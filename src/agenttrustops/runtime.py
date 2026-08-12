"""Decorator-backed reliable action execution."""

from __future__ import annotations

import asyncio
import inspect
import threading
from collections.abc import Awaitable, Callable
from functools import update_wrapper
from typing import Any, Literal, Never, Protocol, Self, TypeVar, cast
from uuid import uuid4

from .errors import ApprovalDenied
from .ledger import SQLiteActionLedger, request_fingerprint
from .models import (
    ActionContext,
    ActionExecutionContext,
    ActionResult,
    ActionStatus,
    PolicyDecision,
    PolicyOutcome,
    VerifiedPrincipal,
)
from .providers import (
    ProviderLookup,
    ProviderObservation,
    ProviderOutcome,
    ProviderProbe,
    validate_provider_name,
)

T = TypeVar("T")
Arguments = dict[str, Any]
IdempotencyKey = Callable[[Arguments, ActionContext], str]


class IndeterminateOutcome(Exception):
    """Signal that a provider may have committed a side effect before failing."""


class _LeaseHeartbeat:
    """Renew a live execution claim while user code is still running."""

    def __init__(
        self,
        ledger: SQLiteActionLedger,
        run_id: str,
        owner: str,
        lease_seconds: int,
    ):
        self.ledger = ledger
        self.run_id = run_id
        self.owner = owner
        self.lease_seconds = lease_seconds
        self._stop = threading.Event()
        self._thread: threading.Thread | None = None

    def __enter__(self) -> Self:
        interval = max(0.25, self.lease_seconds / 3)

        def renew() -> None:
            while not self._stop.wait(interval):
                if not self.ledger.heartbeat_execution(
                    self.run_id,
                    owner=self.owner,
                    lease_seconds=self.lease_seconds,
                ):
                    return

        self._thread = threading.Thread(
            target=renew,
            name=f"agenttrustops-heartbeat-{self.run_id}",
            daemon=True,
        )
        self._thread.start()
        return self

    def __exit__(self, *args: object) -> Literal[False]:
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=1)
        return False


class ActionPolicy(Protocol):
    def evaluate(
        self,
        action_name: str,
        arguments: Arguments,
        context: ActionContext,
    ) -> PolicyDecision: ...


