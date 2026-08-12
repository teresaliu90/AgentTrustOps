"""Provider-side outcome inspection contracts for safe reconciliation.

An agent or API caller must never decide whether an uncertain side effect
committed.  A server-owned probe implements this contract and checks the
provider using the stable idempotency key or another authoritative reference.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from enum import StrEnum
from typing import Any, Protocol


class ProviderOutcome(StrEnum):
    """Conclusions an authoritative provider lookup may return."""

    COMMITTED = "committed"
    NOT_COMMITTED = "not_committed"
    PENDING = "pending"


@dataclass(frozen=True, slots=True)
class ProviderLookup:
    """Trusted lookup input built from the persisted governed request."""

    run_id: str
    action_name: str
    tenant_id: str
    idempotency_key: str
    arguments: dict[str, Any] = field(default_factory=dict)

    def __post_init__(self) -> None:
        for value, name in (
            (self.run_id, "run_id"),
            (self.action_name, "action_name"),
            (self.tenant_id, "tenant_id"),
            (self.idempotency_key, "idempotency_key"),
        ):
            if not value.strip():
                raise ValueError(f"{name} cannot be empty")
        object.__setattr__(self, "arguments", _json_copy(self.arguments))


@dataclass(frozen=True, slots=True)
class ProviderObservation:
    """Privacy-reviewed conclusion returned by a provider probe.

    ``summary``, ``reference`` and ``safe_result`` are persisted in the audit
    trail.  Probes must never put raw provider responses, credentials, or
    customer data in these fields.
    """

    outcome: ProviderOutcome
    summary: str
    reference: str | None = None
    safe_result: Any = None

    def __post_init__(self) -> None:
        if not isinstance(self.outcome, ProviderOutcome):
            raise TypeError("provider observation outcome must be ProviderOutcome")
        summary = self.summary.strip()
        if not summary:
            raise ValueError("provider observation summary cannot be empty")
        if len(summary) > 500:
            raise ValueError(
                "provider observation summary cannot exceed 500 characters"
            )
        reference = None if self.reference is None else self.reference.strip()
        if reference is not None and not reference:
            reference = None
        if reference is not None and len(reference) > 255:
            raise ValueError("provider reference cannot exceed 255 characters")
        object.__setattr__(self, "summary", summary)
        object.__setattr__(self, "reference", reference)
        object.__setattr__(self, "safe_result", _json_copy(self.safe_result))


class ProviderProbe(Protocol):
    """Server-owned adapter that authoritatively inspects one side effect."""

    name: str

    def lookup(self, request: ProviderLookup) -> ProviderObservation: ...


class ProviderLookupError(RuntimeError):
    """A provider could not be inspected; the run must remain unknown."""


def validate_provider_name(name: str) -> str:
    if not isinstance(name, str):
        raise TypeError("provider probe name must be a string")
    normalized = name.strip()
    if not normalized:
        raise ValueError("provider probe name cannot be empty")
    if len(normalized) > 100:
        raise ValueError("provider probe name cannot exceed 100 characters")
    return normalized


def _json_copy(value: Any) -> Any:
    try:
        return json.loads(
            json.dumps(value, sort_keys=True, separators=(",", ":"), allow_nan=False)
        )
    except (TypeError, ValueError, UnicodeError) as error:
        raise ValueError(
            "provider reconciliation data must be JSON serializable"
        ) from error
