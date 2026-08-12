"""Small, serializable contracts shared by policies, ledgers, and actions."""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any


def _json_object_copy(value: dict[str, Any], *, field_name: str) -> dict[str, Any]:
    if not isinstance(value, dict):
        raise TypeError(f"{field_name} must be a dictionary")
    try:
        copied = json.loads(
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError(f"{field_name} must be JSON serializable") from error
    return copied


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
    APPROVAL_EXPIRED = "approval_expired"
    EXECUTING = "executing"
    UNKNOWN = "unknown"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ActionExecutionContext:
    """Trusted runtime identity injected only into protected business code.

    This context is constructed from the persisted run after execution is
    claimed. It is never accepted from model arguments or an HTTP request.
    Provider adapters can therefore forward the exact governed idempotency key
    without recomputing it from untrusted input.
    """

    run_id: str
    action_name: str
    tenant_id: str
    idempotency_key: str
    attempt: int

    def __post_init__(self) -> None:
        for value, name in (
            (self.run_id, "run_id"),
            (self.action_name, "action_name"),
            (self.tenant_id, "tenant_id"),
            (self.idempotency_key, "idempotency_key"),
        ):
            normalized = value.strip()
            if not normalized:
                raise ValueError(f"{name} cannot be empty")
            object.__setattr__(self, name, normalized)
        if self.attempt < 1:
            raise ValueError("attempt must be at least one")


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

    def __post_init__(self) -> None:
        actor_id = self.actor_id.strip()
        tenant_id = self.tenant_id.strip()
        if not actor_id:
            raise ValueError("actor_id cannot be empty")
        if not tenant_id:
            raise ValueError("tenant_id cannot be empty")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(
            self,
            "roles",
            tuple(
                sorted({str(role).strip() for role in self.roles if str(role).strip()})
            ),
        )
        object.__setattr__(
            self,
            "evidence",
            tuple(
                sorted(
                    {str(item).strip() for item in self.evidence if str(item).strip()}
                )
            ),
        )
        object.__setattr__(
            self,
            "metadata",
            _json_object_copy(self.metadata, field_name="metadata"),
        )


@dataclass(frozen=True, slots=True)
class VerifiedPrincipal:
    """Identity asserted by a trusted application adapter.

    Constructing this object does not authenticate a user. Production adapters
    must create it only after verifying an OIDC token, service identity, mTLS
    certificate, or an equivalent trusted credential.
    """

    actor_id: str
    tenant_id: str
    roles: tuple[str, ...]
    auth_source: str

    def __post_init__(self) -> None:
        actor_id = self.actor_id.strip()
        tenant_id = self.tenant_id.strip()
        auth_source = self.auth_source.strip()
        if not actor_id or not tenant_id or not auth_source:
            raise ValueError("verified principal fields cannot be empty")
        roles = tuple(
            sorted({str(role).strip() for role in self.roles if str(role).strip()})
        )
        if not roles:
            raise ValueError("verified principal needs at least one role")
        object.__setattr__(self, "actor_id", actor_id)
        object.__setattr__(self, "tenant_id", tenant_id)
        object.__setattr__(self, "auth_source", auth_source)
        object.__setattr__(self, "roles", roles)


@dataclass(frozen=True, slots=True)
class PolicyDecision:
    outcome: PolicyOutcome
    reason: str
    policy_version: str
    facts: dict[str, Any] = field(default_factory=dict)
    policy_digest: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, PolicyOutcome):
            raise TypeError("policy outcome must be PolicyOutcome")
        reason = self.reason.strip()
        policy_version = self.policy_version.strip()
        if not reason:
            raise ValueError("policy decision reason cannot be empty")
        if not policy_version:
            raise ValueError("policy version cannot be empty")
        policy_digest = self.policy_digest
        if policy_digest is not None:
            policy_digest = policy_digest.strip()
            if not policy_digest:
                raise ValueError("policy digest cannot be empty")
        object.__setattr__(self, "reason", reason)
        object.__setattr__(self, "policy_version", policy_version)
        object.__setattr__(self, "policy_digest", policy_digest)
        object.__setattr__(
            self,
            "facts",
            _json_object_copy(self.facts, field_name="policy facts"),
        )


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
    attempt: int = 0

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
            "attempt": self.attempt,
        }

    def to_public_dict(self) -> dict[str, Any]:
        """Return the default API-safe view without the idempotency key."""

        return {
            "run_id": self.run_id,
            "action_name": self.action_name,
            "status": self.status.value,
            "policy_version": self.policy_version,
            "reason": self.reason,
            "value": self.value,
            "attempt": self.attempt,
        }
