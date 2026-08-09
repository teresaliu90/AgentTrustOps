"""Durable operational metrics derived from the action ledger."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from .ledger import SQLiteActionLedger


@dataclass(frozen=True, slots=True)
class OperationalSnapshot:
    """A privacy-safe summary suitable for health pages and alerting."""

    backend: str
    schema_version: int | None
    status_counts: dict[str, int]
    event_counts: dict[str, int]
    approval_counts: dict[str, int]
    duplicate_retries: int
    integrity: dict[str, Any] | None = None
    tenant_id: str | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "backend": self.backend,
            "schema_version": self.schema_version,
            "tenant_id": self.tenant_id,
            "status_counts": self.status_counts,
            "event_counts": self.event_counts,
            "approval_counts": self.approval_counts,
            "duplicate_retries": self.duplicate_retries,
            "integrity": self.integrity,
        }


def collect_operational_snapshot(
    ledger: SQLiteActionLedger,
    *,
    tenant_id: str | None = None,
    verify_integrity: bool = False,
    integrity_limit: int = 10000,
) -> OperationalSnapshot:
    """Collect durable counts without exposing arguments, evidence, or identities."""

    schema = ledger.schema_info()
    integrity = (
        ledger.verify_all_event_chains(tenant_id=tenant_id, limit=integrity_limit)
        if verify_integrity
        else None
    )
    return OperationalSnapshot(
        backend=str(schema["backend"]),
        schema_version=schema["schema_version"],
        tenant_id=tenant_id,
        status_counts=ledger.status_counts(tenant_id=tenant_id),
        event_counts=ledger.event_counts(tenant_id=tenant_id),
        approval_counts=ledger.approval_counts(tenant_id=tenant_id),
        duplicate_retries=ledger.duplicate_retry_count(tenant_id=tenant_id),
        integrity=integrity,
    )


def render_prometheus(snapshot: OperationalSnapshot) -> str:
    """Render a snapshot in the Prometheus text exposition format."""

    tenant = snapshot.tenant_id or "all"
    lines = [
        "# HELP agenttrustops_runs Current governed action runs by status.",
        "# TYPE agenttrustops_runs gauge",
    ]
    for status, count in sorted(snapshot.status_counts.items()):
        lines.append(
            f'agenttrustops_runs{{status="{_label(status)}",tenant="{_label(tenant)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP agenttrustops_events_total Durable action events by type.",
            "# TYPE agenttrustops_events_total counter",
        ]
    )
    for event_type, count in sorted(snapshot.event_counts.items()):
        lines.append(
            "agenttrustops_events_total"
            f'{{event_type="{_label(event_type)}",tenant="{_label(tenant)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP agenttrustops_approvals Approval records by decision state.",
            "# TYPE agenttrustops_approvals gauge",
        ]
    )
    for status, count in sorted(snapshot.approval_counts.items()):
        lines.append(
            "agenttrustops_approvals"
            f'{{status="{_label(status)}",tenant="{_label(tenant)}"}} {count}'
        )
    lines.extend(
        [
            "# HELP agenttrustops_duplicate_retries_total Duplicate invocations suppressed without regenerating the event chain.",
            "# TYPE agenttrustops_duplicate_retries_total counter",
            (
                "agenttrustops_duplicate_retries_total"
                f'{{tenant="{_label(tenant)}"}} {snapshot.duplicate_retries}'
            ),
        ]
    )
    if snapshot.integrity is not None:
        lines.extend(
            [
                "# HELP agenttrustops_event_chains_invalid Invalid event chains found by the latest scan.",
                "# TYPE agenttrustops_event_chains_invalid gauge",
                (
                    "agenttrustops_event_chains_invalid"
                    f'{{tenant="{_label(tenant)}"}} {snapshot.integrity["invalid"]}'
                ),
            ]
        )
    return "\n".join(lines) + "\n"


def _label(value: str) -> str:
    return value.replace("\\", "\\\\").replace("\n", "\\n").replace('"', '\\"')