class TrustedAction:
    """Callable metadata plus the intended guarded route to protected code."""

    def __init__(
        self,
        function: Callable[..., T],
        *,
        ledger: SQLiteActionLedger,
        policy: ActionPolicy,
        idempotency_key: IdempotencyKey,
        risk: str,
        name: str | None = None,
        execution_lease_seconds: int = 60,
        approval_ttl_seconds: int = 3600,
        approval_roles: tuple[str, ...] = ("agenttrustops_approver",),
        reconciliation_roles: tuple[str, ...] = ("agenttrustops_reconciler",),
        allow_self_approval: bool = False,
        execution_context_parameter: str | None = None,
    ):
        self.function = function
        self.ledger = ledger
        self.policy = policy
        self.idempotency_key_factory = idempotency_key
        self.risk = risk.strip()
        self.name = (name or function.__name__).strip()
        if not self.risk:
            raise ValueError("risk cannot be empty")
        if not self.name:
            raise ValueError("action name cannot be empty")
        if not 1 <= execution_lease_seconds <= 86400:
            raise ValueError("execution_lease_seconds must be between 1 and 86400")
        if not 1 <= approval_ttl_seconds <= 604800:
            raise ValueError("approval_ttl_seconds must be between 1 and 604800")
        self.execution_lease_seconds = execution_lease_seconds
        self.approval_ttl_seconds = approval_ttl_seconds
        self.approval_roles = tuple(
            sorted({role.strip() for role in approval_roles if role.strip()})
        )
        self.reconciliation_roles = tuple(
            sorted({role.strip() for role in reconciliation_roles if role.strip()})
        )
        if not self.approval_roles or not self.reconciliation_roles:
            raise ValueError("approval and reconciliation roles cannot be empty")
        self.allow_self_approval = allow_self_approval
        self.execution_context_parameter = self._validate_execution_context_parameter(
            execution_context_parameter
        )
        update_wrapper(self, function)

    def _validate_execution_context_parameter(self, name: str | None) -> str | None:
        if name is None:
            return None
        normalized = name.strip()
        if not normalized:
            raise ValueError("execution_context_parameter cannot be empty")
        parameter = inspect.signature(self.function).parameters.get(normalized)
        if parameter is None:
            raise ValueError(
                f"protected function has no execution context parameter: {normalized}"
            )
        if parameter.kind not in {
            inspect.Parameter.POSITIONAL_OR_KEYWORD,
            inspect.Parameter.KEYWORD_ONLY,
        }:
            raise ValueError("execution context parameter must accept a keyword value")
        return normalized

    def __call__(self, *args: Any, **kwargs: Any) -> Never:
        method = "invoke_async" if self.is_async else "invoke"
        raise TypeError(
            f"trusted actions cannot be called directly; use .{method}(context=..., "
            "**arguments)"
        )

    @property
    def is_async(self) -> bool:
        """Whether the protected tool is declared with ``async def``."""

        return inspect.iscoroutinefunction(self.function)

    def invoke(self, *, context: ActionContext, **arguments: Any) -> ActionResult:
        if self.is_async:
            raise TypeError("async trusted actions require 'await .invoke_async(...)'")
        prepared = self._prepare_invoke(context, arguments)
        if isinstance(prepared, ActionResult):
            return prepared
        return self._execute(prepared, arguments)

    def invoke_request(
        self,
        *,
        context: ActionContext,
        arguments: Arguments,
        idempotency_key: str,
    ) -> ActionResult:
        """Invoke a sync action with a gateway-supplied idempotency key."""

        if self.is_async:
            raise TypeError(
                "async trusted actions require 'await .invoke_request_async(...)'"
            )
        prepared = self._prepare_invoke(
            context,
            dict(arguments),
            idempotency_key_override=idempotency_key,
        )
        if isinstance(prepared, ActionResult):
            return prepared
        return self._execute(prepared, dict(arguments))

    async def invoke_async(
        self,
        *,
        context: ActionContext,
        **arguments: Any,
    ) -> ActionResult:
        """Evaluate policy and await an asynchronous protected tool."""

        if not self.is_async:
            raise TypeError("sync trusted actions require '.invoke(...)'")
        prepared = self._prepare_invoke(context, arguments)
        if isinstance(prepared, ActionResult):
            return prepared
        return await self._execute_async(prepared, arguments)

    async def invoke_request_async(
        self,
        *,
        context: ActionContext,
        arguments: Arguments,
        idempotency_key: str,
    ) -> ActionResult:
        """Invoke an async action with a gateway-supplied idempotency key."""

        if not self.is_async:
            raise TypeError("sync trusted actions require '.invoke_request(...)'")
        prepared = self._prepare_invoke(
            context,
            dict(arguments),
            idempotency_key_override=idempotency_key,
        )
        if isinstance(prepared, ActionResult):
            return prepared
        return await self._execute_async(prepared, dict(arguments))

    def _prepare_invoke(
        self,
        context: ActionContext,
        arguments: Arguments,
        *,
        idempotency_key_override: str | None = None,
    ) -> str | ActionResult:
        if (
            self.execution_context_parameter is not None
            and self.execution_context_parameter in arguments
        ):
            raise ValueError("execution context is supplied only by AgentTrustOps")
        key = (
            idempotency_key_override
            if idempotency_key_override is not None
            else self.idempotency_key_factory(arguments, context)
        ).strip()
        if not key:
            raise ValueError("idempotency key cannot be empty")
        fingerprint = request_fingerprint(
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            roles=context.roles,
            evidence=context.evidence,
            action_name=self.name,
            risk=self.risk,
            arguments=arguments,
            metadata=context.metadata,
        )
        run_id = f"run_{uuid4().hex}"
        run, created = self.ledger.create_or_get_run(
            run_id=run_id,
            tenant_id=context.tenant_id,
            actor_id=context.actor_id,
            roles=context.roles,
            evidence=context.evidence,
            action_name=self.name,
            risk=self.risk,
            idempotency_key=key,
            request_fingerprint=fingerprint,
            arguments=arguments,
            metadata=context.metadata,
        )
        if not created:
            self.ledger.expire_approvals(tenant_id=context.tenant_id)
            self.ledger.recover_expired_executions(tenant_id=context.tenant_id)
            self.ledger.record_duplicate(run["run_id"])
            return self._result_from_run(
                self.ledger.get_run(run["run_id"]), duplicate=True
            )
        try:
            decision = self.policy.evaluate(self.name, arguments, context)
        except Exception as error:  # noqa: BLE001 - policy plug-ins are untrusted boundaries
            decision = PolicyDecision(
                PolicyOutcome.DENY,
                f"policy evaluation failed: {type(error).__name__}",
                "policy-error",
                {"error_type": type(error).__name__},
            )
        try:
            self.ledger.record_policy_decision(
                run_id,
                decision,
                approval_ttl_seconds=self.approval_ttl_seconds,
            )
        except (TypeError, ValueError, UnicodeError) as error:
            decision = PolicyDecision(
                PolicyOutcome.DENY,
                f"policy decision could not be serialized: {type(error).__name__}",
                "policy-error",
                {"error_type": type(error).__name__},
            )
            self.ledger.record_policy_decision(
                run_id,
                decision,
                approval_ttl_seconds=self.approval_ttl_seconds,
            )
        if decision.outcome is not PolicyOutcome.ALLOW:
            return self._result_from_run(self.ledger.get_run(run_id))
        return run_id

    def approve(
        self,
        run_id: str,
        *,
        principal: VerifiedPrincipal,
        note: str,
    ) -> ActionResult:
        if not note.strip():
            raise ValueError("approval note is required")
        if not self.ledger.decide_approval(
            run_id,
            approved=True,
            principal=principal,
            note=note.strip(),
            required_roles=self.approval_roles,
            allow_self_approval=self.allow_self_approval,
        ):
            run = self.ledger.get_run(run_id)
            if run is not None and run["status"] == ActionStatus.APPROVAL_EXPIRED.value:
                raise ApprovalDenied("approval request has expired")
            raise ValueError("run is not waiting for approval")
        return self._result_from_run(self.ledger.get_run(run_id))

    def reject(
        self,
        run_id: str,
        *,
        principal: VerifiedPrincipal,
        note: str,
    ) -> ActionResult:
        if not note.strip():
            raise ValueError("rejection note is required")
        if not self.ledger.decide_approval(
            run_id,
            approved=False,
            principal=principal,
            note=note.strip(),
            required_roles=self.approval_roles,
            allow_self_approval=self.allow_self_approval,
        ):
            run = self.ledger.get_run(run_id)
            if run is not None and run["status"] == ActionStatus.APPROVAL_EXPIRED.value:
                raise ApprovalDenied("approval request has expired")
            raise ValueError("run is not waiting for approval")
        return self._result_from_run(self.ledger.get_run(run_id))

    def reconcile(
        self,
        run_id: str,
        *,
        outcome: str,
        principal: VerifiedPrincipal,
        note: str,
        result: Any = None,
    ) -> ActionResult:
        """Resolve an ``unknown`` run after checking the external provider."""

        if outcome not in {ActionStatus.COMPLETED.value, ActionStatus.FAILED.value}:
            raise ValueError("outcome must be 'completed' or 'failed'")
        if not note.strip():
            raise ValueError("reconciliation note is required")
        if not set(self.reconciliation_roles).intersection(principal.roles):
            raise ApprovalDenied("principal lacks a required reconciliation role")
        run = self.ledger.get_run(run_id)
        if run is None:
            raise KeyError("run not found")
        if run["action_name"] != self.name:
            raise ValueError("run belongs to a different action")
        if run["tenant_id"] != principal.tenant_id:
            raise ApprovalDenied(
                "reconciliation operator belongs to a different tenant"
            )
        status = ActionStatus(outcome)
        if not self.ledger.reconcile_run(
            run_id,
            status,
            reason=note.strip(),
            result=result,
            principal=principal,
        ):
            raise ValueError("run is not waiting for reconciliation")
        return self._result_from_run(self.ledger.get_run(run_id))

    def reconcile_from_provider(
        self,
        run_id: str,
        *,
        probe: ProviderProbe,
        principal: VerifiedPrincipal,
    ) -> ActionResult:
        """Inspect an authoritative provider before resolving an unknown run.

        The lookup input comes from the persisted request, never from an agent
        or reconciliation HTTP body.  A pending observation records evidence
        but deliberately leaves the run in ``unknown``.
        """

        run = self._load_reconcilable_run(run_id, principal=principal)
        provider = validate_provider_name(probe.name)
        observation = probe.lookup(
            ProviderLookup(
                run_id=run_id,
                action_name=self.name,
                tenant_id=str(run["tenant_id"]),
                idempotency_key=str(run["idempotency_key"]),
                created_at=str(run["created_at"]),
                arguments=dict(run["arguments"]),
            )
        )
        if not isinstance(observation, ProviderObservation):
            raise TypeError("provider probe must return ProviderObservation")
        status: ActionStatus | None = None
        result: dict[str, Any] = {"provider": provider}
        if observation.outcome is not ProviderOutcome.PENDING:
            status = (
                ActionStatus.COMPLETED
                if observation.outcome is ProviderOutcome.COMMITTED
                else ActionStatus.FAILED
            )
            if observation.reference is not None:
                result["provider_reference"] = observation.reference
            if observation.safe_result is not None:
                result["safe_result"] = observation.safe_result
        applied = self.ledger.apply_provider_observation(
            run_id,
            provider=provider,
            outcome=observation.outcome.value,
            summary=observation.summary,
            reference=observation.reference,
            status=status,
            result=None if status is None else result,
            principal=principal,
        )
        if not applied:
            return self._result_from_run(self.ledger.get_run(run_id), duplicate=True)
        return self._result_from_run(self.ledger.get_run(run_id))

    def _load_reconcilable_run(
        self,
        run_id: str,
        *,
        principal: VerifiedPrincipal,
    ) -> dict[str, Any]:
        if not set(self.reconciliation_roles).intersection(principal.roles):
            raise ApprovalDenied("principal lacks a required reconciliation role")
        run = self.ledger.get_run(run_id)
        if run is None:
            raise KeyError("run not found")
        if run["action_name"] != self.name:
            raise ValueError("run belongs to a different action")
        if run["tenant_id"] != principal.tenant_id:
            raise ApprovalDenied(
                "reconciliation operator belongs to a different tenant"
            )
        if run["status"] != ActionStatus.UNKNOWN.value:
            raise ValueError("run is not waiting for reconciliation")
        return run

    def resume(self, run_id: str) -> ActionResult:
        if self.is_async:
            raise TypeError("async trusted actions require 'await .resume_async(...)'")
        run = self._prepare_resume(run_id)
        if isinstance(run, ActionResult):
            return run
        return self._execute(run_id, run["arguments"])

    async def resume_async(self, run_id: str) -> ActionResult:
        """Resume an approved asynchronous action and await its tool call."""

        if not self.is_async:
            raise TypeError("sync trusted actions require '.resume(...)'")
        run = self._prepare_resume(run_id)
        if isinstance(run, ActionResult):
            return run
        return await self._execute_async(run_id, run["arguments"])

    def _prepare_resume(self, run_id: str) -> dict[str, Any] | ActionResult:
        run = self.ledger.get_run(run_id)
        if run is None:
            raise KeyError("run not found")
        if run["action_name"] != self.name:
            raise ValueError("run belongs to a different action")
        if run["status"] == ActionStatus.COMPLETED.value:
            return self._result_from_run(run, duplicate=True)
        if run["status"] != ActionStatus.APPROVED.value:
            raise ValueError("run must be approved before it can resume")
        return run

    def audit_trail(
        self,
        run_id: str,
        *,
        principal: VerifiedPrincipal | None = None,
    ) -> dict[str, Any] | None:
        return self.ledger.audit_trail(run_id, principal=principal)

    def _execute(self, run_id: str, arguments: Arguments) -> ActionResult:
        owner = f"worker_{uuid4().hex}"
        if not self.ledger.claim_execution(
            run_id,
            owner=owner,
            lease_seconds=self.execution_lease_seconds,
        ):
            run = self.ledger.get_run(run_id)
            if run is None:
                raise KeyError("run not found")
            return self._result_from_run(run, duplicate=True)

        try:
            with _LeaseHeartbeat(
                self.ledger,
                run_id,
                owner,
                self.execution_lease_seconds,
            ):
                value = self.function(
                    **self._arguments_with_execution_context(run_id, arguments)
                )
        except IndeterminateOutcome as error:
            return self._mark_unknown(run_id, owner, type(error).__name__)
        except Exception as error:  # noqa: BLE001 - convert tool failure into a safe run state
            self.ledger.fail_execution(
                run_id, owner=owner, error_type=type(error).__name__
            )
            return self._result_from_run(self.ledger.get_run(run_id))

        try:
            self.ledger.complete_execution(run_id, owner=owner, result=value)
        except (TypeError, ValueError):
            return self._mark_unknown(run_id, owner, "ResultSerializationError")
        return self._result_from_run(self.ledger.get_run(run_id))

    async def _execute_async(
        self,
        run_id: str,
        arguments: Arguments,
    ) -> ActionResult:
        owner = f"worker_{uuid4().hex}"
        if not self.ledger.claim_execution(
            run_id,
            owner=owner,
            lease_seconds=self.execution_lease_seconds,
        ):
            run = self.ledger.get_run(run_id)
            if run is None:
                raise KeyError("run not found")
            return self._result_from_run(run, duplicate=True)

        try:
            with _LeaseHeartbeat(
                self.ledger,
                run_id,
                owner,
                self.execution_lease_seconds,
            ):
                value = await cast(
                    Awaitable[Any],
                    self.function(
                        **self._arguments_with_execution_context(run_id, arguments)
                    ),
                )
        except asyncio.CancelledError:
            self._mark_unknown(run_id, owner, "CancelledError")
            raise
        except IndeterminateOutcome as error:
            return self._mark_unknown(run_id, owner, type(error).__name__)
        except Exception as error:  # noqa: BLE001 - convert tool failure into a safe run state
            self.ledger.fail_execution(
                run_id, owner=owner, error_type=type(error).__name__
            )
            return self._result_from_run(self.ledger.get_run(run_id))

        try:
            self.ledger.complete_execution(run_id, owner=owner, result=value)
        except (TypeError, ValueError):
            return self._mark_unknown(run_id, owner, "ResultSerializationError")
        return self._result_from_run(self.ledger.get_run(run_id))

    def _mark_unknown(
        self,
        run_id: str,
        owner: str,
        error_type: str,
    ) -> ActionResult:
        self.ledger.mark_execution_unknown(
            run_id,
            owner=owner,
            error_type=error_type,
        )
        return self._result_from_run(self.ledger.get_run(run_id))

    def _arguments_with_execution_context(
        self,
        run_id: str,
        arguments: Arguments,
    ) -> Arguments:
        values = dict(arguments)
        parameter = self.execution_context_parameter
        if parameter is None:
            return values
        run = self.ledger.get_run(run_id)
        if run is None:
            raise KeyError("run not found")
        values[parameter] = ActionExecutionContext(
            run_id=str(run["run_id"]),
            action_name=str(run["action_name"]),
            tenant_id=str(run["tenant_id"]),
            idempotency_key=str(run["idempotency_key"]),
            attempt=int(run["attempt"]),
        )
        return values

    @staticmethod
    def _result_from_run(
        run: dict[str, Any] | None,
        *,
        duplicate: bool = False,
    ) -> ActionResult:
        if run is None:
            raise KeyError("run not found")
        return ActionResult(
            run_id=run["run_id"],
            action_name=run["action_name"],
            status=ActionStatus(run["status"]),
            idempotency_key=run["idempotency_key"],
            policy_version=run["policy_version"],
            reason=run["reason"],
            value=run["result"],
            duplicate=duplicate,
            attempt=run["attempt"],
        )


def trusted_action(
    *,
    ledger: SQLiteActionLedger,
    policy: ActionPolicy,
    idempotency_key: IdempotencyKey,
    risk: str,
    name: str | None = None,
    execution_lease_seconds: int = 60,
    approval_ttl_seconds: int = 3600,
    approval_roles: tuple[str, ...] = ("agenttrustops_approver",),
    reconciliation_roles: tuple[str, ...] = ("agenttrustops_reconciler",),
    allow_self_approval: bool = False,
    execution_context_parameter: str | None = None,
) -> Callable[[Callable[..., T]], TrustedAction]:
    """Protect a business action behind policy, approval, and idempotency."""

    def decorator(function: Callable[..., T]) -> TrustedAction:
        return TrustedAction(
            function,
            ledger=ledger,
            policy=policy,
            idempotency_key=idempotency_key,
            risk=risk,
            name=name,
            execution_lease_seconds=execution_lease_seconds,
            approval_ttl_seconds=approval_ttl_seconds,
            approval_roles=approval_roles,
            reconciliation_roles=reconciliation_roles,
            allow_self_approval=allow_self_approval,
            execution_context_parameter=execution_context_parameter,
        )

    return decorator
