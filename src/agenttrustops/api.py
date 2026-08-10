"""Optional FastAPI control plane for governed actions.

Install with ``pip install 'agenttrustops[api]'``. The service authenticates a
credential before deriving actor, tenant, and roles; those fields are never
accepted from an invocation request body.
"""

from collections.abc import Callable
from importlib.resources import files
from typing import Annotated, Any, Literal, Protocol
from uuid import uuid4

from fastapi import (
    Depends,
    FastAPI,
    Header,
    HTTPException,
    Query,
    Request,
    Response,
    status,
)
from fastapi.responses import HTMLResponse, JSONResponse, PlainTextResponse
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .auth import AuthenticationError, IdentityVerifier
from .errors import ApprovalDenied, IdempotencyConflict, InvalidTransition
from .models import ActionContext, ActionResult, ActionStatus, VerifiedPrincipal
from .observability import collect_operational_snapshot, render_prometheus
from .registry import ActionRegistry


class InvocationContextResolver(Protocol):
    """Resolve policy evidence from trusted application data sources."""

    def __call__(
        self,
        principal: VerifiedPrincipal,
        action_name: str,
        arguments: dict[str, Any],
        evidence_refs: tuple[str, ...],
    ) -> ActionContext: ...


class PrincipalContextResolver:
    """Safe default for actions that do not require external evidence."""

    def __call__(
        self,
        principal: VerifiedPrincipal,
        action_name: str,
        arguments: dict[str, Any],
        evidence_refs: tuple[str, ...],
    ) -> ActionContext:
        if evidence_refs:
            raise ValueError(
                "evidence_refs require a server-side InvocationContextResolver"
            )
        return ActionContext(
            actor_id=principal.actor_id,
            tenant_id=principal.tenant_id,
            roles=principal.roles,
            metadata={"identity_source": principal.auth_source},
        )


class StrictRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")


class InvokeRequest(StrictRequest):
    arguments: dict[str, Any] = Field(default_factory=dict)
    evidence_refs: list[Annotated[str, Field(min_length=1, max_length=255)]] = Field(
        default_factory=list,
        max_length=100,
    )


class DecisionRequest(StrictRequest):
    note: str = Field(min_length=3, max_length=2000)


class ReconcileRequest(DecisionRequest):
    outcome: Literal["completed", "failed"]
    result: Any = None


