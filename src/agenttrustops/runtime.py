"""Decorator-backed reliable action execution."""

from __future__ import annotations

from collections.abc import Callable
from functools import update_wrapper
from typing import Any, Protocol, TypeVar
from uuid import uuid4

from .ledger import SQLiteActionLedger
from .models import (
    ActionContext,
    ActionResult,
    ActionStatus,
    PolicyDecision,
    PolicyOutcome,
)

T = TypeVar("T")
Arguments = dict[str, Any]
IdempotencyKey = Callable[[Arguments, ActionContext], str]


class ActionPolicy(Protocol):
    def evaluate(
        self,
        action_name: str,
        arguments: Arguments,
        context: ActionContext,
    ) -> PolicyDecision: ...


class TrustedAction:
    """Callable metadata plus the only guarded route to the wrapped function."""

    def __init__(
        self,
        function: Callable[..., T],
        *,
        ledger: SQLiteActionLedger,
        policy: ActionPolicy,
        idempotency_key: IdempotencyKey,
        risk: str,
        name: str | None = None,
    ):
        self.function = function
        self.ledger = ledger
        self.policy = policy
        self.idempotency_key_factory = idempotency_key
        self.risk = risk
        self.name = name or function.__name__
        update_wrapper(self, function)

    def __call__(self, *args: Any, **kwargs: Any) -> T:
        raise TypeError(
            "trusted actions cannot be called directly; use .invoke(context=..., **arguments)"
        )

    def invoke(self, *, context: ActionContext, **arguments: Any) -> ActionResult:
        key = self.idempotency_key_factory(arguments, context).strip()
        if not key:
            raise ValueError("idempotency key cannot be empty")
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
            arguments=arguments,
        )
        if not created:
            self.ledger.append_event(
                run["run_id"],
                "retry.skipped_duplicate",
                {"original_status": run["status"]},
            )
            return self._result_from_run(
                self.ledger.get_run(run["run_id"]), duplicate=True
            )

        self.ledger.append_event(
            run_id,
            "run.created",
            {"action_name": self.name, "risk": self.risk},
        )
        try:
            decision = self.policy.evaluate(self.name, arguments, context)
        except Exception as error:  # noqa: BLE001 - policy plug-ins are untrusted boundaries
            safe_reason = f"policy evaluation failed: {type(error).__name__}"
            self.ledger.update_run(run_id, ActionStatus.DENIED, reason=safe_reason)
            self.ledger.append_event(
                run_id,
                "policy.failed",
                {"error_type": type(error).__name__},
            )
            self.ledger.append_event(run_id, "run.denied", {"reason": safe_reason})
            return self._result_from_run(self.ledger.get_run(run_id))
        self.ledger.append_event(
            run_id,
            "policy.checked",
            {
                "outcome": decision.outcome.value,
                "policy_version": decision.policy_version,
                "reason": decision.reason,
                "facts": decision.facts,
            },
        )

        if decision.outcome is PolicyOutcome.DENY:
            self.ledger.update_run(
                run_id,
                ActionStatus.DENIED,
                policy_version=decision.policy_version,
                reason=decision.reason,
            )
            self.ledger.append_event(run_id, "run.denied", {"reason": decision.reason})
            return self._result_from_run(self.ledger.get_run(run_id))

        if decision.outcome is PolicyOutcome.APPROVAL_REQUIRED:
            self.ledger.update_run(
                run_id,
                ActionStatus.PENDING_APPROVAL,
                policy_version=decision.policy_version,
                reason=decision.reason,
            )
            self.ledger.request_approval(run_id)
            self.ledger.append_event(
                run_id,
                "approval.requested",
                {"reason": decision.reason, "policy_version": decision.policy_version},
            )
            return self._result_from_run(self.ledger.get_run(run_id))

        self.ledger.update_run(
            run_id,
            ActionStatus.CREATED,
            policy_version=decision.policy_version,
            reason=decision.reason,
        )
        return self._execute(run_id, arguments)

    def approve(self, run_id: str, *, approver_id: str, note: str) -> ActionResult:
        if not approver_id.strip() or not note.strip():
            raise ValueError("approver_id and note are required")
        if not self.ledger.decide_approval(
            run_id,
            approved=True,
            approver_id=approver_id.strip(),
            note=note.strip(),
        ):
            raise ValueError("run is not waiting for approval")
        self.ledger.append_event(
            run_id,
            "approval.approved",
            {"approver_id": approver_id.strip(), "note": note.strip()},
        )
        return self._result_from_run(self.ledger.get_run(run_id))

    def reject(self, run_id: str, *, approver_id: str, note: str) -> ActionResult:
        if not approver_id.strip() or not note.strip():
            raise ValueError("approver_id and note are required")
        if not self.ledger.decide_approval(
            run_id,
            approved=False,
            approver_id=approver_id.strip(),
            note=note.strip(),
        ):
            raise ValueError("run is not waiting for approval")
        self.ledger.append_event(
            run_id,
            "approval.rejected",
            {"approver_id": approver_id.strip(), "note": note.strip()},
        )
        return self._result_from_run(self.ledger.get_run(run_id))

    def resume(self, run_id: str) -> ActionResult:
        run = self.ledger.get_run(run_id)
        if run is None:
            raise KeyError("run not found")
        if run["action_name"] != self.name:
            raise ValueError("run belongs to a different action")
        if run["status"] == ActionStatus.COMPLETED.value:
            return self._result_from_run(run, duplicate=True)
        if run["status"] != ActionStatus.APPROVED.value:
            raise ValueError("run must be approved before it can resume")
        self.ledger.append_event(run_id, "run.resumed", {})
        return self._execute(run_id, run["arguments"])

    def audit_trail(self, run_id: str) -> dict[str, Any] | None:
        return self.ledger.audit_trail(run_id)

    def _execute(self, run_id: str, arguments: Arguments) -> ActionResult:
        if not self.ledger.claim_execution(run_id):
            run = self.ledger.get_run(run_id)
            if run is None:
                raise KeyError("run not found")
            return self._result_from_run(run, duplicate=True)

        self.ledger.append_event(run_id, "tool.execution.started", {})
        try:
            value = self.function(**arguments)
        except Exception as error:  # noqa: BLE001 - convert tool failure into a safe run state
            safe_reason = f"tool execution failed: {type(error).__name__}"
            self.ledger.update_run(run_id, ActionStatus.FAILED, reason=safe_reason)
            self.ledger.append_event(
                run_id,
                "tool.execution.failed",
                {"error_type": type(error).__name__},
            )
            return self._result_from_run(self.ledger.get_run(run_id))

        self.ledger.update_run(run_id, ActionStatus.COMPLETED, result=value)
        self.ledger.append_event(run_id, "tool.execution.succeeded", {})
        self.ledger.append_event(run_id, "run.completed", {})
        return self._result_from_run(self.ledger.get_run(run_id))

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
        )


def trusted_action(
    *,
    ledger: SQLiteActionLedger,
    policy: ActionPolicy,
    idempotency_key: IdempotencyKey,
    risk: str,
    name: str | None = None,
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
        )

    return decorator
