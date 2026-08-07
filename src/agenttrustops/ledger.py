"""SQLite append-only action ledger used by the reference SDK."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

from .models import ActionStatus


def _now() -> str:
    return datetime.now(UTC).isoformat()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SQLiteActionLedger:
    """Reference action ledger with an immutable events table.

    The API intentionally exposes event insertion and reads only. SQLite is
    useful for local verification, but it is not an immutable production audit
    system and does not provide cryptographic tamper evidence.
    """

    def __init__(self, path: str | Path):
        self.path = str(path)
        self._migrate()

    def _connect(self) -> sqlite3.Connection:
        connection = sqlite3.connect(self.path, timeout=10)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = ON")
        connection.execute("PRAGMA busy_timeout = 10000")
        connection.execute("PRAGMA journal_mode = WAL")
        return connection

    def _migrate(self) -> None:
        with closing(self._connect()) as connection, connection:
            connection.executescript(
                """
                CREATE TABLE IF NOT EXISTS action_runs (
                    run_id TEXT PRIMARY KEY,
                    tenant_id TEXT NOT NULL,
                    actor_id TEXT NOT NULL,
                    action_name TEXT NOT NULL,
                    risk TEXT NOT NULL,
                    idempotency_key TEXT NOT NULL,
                    status TEXT NOT NULL,
                    arguments_json TEXT NOT NULL,
                    roles_json TEXT NOT NULL,
                    evidence_json TEXT NOT NULL,
                    policy_version TEXT,
                    reason TEXT,
                    result_json TEXT,
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
                    created_at TEXT NOT NULL,
                    FOREIGN KEY (run_id) REFERENCES action_runs(run_id)
                );

                CREATE TABLE IF NOT EXISTS approvals (
                    run_id TEXT PRIMARY KEY,
                    status TEXT NOT NULL,
                    approver_id TEXT,
                    note TEXT,
                    requested_at TEXT NOT NULL,
                    decided_at TEXT,
                    FOREIGN KEY (run_id) REFERENCES action_runs(run_id)
                );

                CREATE INDEX IF NOT EXISTS idx_events_run_sequence
                ON action_events(run_id, sequence);
                """
            )

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
        arguments: dict[str, Any],
    ) -> tuple[dict[str, Any], bool]:
        timestamp = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                INSERT OR IGNORE INTO action_runs (
                    run_id, tenant_id, actor_id, action_name, risk,
                    idempotency_key, status, arguments_json, roles_json,
                    evidence_json, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    run_id,
                    tenant_id,
                    actor_id,
                    action_name,
                    risk,
                    idempotency_key,
                    ActionStatus.CREATED.value,
                    _json(arguments),
                    _json(roles),
                    _json(evidence),
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
        return self._decode_run(row), created

    def append_event(
        self,
        run_id: str,
        event_type: str,
        payload: dict[str, Any] | None = None,
    ) -> None:
        from uuid import uuid4

        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT INTO action_events (
                    event_id, run_id, event_type, payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?)
                """,
                (uuid4().hex, run_id, event_type, _json(payload or {}), _now()),
            )

    def update_run(
        self,
        run_id: str,
        status: ActionStatus,
        *,
        policy_version: str | None = None,
        reason: str | None = None,
        result: Any = None,
    ) -> None:
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                UPDATE action_runs
                SET status = ?,
                    policy_version = COALESCE(?, policy_version),
                    reason = ?,
                    result_json = ?,
                    updated_at = ?
                WHERE run_id = ?
                """,
                (
                    status.value,
                    policy_version,
                    reason,
                    None if result is None else _json(result),
                    _now(),
                    run_id,
                ),
            )

    def claim_execution(self, run_id: str) -> bool:
        """Atomically allow one caller to cross into the side-effect window."""

        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE action_runs SET status = ?, updated_at = ?
                WHERE run_id = ? AND status IN (?, ?)
                """,
                (
                    ActionStatus.EXECUTING.value,
                    _now(),
                    run_id,
                    ActionStatus.CREATED.value,
                    ActionStatus.APPROVED.value,
                ),
            )
            return cursor.rowcount == 1

    def request_approval(self, run_id: str) -> None:
        timestamp = _now()
        with closing(self._connect()) as connection, connection:
            connection.execute(
                """
                INSERT OR REPLACE INTO approvals (
                    run_id, status, requested_at
                ) VALUES (?, ?, ?)
                """,
                (run_id, ActionStatus.PENDING_APPROVAL.value, timestamp),
            )

    def decide_approval(
        self,
        run_id: str,
        *,
        approved: bool,
        approver_id: str,
        note: str,
    ) -> bool:
        next_status = ActionStatus.APPROVED if approved else ActionStatus.REJECTED
        with closing(self._connect()) as connection, connection:
            connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE approvals
                SET status = ?, approver_id = ?, note = ?, decided_at = ?
                WHERE run_id = ? AND status = ?
                """,
                (
                    next_status.value,
                    approver_id,
                    note,
                    _now(),
                    run_id,
                    ActionStatus.PENDING_APPROVAL.value,
                ),
            )
            if cursor.rowcount == 1:
                connection.execute(
                    """
                    UPDATE action_runs SET status = ?, reason = ?, updated_at = ?
                    WHERE run_id = ? AND status = ?
                    """,
                    (
                        next_status.value,
                        note,
                        _now(),
                        run_id,
                        ActionStatus.PENDING_APPROVAL.value,
                    ),
                )
                return True
            return False

    def get_run(self, run_id: str) -> dict[str, Any] | None:
        with closing(self._connect()) as connection, connection:
            row = connection.execute(
                "SELECT * FROM action_runs WHERE run_id = ?", (run_id,)
            ).fetchone()
        return None if row is None else self._decode_run(row)

    def events(self, run_id: str) -> list[dict[str, Any]]:
        with closing(self._connect()) as connection, connection:
            rows = connection.execute(
                """
                SELECT sequence, event_id, event_type, payload_json, created_at
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
                "created_at": row["created_at"],
            }
            for row in rows
        ]

    def audit_trail(self, run_id: str) -> dict[str, Any] | None:
        run = self.get_run(run_id)
        if run is None:
            return None
        return {
            "run": run,
            "events": self.events(run_id),
            "integrity": {
                "chain_verified": False,
                "mode": "sqlite_reference_ledger",
            },
        }

    @staticmethod
    def _decode_run(row: sqlite3.Row) -> dict[str, Any]:
        return {
            "run_id": row["run_id"],
            "tenant_id": row["tenant_id"],
            "actor_id": row["actor_id"],
            "action_name": row["action_name"],
            "risk": row["risk"],
            "idempotency_key": row["idempotency_key"],
            "status": row["status"],
            "arguments": json.loads(row["arguments_json"]),
            "roles": tuple(json.loads(row["roles_json"])),
            "evidence": tuple(json.loads(row["evidence_json"])),
            "policy_version": row["policy_version"],
            "reason": row["reason"],
            "result": None
            if row["result_json"] is None
            else json.loads(row["result_json"]),
            "created_at": row["created_at"],
            "updated_at": row["updated_at"],
        }
