"""Transactional SQLite reference ledger for governed agent actions."""

from __future__ import annotations

import hashlib
import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any, Literal
from uuid import uuid4

from .errors import ApprovalDenied, IdempotencyConflict, InvalidTransition
from .models import ActionStatus, PolicyDecision, PolicyOutcome, VerifiedPrincipal


def _now() -> datetime:
    return datetime.now(UTC)


def _timestamp(value: datetime | None = None) -> str:
    return (value or _now()).isoformat()


def _json(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    )


def _digest(value: Any) -> str:
    return "sha256:" + hashlib.sha256(_json(value).encode("utf-8")).hexdigest()


def request_fingerprint(
    *,
    tenant_id: str,
    actor_id: str,
    roles: tuple[str, ...],
    evidence: tuple[str, ...],
    action_name: str,
    risk: str,
    arguments: dict[str, Any],
    metadata: dict[str, Any] | None = None,
) -> str:
    """Hash the complete governed request without storing another plaintext copy."""

    return _digest(
        {
            "schema": "agenttrustops-request-v1",
            "tenant_id": tenant_id,
            "actor_id": actor_id,
            "roles": sorted(roles),
            "evidence": sorted(evidence),
            "action_name": action_name,
            "risk": risk,
            "arguments": arguments,
            "metadata": metadata or {},
        }
    )