def create_app(
    registry: ActionRegistry,
    identity_verifier: IdentityVerifier,
    *,
    context_resolver: InvocationContextResolver | None = None,
    invoker_role: str = "agenttrustops_invoker",
    viewer_role: str = "agenttrustops_viewer",
    executor_role: str = "agenttrustops_executor",
    observer_role: str = "agenttrustops_observer",
    operator_role: str = "agenttrustops_operator",
) -> FastAPI:
    """Build an authenticated, tenant-scoped control-plane application."""

    resolve_context = context_resolver or PrincipalContextResolver()
    app = FastAPI(
        title="AgentTrustOps Control Plane",
        version="0.3.0",
        description=(
            "Policy, approval, idempotency, reconciliation, and audit endpoints "
            "for explicitly registered agent actions."
        ),
    )

    @app.middleware("http")
    async def request_identity(
        request: Request, call_next: Callable[..., Any]
    ) -> Response:
        request_id = request.headers.get("X-Request-ID", f"req_{uuid4().hex}")[:128]
        response = await call_next(request)
        response.headers["X-Request-ID"] = request_id
        response.headers["Cache-Control"] = "no-store"
        if request.url.path == "/ui" or request.url.path.startswith("/ui/"):
            response.headers["Content-Security-Policy"] = (
                "default-src 'none'; style-src 'self'; script-src 'self'; "
                "connect-src 'self'; img-src 'self' data:; base-uri 'none'; "
                "frame-ancestors 'none'; form-action 'none'"
            )
            response.headers["X-Content-Type-Options"] = "nosniff"
            response.headers["Referrer-Policy"] = "no-referrer"
        return response

    async def principal(
        authorization: str | None = Header(default=None, alias="Authorization"),
    ) -> VerifiedPrincipal:
        if not authorization or not authorization.startswith("Bearer "):
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail="bearer credential required",
                headers={"WWW-Authenticate": "Bearer"},
            )
        credential = authorization.removeprefix("Bearer ").strip()
        try:
            return identity_verifier.verify(credential)
        except AuthenticationError as error:
            raise HTTPException(
                status_code=status.HTTP_401_UNAUTHORIZED,
                detail=str(error),
                headers={"WWW-Authenticate": "Bearer"},
            ) from error

    def require_role(identity: VerifiedPrincipal, role: str) -> None:
        if role not in identity.roles:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"verified principal lacks required role: {role}",
            )

    def load_tenant_run(run_id: str, identity: VerifiedPrincipal) -> dict[str, Any]:
        run = registry.ledger.get_run(run_id)
        if run is None:
            raise HTTPException(status_code=404, detail="run not found")
        if run["tenant_id"] != identity.tenant_id:
            raise HTTPException(status_code=404, detail="run not found")
        return run

    def visible_run(run_id: str, identity: VerifiedPrincipal) -> dict[str, Any]:
        trail = registry.ledger.audit_trail(run_id, principal=identity)
        if trail is None:
            raise HTTPException(status_code=404, detail="run not found")
        return trail["run"]

    @app.exception_handler(IdempotencyConflict)
    async def idempotency_conflict(
        request: Request,
        error: IdempotencyConflict,
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(InvalidTransition)
    async def invalid_transition(
        request: Request,
        error: InvalidTransition,
    ) -> JSONResponse:
        return JSONResponse(status_code=409, content={"detail": str(error)})

    @app.exception_handler(ApprovalDenied)
    async def approval_denied(
        request: Request,
        error: ApprovalDenied,
    ) -> JSONResponse:
        return JSONResponse(status_code=403, content={"detail": str(error)})

    @app.get("/healthz", tags=["operations"])
    async def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/readyz", tags=["operations"])
    async def readiness() -> dict[str, Any]:
        return {"status": "ready", "ledger": registry.ledger.schema_info()}

    @app.get("/ui", tags=["console"], response_class=HTMLResponse)
    async def control_plane_ui() -> HTMLResponse:
        """Serve the credential-local operations console shell."""

        return HTMLResponse(_static_asset("control-plane.html"))

    @app.get("/ui/control-plane.css", tags=["console"])
    async def control_plane_css() -> Response:
        return Response(_static_asset("control-plane.css"), media_type="text/css")

    @app.get("/ui/control-plane.js", tags=["console"])
    async def control_plane_js() -> Response:
        return Response(
            _static_asset("control-plane.js"),
            media_type="text/javascript",
        )

    @app.get("/v1/actions", tags=["actions"])
    async def actions(
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
    ) -> dict[str, Any]:
        require_role(identity, viewer_role)
        return {"actions": registry.names()}

    @app.post("/v1/actions/{action_name}/invoke", tags=["actions"])
    async def invoke(
        action_name: str,
        body: InvokeRequest,
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
        idempotency_key: str | None = Header(default=None, alias="Idempotency-Key"),
    ) -> dict[str, Any]:
        require_role(identity, invoker_role)
        if idempotency_key is None or not 8 <= len(idempotency_key.strip()) <= 255:
            raise HTTPException(
                status_code=400,
                detail="Idempotency-Key must contain between 8 and 255 characters",
            )
        try:
            action = registry.get(action_name)
        except KeyError as error:
            raise HTTPException(status_code=404, detail=str(error)) from error
        try:
            context = resolve_context(
                identity,
                action_name,
                dict(body.arguments),
                tuple(body.evidence_refs),
            )
            _validate_resolved_context(identity, context)
            if action.is_async:
                result = await action.invoke_request_async(
                    context=context,
                    arguments=body.arguments,
                    idempotency_key=idempotency_key,
                )
            else:
                result = await run_in_threadpool(
                    action.invoke_request,
                    context=context,
                    arguments=body.arguments,
                    idempotency_key=idempotency_key,
                )
        except ValueError as error:
            raise HTTPException(status_code=400, detail=str(error)) from error
        return _public_result(result)

    @app.get("/v1/runs", tags=["runs"])
    async def runs(
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
        run_status: ActionStatus | None = None,
        limit: Annotated[int, Query(ge=1, le=1000)] = 100,
    ) -> dict[str, Any]:
        require_role(identity, viewer_role)
        listed = registry.ledger.list_runs(
            tenant_id=identity.tenant_id,
            status=run_status,
            limit=limit,
        )
        return {"runs": [visible_run(str(run["run_id"]), identity) for run in listed]}

    @app.get("/v1/runs/{run_id}/audit", tags=["runs"])
    async def audit(
        run_id: str,
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
    ) -> dict[str, Any]:
        require_role(identity, viewer_role)
        load_tenant_run(run_id, identity)
        trail = registry.ledger.audit_trail(run_id, principal=identity)
        if trail is None:
            raise HTTPException(status_code=404, detail="run not found")
        return trail

    @app.get("/v1/approvals", tags=["approvals"])
    async def approvals(
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
    ) -> dict[str, Any]:
        require_role(identity, viewer_role)
        pending = registry.ledger.list_runs(
            tenant_id=identity.tenant_id,
            status=ActionStatus.PENDING_APPROVAL,
            limit=1000,
        )
        return {
            "approvals": [visible_run(str(run["run_id"]), identity) for run in pending]
        }

    @app.post("/v1/runs/{run_id}/approve", tags=["approvals"])
    async def approve(
        run_id: str,
        body: DecisionRequest,
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
    ) -> dict[str, Any]:
        run = load_tenant_run(run_id, identity)
        action = registry.get(str(run["action_name"]))
        result = await run_in_threadpool(
            action.approve,
            run_id,
            principal=identity,
            note=body.note,
        )
        return _public_result(result)

    @app.post("/v1/runs/{run_id}/reject", tags=["approvals"])
    async def reject(
        run_id: str,
        body: DecisionRequest,
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
    ) -> dict[str, Any]:
        run = load_tenant_run(run_id, identity)
        action = registry.get(str(run["action_name"]))
        result = await run_in_threadpool(
            action.reject,
            run_id,
            principal=identity,
            note=body.note,
        )
        return _public_result(result)

    @app.post("/v1/runs/{run_id}/resume", tags=["actions"])
    async def resume(
        run_id: str,
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
    ) -> dict[str, Any]:
        require_role(identity, executor_role)
        run = load_tenant_run(run_id, identity)
        action = registry.get(str(run["action_name"]))
        if action.is_async:
            result = await action.resume_async(run_id)
        else:
            result = await run_in_threadpool(action.resume, run_id)
        return _public_result(result)

    @app.post("/v1/runs/{run_id}/reconcile", tags=["operations"])
    async def reconcile(
        run_id: str,
        body: ReconcileRequest,
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
    ) -> dict[str, Any]:
        run = load_tenant_run(run_id, identity)
        action = registry.get(str(run["action_name"]))
        result = await run_in_threadpool(
            action.reconcile,
            run_id,
            outcome=body.outcome,
            principal=identity,
            note=body.note,
            result=body.result,
        )
        return _public_result(result)

    @app.post("/v1/operations/recover", tags=["operations"])
    async def recover(
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
    ) -> dict[str, Any]:
        require_role(identity, operator_role)
        expired = await run_in_threadpool(
            registry.ledger.expire_approvals,
            tenant_id=identity.tenant_id,
        )
        recovered = await run_in_threadpool(
            registry.ledger.recover_expired_executions,
            tenant_id=identity.tenant_id,
        )
        return {
            "recovered_executions": len(recovered),
            "execution_run_ids": recovered,
            "expired_approvals": len(expired),
            "approval_run_ids": expired,
        }

    @app.get("/metrics", tags=["operations"], response_class=PlainTextResponse)
    async def metrics(
        identity: Annotated[VerifiedPrincipal, Depends(principal)],
    ) -> PlainTextResponse:
        require_role(identity, observer_role)
        snapshot = collect_operational_snapshot(
            registry.ledger,
            tenant_id=identity.tenant_id,
        )
        return PlainTextResponse(
            render_prometheus(snapshot),
            media_type="text/plain; version=0.0.4; charset=utf-8",
        )

    return app


def _validate_resolved_context(
    principal: VerifiedPrincipal,
    context: ActionContext,
) -> None:
    if (
        context.actor_id != principal.actor_id
        or context.tenant_id != principal.tenant_id
    ):
        raise ValueError("context resolver changed verified actor or tenant")
    if not set(context.roles).issubset(principal.roles):
        raise ValueError("context resolver added an unverified role")


def _public_result(result: ActionResult) -> dict[str, Any]:
    """Exclude idempotency keys, credentials, request bodies, and evidence by default."""

    return result.to_public_dict()


def _static_asset(name: str) -> str:
    return files("agenttrustops").joinpath("static", name).read_text(encoding="utf-8")
