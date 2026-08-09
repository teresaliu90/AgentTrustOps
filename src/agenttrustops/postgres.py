"""Optional PostgreSQL ledger for multi-process production deployments."""

from __future__ import annotations

from typing import Any, Literal, Self

from .ledger import SQLiteActionLedger


class PostgresActionLedger(SQLiteActionLedger):
    """PostgreSQL implementation of the v2 action-ledger contract.

    The domain transitions are inherited from the heavily tested reference
    ledger. A small DB-API adapter translates parameter markers and conflict
    syntax, while PostgreSQL row locks serialize each run's event hash chain.
    """

    backend_name = "postgresql"

    def __init__(self, dsn: str):
        if not dsn.strip():
            raise ValueError("PostgreSQL DSN cannot be empty")
        try:
            import psycopg
            from psycopg.rows import dict_row
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "PostgreSQL support requires: pip install 'agenttrustops[postgres]'"
            ) from error
        self.dsn = dsn
        self.path = dsn
        self._psycopg = psycopg
        self._dict_row = dict_row
        self._memory_connection = None
        self._migrate()

    def _connection(self) -> _PostgresConnectionManager:
        return _PostgresConnectionManager(self)

    def _migrate(self) -> None:
        statements = (
            """
            CREATE TABLE IF NOT EXISTS ledger_metadata (
                key TEXT PRIMARY KEY,
                value TEXT NOT NULL
            )
            """,
            """
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
                attempt BIGINT NOT NULL DEFAULT 0,
                duplicate_count BIGINT NOT NULL DEFAULT 0,
                event_count BIGINT NOT NULL DEFAULT 0,
                event_head_hash TEXT,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                UNIQUE (tenant_id, action_name, idempotency_key)
            )
            """,
            """
            CREATE TABLE IF NOT EXISTS action_events (
                sequence BIGSERIAL PRIMARY KEY,
                event_id TEXT NOT NULL UNIQUE,
                run_id TEXT NOT NULL REFERENCES action_runs(run_id),
                event_type TEXT NOT NULL,
                payload_json TEXT NOT NULL,
                previous_hash TEXT,
                event_hash TEXT,
                created_at TEXT NOT NULL
            )
            """,
            """
            ALTER TABLE action_runs
            ADD COLUMN IF NOT EXISTS duplicate_count BIGINT NOT NULL DEFAULT 0
            """,
            """
            ALTER TABLE action_runs
            ADD COLUMN IF NOT EXISTS metadata_json TEXT NOT NULL DEFAULT '{}'
            """,
            """
            ALTER TABLE action_runs
            ADD COLUMN IF NOT EXISTS event_count BIGINT NOT NULL DEFAULT 0
            """,
            """
            ALTER TABLE action_runs
            ADD COLUMN IF NOT EXISTS event_head_hash TEXT
            """,
            """
            CREATE TABLE IF NOT EXISTS approvals (
                run_id TEXT PRIMARY KEY REFERENCES action_runs(run_id),
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
                decided_at TEXT
            )
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_events_run_sequence
            ON action_events(run_id, sequence)
            """,
            """
            CREATE INDEX IF NOT EXISTS idx_runs_status_lease
            ON action_runs(status, lease_expires_at)
            """,
            """
            UPDATE action_runs SET
                event_count = (
                    SELECT COUNT(*) FROM action_events
                    WHERE action_events.run_id = action_runs.run_id
                ),
                event_head_hash = (
                    SELECT event_hash FROM action_events
                    WHERE action_events.run_id = action_runs.run_id
                    ORDER BY sequence DESC LIMIT 1
                )
            WHERE event_count = 0 AND EXISTS (
                SELECT 1 FROM action_events
                WHERE action_events.run_id = action_runs.run_id
            )
            """,
            """
            INSERT INTO ledger_metadata(key, value) VALUES ('schema_version', '2')
            ON CONFLICT (key) DO UPDATE SET value = EXCLUDED.value
            """,
        )
        with self._connection() as connection, connection:
            for statement in statements:
                connection.execute(statement)

    def _lock_run_tx(self, connection: Any, run_id: str) -> None:
        connection.execute(
            "SELECT run_id FROM action_runs WHERE run_id = ? FOR UPDATE",
            (run_id,),
        ).fetchone()

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
        """Connections are short-lived and returned after every transaction."""


class _PostgresConnectionManager:
    def __init__(self, ledger: PostgresActionLedger):
        self.ledger = ledger
        self.raw: Any = None
        self.connection: _PostgresConnection | None = None

    def __enter__(self) -> _PostgresConnection:
        self.raw = self.ledger._psycopg.connect(
            self.ledger.dsn,
            row_factory=self.ledger._dict_row,
        )
        self.connection = _PostgresConnection(self.raw)
        return self.connection

    def __exit__(self, *args: object) -> Literal[False]:
        if self.raw is not None:
            self.raw.close()
        return False


class _PostgresConnection:
    def __init__(self, raw: Any):
        self.raw = raw

    def __enter__(self) -> Self:
        return self

    def __exit__(
        self,
        error_type: object,
        error: object,
        traceback: object,
    ) -> Literal[False]:
        if error_type is None:
            self.raw.commit()
        else:
            self.raw.rollback()
        return False

    def execute(self, sql: str, values: Any = ()) -> Any:
        normalized = sql.strip()
        if normalized == "BEGIN IMMEDIATE":
            return _NoopCursor()
        if normalized.startswith("INSERT OR IGNORE INTO"):
            normalized = normalized.replace("INSERT OR IGNORE INTO", "INSERT INTO", 1)
            normalized += " ON CONFLICT DO NOTHING"
        translated = normalized.replace("?", "%s")
        return self.raw.execute(translated, values)


class _NoopCursor:
    rowcount = 0

    @staticmethod
    def fetchone() -> None:
        return None

    @staticmethod
    def fetchall() -> list[Any]:
        return []
