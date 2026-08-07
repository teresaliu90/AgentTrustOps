"""Small, serializable contracts shared by policies, ledgers, and actions."""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


class PolicyOutcome(StrEnum):
    ALLOW = "allow"
    DENY = "deny"
    APPROVAL_REQUIRED = "approval_required"


class ActionStatus(StrEnum):
    CREATED = "created"
    DENIED = "denied"
    PENDING_APPROVAL = "pending_approval"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXECUTING = "executing"
    UNKNOWN = "unknown"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ActionContext:
    """Identity and evidence supplied by the trusted application boundary.

    ``tenant_id`` and ``roles`` are SDK inputs, not authenticated identity on
    their own. A production application must derive them from a trusted IdP or
    gateway rather than accepting arbitrary model/user claims.
    """

    actor_id: str
    tenant_id: str = "default"
    roles: tuple[str, ...] = ()
    evidence: tuple[str, ...] = ()
    metadata: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reason: str
    policy_version: str
    facts: dict[str, Any] = field(default_factory=dict)


@dataclass(frozen=True, slots=True)
class ActionResult:
    run_id: str
    action_name: str
    status: ActionStatus
    idempotency_key: str
    policy_version: str | None = None
    reason: str | None = None
    value: Any = None
    duplicate: bool = False

    @property
    def executed(self) -> bool:
        return self.status is ActionStatus.COMPLETED

    def to_dict(self) -> dict[str, Any]:
        return {
            "run_id": self.run_id,
            "action_name": self.action_name,
            "status": self.status.value,
            "idempotency_key": self.idempotency_key,
            "policy_version": self.policy_version,
            "reason": self.reason,
            "value": self.value,
            "duplicate": self.duplicate,
        }