class SQLiteActionLedger:
    """SQLite reference ledger with atomic state/event transitions.

    New ledgers use a SHA-256 event chain and execution leases. The chain is
    tamper-evident, not immutable: an administrator who can rewrite the entire
    SQLite file can also recompute it. Production deployments should export
    events to an independently controlled append-only system.
    """

    schema_version = 2
    backend_name = "sqlite"

    def __init__(self, path: str | Path):
        self.path = str(path)
        if self.path != ":memory:":
            Path(self.path).parent.mkdir(parents=True, exist_ok=True)
        self._memory_connection: sqlite3.Connection | None = None
        if self.path == ":memory:":
            self._memory_connection = self._new_connection(self.path)
        self._migrate()

    @staticmethod
    def _new_connection(path: str) -> sqlite3.Connection:
        connection = sqlite3.connect(path, timeout=10, check_same_thread=False)
        try:
            connection.row_factory = sqlite3.Row
            for pragma in (
                "PRAGMA foreign_keys = ON",
                "PRAGMA busy_timeout = 10000",
                "PRAGMA journal_mode = WAL",
            ):
                connection.execute(pragma).close()
            return connection
        except BaseException:
            connection.close()
            raise

    def _connect(self) -> sqlite3.Connection:
        return self._memory_connection or self._new_connection(self.path)

    def _connection(self):
        connection = self._connect()
        if self._memory_connection is not None:
            return _BorrowedConnection(connection)
        return closing(connection)

    @staticmethod
    def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
        return {
            str(row["name"])
            for row in connection.execute(f"PRAGMA table_info({table})")
        }

    @staticmethod
    def _add_column(
        connection: sqlite3.Connection,
        table: str,
        definition: str,
    ) -> None:
        name = definition.split()[0]
        if name not in SQLiteActionLedger._columns(connection, table):
            connection.execute(f"ALTER TABLE {table} ADD COLUMN {definition}")

    def _migrate(self) -> None:
        with self._connection() as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS ledger_metadata (
                    key TEXT PRIMARY KEY,
                    value TEXT NOT NULL
                );

                CREATE TABLE IF NOT EXISTS action_runs (
                    run_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action_name TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    status TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    roles_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    metadata_json TEXT NOT NULL DEFAULT '{}',
                    policy_version TEXT,
                    policy_digest TEXT,
                    reason TEXT,
                    result_json TEXT,
                    execution_owner TEXT,
                    lease_expires_at TEXT,
                    attempt INTEGER NOT NULL DEFAULT 0,
                    duplicate_count INTEGER NOT NULL DEFAULT 0,
                    event_count INTEGER NOT NULL DEFAULT 0,
                    event_head_hash TEXT,
                    created_at TEXT NOT NULL,
                    updated_at TEXT NOT NULL,
                    UNIQUE (tenant_id, action_name, idempotency_key)
                );

                CREATE TABLE IF NOT EXISTS action_events (
                    sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                    event_id TEXT NOT NULL UNIQUE,
                    run_id TEXT NOT NULL,
                    event_type TEXT NOT NULL,
                    payload_json TEXT NOT NULL,
                    previous_hash TEXT,
                    event_hash TEXT,
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES action_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    request_fingerprint TEXT NOT NULL,
                    policy_version TEXT NOT NULL,
                    policy_digest TEXT,
                    requested_actor_id TEXT NOT NULL,
                    approver_id TEXT,
                    approver_auth_source TEXT,
                    note TEXT,
                    requested_at TEXT NOT NULL,
                    expires_at TEXT NOT NULL,
                    decided_at TEXT,
                    FOREIGN KEY (run_id) REFERENCES action_runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_events_run_sequence
                ON action_events(run_id, sequence);
                """
            )
            # Migrate v0.1 files without discarding their local evidence.
            self._add_column(connection, "action_runs", "request_fingerprint TEXT")
            self._add_column(connection, "action_runs", "policy_digest TEXT")
            self._add_column(
                connection,
                "action_runs",
                "metadata_json TEXT NOT NULL DEFAULT '{}'",
            )
            self._add_column(connection, "action_runs", "execution_owner TEXT")
            self._add_column(connection, "action_runs", "lease_expires_at TEXT")
            self._add_column(
                connection, "action_runs", "attempt INTEGER NOT NULL DEFAULT 0"
            )
            self._add_column(
                connection,
                "action_runs",
                "duplicate_count INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column(
                connection,
                "action_runs",
                "event_count INTEGER NOT NULL DEFAULT 0",
            )
            self._add_column(connection, "action_runs", "event_head_hash TEXT")
            self._add_column(connection, "action_events", "previous_hash TEXT")
            self._add_column(connection, "action_events", "event_hash TEXT")
            self._add_column(connection, "approvals", "request_fingerprint TEXT")
            self._add_column(connection, "approvals", "policy_version TEXT")
            self._add_column(connection, "approvals", "policy_digest TEXT")
            self._add_column(connection, "approvals", "requested_actor_id TEXT")
            self._add_column(connection, "approvals", "approver_auth_source TEXT")
            self._add_column(connection, "approvals", "expires_at TEXT")
            connection.execute(
                """
                CREATE INDEX IF NOT EXISTS idx_runs_status_lease
                ON action_runs(status, lease_expires_at)
                """
            )
            self._backfill_v1(connection)
            connection.execute(
                "INSERT OR REPLACE INTO ledger_metadata(key, value) VALUES ('schema_version', ?)",
                (str(self.schema_version),),
            )

    def _backfill_v1(self, connection: sqlite3.Connection) -> None:
        runs = connection.execute(
            "SELECT * FROM action_runs WHERE request_fingerprint IS NULL OR request_fingerprint = ''"
        ).fetchall()
        for row in runs:
            fingerprint = request_fingerprint(
                tenant_id=str(row["tenant_id"]),
                actor_id=str(row["actor_id"]),
                roles=tuple(json.loads(row["roles_json"])),
                evidence=tuple(json.loads(row["evidence_json"])),
                action_name=str(row["action_name"]),
                risk=str(row["risk"]),
                arguments=json.loads(row["arguments_json"]),
                metadata=json.loads(row["metadata_json"]),
            )
            connection.execute(
                "UPDATE action_runs SET request_fingerprint = ? WHERE run_id = ?",
                (fingerprint, row["run_id"]),
            )
        approvals = connection.execute(
            """
            SELECT approvals.run_id, action_runs.request_fingerprint,
                   action_runs.policy_version, action_runs.policy_digest,
                   action_runs.actor_id, approvals.requested_at
            FROM approvals JOIN action_runs USING (run_id)
            WHERE approvals.request_fingerprint IS NULL
               OR approvals.request_fingerprint = ''
            """
        ).fetchall()
        for row in approvals:
            requested_at = datetime.fromisoformat(str(row["requested_at"]))
            expires_at = requested_at + timedelta(hours=1)
            connection.execute(
                """
                UPDATE approvals SET request_fingerprint = ?, policy_version = ?,
                    policy_digest = ?, requested_actor_id = ?, expires_at = ?
                WHERE run_id = ?
                """,
                (
                    row["request_fingerprint"],
                    row["policy_version"] or "legacy-unresolved",
                    row["policy_digest"],
                    row["actor_id"],
                    expires_at.isoformat(),
                    row["run_id"],
                ),
            )
        for run in connection.execute(
            "SELECT run_id, event_count, event_head_hash FROM action_runs"
        ).fetchall():
            previous_hash: str | None = None
            events = connection.execute(
                "SELECT * FROM action_events WHERE run_id = ? ORDER BY sequence",
                (run["run_id"],),
            ).fetchall()
            needs_hash_backfill = any(event["event_hash"] is None for event in events)
            if needs_hash_backfill:
                for event in events:
                    event_hash = self._event_hash(
                        run_id=str(event["run_id"]),
                        event_type=str(event["event_type"]),
                        payload_json=str(event["payload_json"]),
                        previous_hash=previous_hash,
                        created_at=str(event["created_at"]),
                    )
                    connection.execute(
                        """
                        UPDATE action_events SET previous_hash = ?, event_hash = ?
                        WHERE sequence = ?
                        """,
                        (previous_hash, event_hash, event["sequence"]),
                    )
                    previous_hash = event_hash
            elif events:
                previous_hash = str(events[-1]["event_hash"])
            if needs_hash_backfill or (int(run["event_count"]) == 0 and events):
                connection.execute(
                    """
                    UPDATE action_runs SET event_count = ?, event_head_hash = ?
                    WHERE run_id = ?
                    """,
                    (len(events), previous_hash, run["run_id"]),
                )

    @staticmethod
    def _event_hash(
        *,
        run_id: str,
        event_type: str,
        payload_json: str,
        previous_hash: str | None,
        created_at: str,
    ) -> str:
        return _digest(
            {
                "run_id": run_id,
                "event_type": event_type,
                "payload": json.loads(payload_json),
                "previous_hash": previous_hash,
                "created_at": created_at,
            }
        )

    def _append_event_tx(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
        *,
        created_at: str | None = None,
    ) -> None:
        self._lock_run_tx(connection, run_id)
        timestamp = created_at or _timestamp()
        payload_json = _json(payload or {})
        row = connection.execute(
            """
            SELECT event_hash FROM action_events
            WHERE run_id = ? ORDER BY sequence DESC LIMIT 1
            """,
            (run_id,),
        ).fetchone()
        previous_hash = None if row is None else str(row["event_hash"])
        event_hash = self._event_hash(
            run_id=run_id,
            event_type=event_type,
            payload_json=payload_json,
            previous_hash=previous_hash,
            created_at=timestamp,
        )
        connection.execute(
            """
            INSERT INTO action_events (
                event_id, run_id, event_type, payload_json,
                previous_hash, event_hash, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            """,
            (
                uuid4().hex,
                run_id,
                event_type,
                payload_json,
                previous_hash,
                event_hash,
                timestamp,
            ),
        )
        cursor = connection.execute(
            """
            UPDATE action_runs
            SET event_count = event_count + 1, event_head_hash = ?
            WHERE run_id = ?
            """,
            (event_hash, run_id),
        )
        if cursor.rowcount != 1:
            raise KeyError("run not found while anchoring event chain")

    def _lock_run_tx(self, connection: sqlite3.Connection, run_id: str) -> None:
        """Hook for backends that need an explicit per-run event-chain lock."""

    def create_or_get_run(
        self,
        *,
        run_id: str,
        tenant_id: str,
        actor_id: str,
        roles: tuple[str, ...],
        evidence: tuple[str, ...],
        action_name: str,
        risk: str,
        idempotency_key: str,
        request_fingerprint: str,
        arguments: dict[str, Any],
        metadata: dict[str, Any] | None = None,
    ) -> tuple[dict[str, Any], bool]:
        timestamp = _timestamp()
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO action_runs (
                    run_id, tenant_id, actor_id, action_name, risk,
                    idempotency_key, request_fingerprint, status, arguments_json,
                    roles_json, evidence_json, metadata_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    tenant_id,
                    actor_id,
                    action_name,
                    risk,
                    idempotency_key,
                    request_fingerprint,
                    ActionStatus.CREATED.value,
                    _json(arguments),
                    _json(roles),
                    _json(evidence),
                    _json(metadata or {}),
                    timestamp,
                    timestamp,
                ),
            )
            created = cursor.rowcount == 1
            row = connection.execute(
                """
                SELECT * FROM action_runs
                WHERE tenant_id = ? AND action_name = ? AND idempotency_key = ?
                """,
                (tenant_id, action_name, idempotency_key),
            ).fetchone()
            if row is None:
                raise RuntimeError("action run could not be created or loaded")
            if str(row["request_fingerprint"]) != request_fingerprint:
                raise IdempotencyConflict(
                    "idempotency key was already used for a different governed request"
                )
            if created:
                self._append_event_tx(
                    connection,
                    run_id,
                    "run.created",
                    {
                        "action_name": action_name,
                        "risk": risk,
                        "request_fingerprint": request_fingerprint,
                    },
                    created_at=timestamp,
                )
        return self._decode_run(row), created

    def record_duplicate(self, run_id: str) -> None:
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE action_runs SET duplicate_count = duplicate_count + 1
                WHERE run_id = ?
                """,
                (run_id,),
            )
            if cursor.rowcount != 1:
                raise KeyError("run not found")

    def record_policy_decision(
        self,
        run_id: str,
        decision: PolicyDecision,
        *,
        approval_ttl_seconds: int,
    ) -> None:
        if not 1 <= approval_ttl_seconds <= 604800:
            raise ValueError("approval_ttl_seconds must be between 1 and 604800")
        policy_digest = decision.policy_digest or _digest(
            {"policy_version": decision.policy_version}
        )
        now = _now()
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT * FROM action_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise KeyError("run not found")
            if run["status"] != ActionStatus.CREATED.value:
                raise InvalidTransition("policy can only decide a newly created run")
            if decision.outcome is PolicyOutcome.DENY:
                next_status = ActionStatus.DENIED
            elif decision.outcome is PolicyOutcome.APPROVAL_REQUIRED:
                next_status = ActionStatus.PENDING_APPROVAL
            else:
                next_status = ActionStatus.CREATED
            connection.execute(
                """
                UPDATE action_runs SET status = ?, policy_version = ?, policy_digest = ?,
                    reason = ?, updated_at = ? WHERE run_id = ? AND status = ?
                """,
                (
                    next_status.value,
                    decision.policy_version,
                    policy_digest,
                    decision.reason,
                    now.isoformat(),
                    run_id,
                    ActionStatus.CREATED.value,
                ),
            )
            self._append_event_tx(
                connection,
                run_id,
                "policy.checked",
                {
                    "outcome": decision.outcome.value,
                    "policy_version": decision.policy_version,
                    "policy_digest": policy_digest,
                    "reason": decision.reason,
                    "facts": decision.facts,
                },
            )
            if next_status is ActionStatus.DENIED:
                self._append_event_tx(
                    connection, run_id, "run.denied", {"reason": decision.reason}
                )
            elif next_status is ActionStatus.PENDING_APPROVAL:
                expires_at = now + timedelta(seconds=approval_ttl_seconds)
                connection.execute(
                    """
                    INSERT INTO approvals (
                        run_id, status, request_fingerprint, policy_version,
                        policy_digest, requested_actor_id, requested_at, expires_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        run_id,
                        ActionStatus.PENDING_APPROVAL.value,
                        run["request_fingerprint"],
                        decision.policy_version,
                        policy_digest,
                        run["actor_id"],
                        now.isoformat(),
                        expires_at.isoformat(),
                    ),
                )
                self._append_event_tx(
                    connection,
                    run_id,
                    "approval.requested",
                    {
                        "reason": decision.reason,
                        "policy_version": decision.policy_version,
                        "policy_digest": policy_digest,
                        "request_fingerprint": run["request_fingerprint"],
                        "expires_at": expires_at.isoformat(),
                    },
                )

    def decide_approval(
        self,
        run_id: str,
        *,
        approved: bool,
        principal: VerifiedPrincipal,
        note: str,
        required_roles: tuple[str, ...],
        allow_self_approval: bool,
    ) -> bool:
        next_status = ActionStatus.APPROVED if approved else ActionStatus.REJECTED
        now = _now()
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT action_runs.*, approvals.status AS approval_status,
                       approvals.request_fingerprint AS approved_fingerprint,
                       approvals.policy_version AS approved_policy_version,
                       approvals.policy_digest AS approved_policy_digest,
                       approvals.requested_actor_id, approvals.expires_at
                FROM action_runs JOIN approvals USING (run_id)
                WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError("run or approval not found")
            if principal.tenant_id != row["tenant_id"]:
                raise ApprovalDenied("approver belongs to a different tenant")
            if not set(required_roles).intersection(principal.roles):
                raise ApprovalDenied("approver lacks a required approval role")
            if (
                not allow_self_approval
                and principal.actor_id == row["requested_actor_id"]
            ):
                raise ApprovalDenied("self-approval is not permitted")
            if row["approval_status"] != ActionStatus.PENDING_APPROVAL.value:
                return False
            if row["status"] != ActionStatus.PENDING_APPROVAL.value:
                raise InvalidTransition("run and approval states are inconsistent")
            if datetime.fromisoformat(str(row["expires_at"])) <= now:
                connection.execute(
                    "UPDATE approvals SET status = ?, decided_at = ? WHERE run_id = ?",
                    (ActionStatus.APPROVAL_EXPIRED.value, now.isoformat(), run_id),
                )
                connection.execute(
                    "UPDATE action_runs SET status = ?, updated_at = ? WHERE run_id = ?",
                    (ActionStatus.APPROVAL_EXPIRED.value, now.isoformat(), run_id),
                )
                self._append_event_tx(
                    connection,
                    run_id,
                    "approval.expired",
                    {"expires_at": row["expires_at"]},
                )
                return False
            if (
                row["request_fingerprint"] != row["approved_fingerprint"]
                or row["policy_version"] != row["approved_policy_version"]
                or row["policy_digest"] != row["approved_policy_digest"]
            ):
                raise ApprovalDenied(
                    "approval binding no longer matches the governed run"
                )
            cursor = connection.execute(
                """
                UPDATE approvals SET status = ?, approver_id = ?,
                    approver_auth_source = ?, note = ?, decided_at = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    next_status.value,
                    principal.actor_id,
                    principal.auth_source,
                    note,
                    now.isoformat(),
                    run_id,
                    ActionStatus.PENDING_APPROVAL.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            connection.execute(
                """
                UPDATE action_runs SET status = ?, reason = ?, updated_at = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    next_status.value,
                    note,
                    now.isoformat(),
                    run_id,
                    ActionStatus.PENDING_APPROVAL.value,
                ),
            )
            self._append_event_tx(
                connection,
                run_id,
                "approval.approved" if approved else "approval.rejected",
                {
                    "approver_id": principal.actor_id,
                    "auth_source": principal.auth_source,
                    "note": note,
                    "request_fingerprint": row["request_fingerprint"],
                    "policy_version": row["policy_version"],
                    "policy_digest": row["policy_digest"],
                },
            )
            return True

    def expire_approvals(self, *, tenant_id: str | None = None) -> tuple[str, ...]:
        """Expire overdue approval requests without waiting for a decision attempt."""

        now = _now()
        expired: list[str] = []
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            query = """
                SELECT approvals.run_id, approvals.expires_at
                FROM approvals JOIN action_runs USING (run_id)
                WHERE approvals.status = ? AND action_runs.status = ?
                    AND approvals.expires_at <= ?
            """
            values: list[Any] = [
                ActionStatus.PENDING_APPROVAL.value,
                ActionStatus.PENDING_APPROVAL.value,
                now.isoformat(),
            ]
            if tenant_id is not None:
                query += " AND action_runs.tenant_id = ?"
                values.append(tenant_id)
            for row in connection.execute(query, values).fetchall():
                run_id = str(row["run_id"])
                approval = connection.execute(
                    """
                    UPDATE approvals SET status = ?, decided_at = ?
                    WHERE run_id = ? AND status = ?
                    """,
                    (
                        ActionStatus.APPROVAL_EXPIRED.value,
                        now.isoformat(),
                        run_id,
                        ActionStatus.PENDING_APPROVAL.value,
                    ),
                )
                run = connection.execute(
                    """
                    UPDATE action_runs SET status = ?, updated_at = ?
                    WHERE run_id = ? AND status = ?
                    """,
                    (
                        ActionStatus.APPROVAL_EXPIRED.value,
                        now.isoformat(),
                        run_id,
                        ActionStatus.PENDING_APPROVAL.value,
                    ),
                )
                if approval.rowcount == 1 and run.rowcount == 1:
                    self._append_event_tx(
                        connection,
                        run_id,
                        "approval.expired",
                        {"expires_at": row["expires_at"]},
                    )
                    expired.append(run_id)
                elif approval.rowcount != run.rowcount:
                    raise InvalidTransition(
                        "run and approval expiration states are inconsistent"
                    )
        return tuple(expired)

    def claim_execution(
        self,
        run_id: str,
        *,
        owner: str,
        lease_seconds: int,
    ) -> bool:
        if not owner.strip():
            raise ValueError("execution owner cannot be empty")
        if not 1 <= lease_seconds <= 86400:
            raise ValueError("lease_seconds must be between 1 and 86400")
        now = _now()
        lease_expires_at = now + timedelta(seconds=lease_seconds)
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                """
                SELECT status, lease_expires_at, policy_version
                FROM action_runs WHERE run_id = ?
                """,
                (run_id,),
            ).fetchone()
            if row is None:
                raise KeyError("run not found")
            if (
                row["status"] == ActionStatus.EXECUTING.value
                and row["lease_expires_at"]
                and datetime.fromisoformat(str(row["lease_expires_at"])) <= now
            ):
                self._mark_expired_execution_tx(connection, run_id, now)
                return False
            cursor = connection.execute(
                """
                UPDATE action_runs SET status = ?, execution_owner = ?,
                    lease_expires_at = ?, attempt = attempt + 1, updated_at = ?
                WHERE run_id = ? AND status IN (?, ?) AND policy_version IS NOT NULL
                """,
                (
                    ActionStatus.EXECUTING.value,
                    owner,
                    lease_expires_at.isoformat(),
                    now.isoformat(),
                    run_id,
                    ActionStatus.CREATED.value,
                    ActionStatus.APPROVED.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            attempt = connection.execute(
                "SELECT attempt FROM action_runs WHERE run_id = ?", (run_id,)
            ).fetchone()["attempt"]
            if row["status"] == ActionStatus.APPROVED.value:
                self._append_event_tx(connection, run_id, "run.resumed", {})
            self._append_event_tx(
                connection,
                run_id,
                "tool.execution.started",
                {
                    "owner": owner,
                    "attempt": attempt,
                    "lease_expires_at": lease_expires_at.isoformat(),
                },
            )
            return True

    def heartbeat_execution(
        self, run_id: str, *, owner: str, lease_seconds: int
    ) -> bool:
        if not owner.strip():
            raise ValueError("execution owner cannot be empty")
        if not 1 <= lease_seconds <= 86400:
            raise ValueError("lease_seconds must be between 1 and 86400")
        now = _now()
        expires_at = now + timedelta(seconds=lease_seconds)
        with self._connection() as connection, connection:
            cursor = connection.execute(
                """
                UPDATE action_runs SET lease_expires_at = ?, updated_at = ?
                WHERE run_id = ? AND status = ? AND execution_owner = ?
                    AND lease_expires_at > ?
                """,
                (
                    expires_at.isoformat(),
                    now.isoformat(),
                    run_id,
                    ActionStatus.EXECUTING.value,
                    owner,
                    now.isoformat(),
                ),
            )
            return cursor.rowcount == 1

    def complete_execution(self, run_id: str, *, owner: str, result: Any) -> None:
        self._finish_execution(
            run_id,
            owner=owner,
            status=ActionStatus.COMPLETED,
            reason=None,
            result=result,
            events=[("tool.execution.succeeded", {}), ("run.completed", {})],
        )

    def fail_execution(self, run_id: str, *, owner: str, error_type: str) -> None:
        reason = f"tool execution failed: {error_type}"
        self._finish_execution(
            run_id,
            owner=owner,
            status=ActionStatus.FAILED,
            reason=reason,
            result=None,
            events=[("tool.execution.failed", {"error_type": error_type})],
        )

    def mark_execution_unknown(
        self, run_id: str, *, owner: str, error_type: str
    ) -> None:
        reason = f"tool execution outcome uncertain: {error_type}"
        self._finish_execution(
            run_id,
            owner=owner,
            status=ActionStatus.UNKNOWN,
            reason=reason,
            result=None,
            events=[
                (
                    "tool.execution.uncertain",
                    {"error_type": error_type, "reason": reason},
                )
            ],
        )

    def _finish_execution(
        self,
        run_id: str,
        *,
        owner: str,
        status: ActionStatus,
        reason: str | None,
        result: Any,
        events: list[tuple[str, dict[str, Any]]],
    ) -> None:
        result_json = None if result is None else _json(result)
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE action_runs SET status = ?, reason = ?, result_json = ?,
                    execution_owner = NULL, lease_expires_at = NULL, updated_at = ?
                WHERE run_id = ? AND status = ? AND execution_owner = ?
                """,
                (
                    status.value,
                    reason,
                    result_json,
                    _timestamp(),
                    run_id,
                    ActionStatus.EXECUTING.value,
                    owner,
                ),
            )
            if cursor.rowcount != 1:
                raise InvalidTransition(
                    "execution lease is no longer owned by this worker"
                )
            for event_type, payload in events:
                self._append_event_tx(connection, run_id, event_type, payload)

    def _mark_expired_execution_tx(
        self,
        connection: sqlite3.Connection,
        run_id: str,
        now: datetime,
    ) -> bool:
        reason = "execution lease expired; provider outcome requires reconciliation"
        cursor = connection.execute(
            """
            UPDATE action_runs SET status = ?, reason = ?, execution_owner = NULL,
                lease_expires_at = NULL, updated_at = ? WHERE run_id = ? AND status = ?
            """,
            (
                ActionStatus.UNKNOWN.value,
                reason,
                now.isoformat(),
                run_id,
                ActionStatus.EXECUTING.value,
            ),
        )
        if cursor.rowcount != 1:
            return False
        self._append_event_tx(
            connection,
            run_id,
            "tool.execution.lease_expired",
            {"reason": reason},
        )
        return True

    def recover_expired_executions(
        self,
        *,
        tenant_id: str | None = None,
    ) -> tuple[str, ...]:
        now = _now()
        recovered: list[str] = []
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            query = """
                SELECT run_id FROM action_runs
                WHERE status = ? AND lease_expires_at IS NOT NULL AND lease_expires_at <= ?
            """
            values: list[Any] = [ActionStatus.EXECUTING.value, now.isoformat()]
            if tenant_id is not None:
                query += " AND tenant_id = ?"
                values.append(tenant_id)
            rows = connection.execute(query, values).fetchall()
            for row in rows:
                run_id = str(row["run_id"])
                if self._mark_expired_execution_tx(connection, run_id, now):
                    recovered.append(run_id)
        return tuple(recovered)

    def reconcile_run(
        self,
        run_id: str,
        status: ActionStatus,
        *,
        reason: str,
        result: Any = None,
        principal: VerifiedPrincipal,
    ) -> bool:
        if status not in (ActionStatus.COMPLETED, ActionStatus.FAILED):
            raise ValueError("reconciliation status must be completed or failed")
        result_json = None if result is None else _json(result)
        with self._connection() as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            run = connection.execute(
                "SELECT tenant_id, status FROM action_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
            if run is None:
                raise KeyError("run not found")
            if principal.tenant_id != run["tenant_id"]:
                raise ApprovalDenied(
                    "reconciliation operator belongs to a different tenant"
                )
            cursor = connection.execute(
                """
                UPDATE action_runs SET status = ?, reason = ?, result_json = ?, updated_at = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    status.value,
                    reason,
                    result_json,
                    _timestamp(),
                    run_id,
                    ActionStatus.UNKNOWN.value,
                ),
            )
            if cursor.rowcount != 1:
                return False
            self._append_event_tx(
                connection,
                run_id,
                "run.reconciled",
                {
                    "operator_id": principal.actor_id,
                    "auth_source": principal.auth_source,
                    "outcome": status.value,
                    "note": reason,
                },
            )
            return True

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT * FROM action_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return None if row is None else self._decode_run(row)

    def list_runs(
        self,
        *,
        tenant_id: str | None = None,
        status: ActionStatus | None = None,
        limit: int = 100,
    ) -> list[dict[str, Any]]:
        if not 1 <= limit <= 1000:
            raise ValueError("limit must be between 1 and 1000")
        clauses: list[str] = []
        values: list[Any] = []
        if tenant_id is not None:
            clauses.append("tenant_id = ?")
            values.append(tenant_id)
        if status is not None:
            clauses.append("status = ?")
            values.append(status.value)
        where = f"WHERE {' AND '.join(clauses)}" if clauses else ""
        values.append(limit)
        with self._connection() as connection:
            rows = connection.execute(
                f"SELECT * FROM action_runs {where} ORDER BY created_at DESC LIMIT ?",
                values,
            ).fetchall()
        return [self._decode_run(row) for row in rows]

    def events(self, run_id: str) -> list[dict[str, Any]]:
        with self._connection() as connection:
            rows = connection.execute(
                """
                SELECT sequence, event_id, event_type, payload_json,
                       previous_hash, event_hash, created_at
                FROM action_events WHERE run_id = ? ORDER BY sequence
                """,
                (run_id,),
            ).fetchall()
        return [
            {
                "sequence": row["sequence"],
                "event_id": row["event_id"],
                "event_type": row["event_type"],
                "payload": json.loads(row["payload_json"]),
                "previous_hash": row["previous_hash"],
                "event_hash": row["event_hash"],
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def verify_event_chain(self, run_id: str) -> bool:
        run = self.get_run(run_id)
        if run is None:
            return False
        previous_hash: str | None = None
        events = self.events(run_id)
        for event in events:
            expected = self._event_hash(
                run_id=run_id,
                event_type=str(event["event_type"]),
                payload_json=_json(event["payload"]),
                previous_hash=previous_hash,
                created_at=str(event["created_at"]),
            )
            if (
                event["previous_hash"] != previous_hash
                or event["event_hash"] != expected
            ):
                return False
            previous_hash = str(event["event_hash"])
        return (
            run["event_count"] == len(events)
            and run["event_head_hash"] == previous_hash
        )

    @staticmethod
    def _redacted_run(run: dict[str, Any]) -> dict[str, Any]:
        return {
            **run,
            "actor_id": _digest(run["actor_id"]),
            "idempotency_key": _digest(run["idempotency_key"]),
            "arguments": {"redacted": True, "digest": _digest(run["arguments"])},
            "roles": (),
            "evidence": {
                "redacted": True,
                "count": len(run["evidence"]),
                "digest": _digest(run["evidence"]),
            },
            "metadata": {
                "redacted": True,
                "digest": _digest(run["metadata"]),
            },
            "result": None
            if run["result"] is None
            else {"redacted": True, "digest": _digest(run["result"])},
        }

    @staticmethod
    def _redacted_events(events: list[dict[str, Any]]) -> list[dict[str, Any]]:
        sensitive_keys = {
            "note",
            "facts",
            "arguments",
            "result",
            "evidence",
            "approver_id",
            "operator_id",
            "auth_source",
            "owner",
        }
        redacted: list[dict[str, Any]] = []
        for event in events:
            payload = {
                key: (
                    {"redacted": True, "digest": _digest(value)}
                    if key in sensitive_keys
                    else value
                )
                for key, value in event["payload"].items()
            }
            redacted.append({**event, "payload": payload})
        return redacted

    def audit_trail(
        self,
        run_id: str,
        *,
        principal: VerifiedPrincipal | None = None,
    ) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        sensitive = (
            principal is not None
            and principal.tenant_id == run["tenant_id"]
            and "agenttrustops_auditor" in principal.roles
        )
        events = self.events(run_id)
        return {
            "run": run if sensitive else self._redacted_run(run),
            "events": events if sensitive else self._redacted_events(events),
            "integrity": {
                "chain_verified": self.verify_event_chain(run_id),
                "mode": f"sha256_event_chain_{self.backend_name}",
                "immutable": False,
            },
            "sensitive_fields_included": sensitive,
        }

    def status_counts(self, *, tenant_id: str | None = None) -> dict[str, int]:
        query = "SELECT status, COUNT(*) AS total FROM action_runs"
        values: tuple[Any, ...] = ()
        if tenant_id is not None:
            query += " WHERE tenant_id = ?"
            values = (tenant_id,)
        query += " GROUP BY status"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return {str(row["status"]): int(row["total"]) for row in rows}

    def event_counts(self, *, tenant_id: str | None = None) -> dict[str, int]:
        query = """
            SELECT action_events.event_type, COUNT(*) AS total
            FROM action_events JOIN action_runs USING (run_id)
        """
        values: tuple[Any, ...] = ()
        if tenant_id is not None:
            query += " WHERE action_runs.tenant_id = ?"
            values = (tenant_id,)
        query += " GROUP BY action_events.event_type"
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        return {str(row["event_type"]): int(row["total"]) for row in rows}

    def duplicate_retry_count(self, *, tenant_id: str | None = None) -> int:
        query = "SELECT COALESCE(SUM(duplicate_count), 0) AS total FROM action_runs"
        values: tuple[Any, ...] = ()
        if tenant_id is not None:
            query += " WHERE tenant_id = ?"
            values = (tenant_id,)
        with self._connection() as connection:
            row = connection.execute(query, values).fetchone()
        return 0 if row is None else int(row["total"])

    def approval_counts(self, *, tenant_id: str | None = None) -> dict[str, int]:
        query = """
            SELECT approvals.status, approvals.expires_at
            FROM approvals JOIN action_runs USING (run_id)
        """
        values: tuple[Any, ...] = ()
        if tenant_id is not None:
            query += " WHERE action_runs.tenant_id = ?"
            values = (tenant_id,)
        now = _now()
        counts: dict[str, int] = {}
        expired_pending = 0
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        for row in rows:
            status = str(row["status"])
            counts[status] = counts.get(status, 0) + 1
            if (
                status == ActionStatus.PENDING_APPROVAL.value
                and datetime.fromisoformat(str(row["expires_at"])) <= now
            ):
                expired_pending += 1
        counts["expired_pending"] = expired_pending
        return counts

    def verify_all_event_chains(
        self,
        *,
        tenant_id: str | None = None,
        limit: int = 10000,
    ) -> dict[str, Any]:
        if not 1 <= limit <= 100000:
            raise ValueError("limit must be between 1 and 100000")
        query = "SELECT run_id FROM action_runs"
        values: list[Any] = []
        if tenant_id is not None:
            query += " WHERE tenant_id = ?"
            values.append(tenant_id)
        query += " ORDER BY created_at DESC LIMIT ?"
        values.append(limit)
        with self._connection() as connection:
            rows = connection.execute(query, values).fetchall()
        invalid = [
            str(row["run_id"])
            for row in rows
            if not self.verify_event_chain(str(row["run_id"]))
        ]
        return {
            "checked": len(rows),
            "invalid": len(invalid),
            "invalid_run_ids": invalid,
            "truncated": len(rows) == limit,
        }

    def schema_info(self) -> dict[str, Any]:
        with self._connection() as connection:
            row = connection.execute(
                "SELECT value FROM ledger_metadata WHERE key = 'schema_version'"
            ).fetchone()
            connection.execute("SELECT 1").fetchone()
        return {
            "backend": self.backend_name,
            "schema_version": None if row is None else int(row["value"]),
            "writable": True,
        }

    def close(self) -> None:
        if self._memory_connection is not None:
            self._memory_connection.close()
            self._memory_connection = None

    @staticmethod
    def _decode_run(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "tenant_id": row["tenant_id"],
            "actor_id": row["actor_id"],
            "action_name": row["action_name"],
            "risk": row["risk"],
            "idempotency_key": row["idempotency_key"],
            "request_fingerprint": row["request_fingerprint"],
            "status": row["status"],
            "arguments": json.loads(row["arguments_json"]),
            "roles": tuple(json.loads(row["roles_json"])),
            "evidence": tuple(json.loads(row["evidence_json"])),
            "metadata": json.loads(row["metadata_json"]),
            "policy_version": row["policy_version"],
            "policy_digest": row["policy_digest"],
            "reason": row["reason"],
            "result": None
            if row["result_json"] is None
            else json.loads(row["result_json"]),
            "execution_owner": row["execution_owner"],
            "lease_expires_at": row["lease_expires_at"],
            "attempt": int(row["attempt"]),
            "duplicate_count": int(row["duplicate_count"]),
            "event_count": int(row["event_count"]),
            "event_head_hash": row["event_head_hash"],
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }


class _BorrowedConnection:
    """Context manager that does not close the shared in-memory connection."""

    def __init__(self, connection: sqlite3.Connection):
        self.connection = connection

    def __enter__(self) -> sqlite3.Connection:
        return self.connection

    def __exit__(self, *args: object) -> Literal[False]:
        return False
