from __future__ import annotations

import json
import sqlite3
import tempfile
import unittest
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from agenttrustops import SQLiteActionLedger


class SQLiteMigrationTests(unittest.TestCase):
    def test_v1_ledger_is_upgraded_without_losing_runs_approvals_or_events(
        self,
    ) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "v1.db"
            now = datetime.now(UTC).isoformat()
            with closing(sqlite3.connect(path)) as connection, connection:
                connection.executescript(
                    """
                    CREATE TABLE action_runs (
                        run_id TEXT PRIMARY KEY, tenant_id TEXT NOT NULL,
                        actor_id TEXT NOT NULL, action_name TEXT NOT NULL,
                        risk TEXT NOT NULL, idempotency_key TEXT NOT NULL,
                        status TEXT NOT NULL, arguments_json TEXT NOT NULL,
                        roles_json TEXT NOT NULL, evidence_json TEXT NOT NULL,
                        policy_version TEXT, reason TEXT, result_json TEXT,
                        created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                        UNIQUE (tenant_id, action_name, idempotency_key)
                    );
                    CREATE TABLE action_events (
                        sequence INTEGER PRIMARY KEY AUTOINCREMENT,
                        event_id TEXT NOT NULL UNIQUE, run_id TEXT NOT NULL,
                        event_type TEXT NOT NULL, payload_json TEXT NOT NULL,
                        created_at TEXT NOT NULL,
                        FOREIGN KEY (run_id) REFERENCES action_runs(run_id)
                    );
                    CREATE TABLE approvals (
                        run_id TEXT PRIMARY KEY, status TEXT NOT NULL,
                        approver_id TEXT, note TEXT, requested_at TEXT NOT NULL,
                        decided_at TEXT,
                        FOREIGN KEY (run_id) REFERENCES action_runs(run_id)
                    );
                    """
                )
                connection.execute(
                    """
                    INSERT INTO action_runs VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                    )
                    """,
                    (
                        "legacy-run",
                        "default",
                        "legacy-agent",
                        "legacy-action",
                        "high",
                        "legacy-key",
                        "pending_approval",
                        json.dumps({"value": 1}),
                        json.dumps(["operator"]),
                        json.dumps(["RESOURCE:R-1"]),
                        "legacy-policy-v1",
                        "approval needed",
                        None,
                        now,
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO action_events VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        1,
                        "legacy-event",
                        "legacy-run",
                        "run.created",
                        "{}",
                        now,
                    ),
                )
                connection.execute(
                    "INSERT INTO approvals VALUES (?, ?, ?, ?, ?, ?)",
                    (
                        "legacy-run",
                        "pending_approval",
                        None,
                        None,
                        now,
                        None,
                    ),
                )

            ledger = SQLiteActionLedger(path)
            run = ledger.get_run("legacy-run")
            trail = ledger.audit_trail("legacy-run")

            self.assertEqual(ledger.schema_info()["schema_version"], 2)
            self.assertIsNotNone(run["request_fingerprint"])
            self.assertEqual(run["policy_version"], "legacy-policy-v1")
            self.assertTrue(trail["integrity"]["chain_verified"])
            self.assertEqual(len(trail["events"]), 1)


if __name__ == "__main__":
    unittest.main()
