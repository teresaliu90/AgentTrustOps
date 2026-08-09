from __future__ import annotations

import os
import unittest
from concurrent.futures import ThreadPoolExecutor

from agenttrustops import (
    ActionContext,
    PolicyDecision,
    PolicyOutcome,
    PostgresActionLedger,
    trusted_action,
)


@unittest.skipUnless(
    os.getenv("AGENTTRUSTOPS_TEST_POSTGRES_DSN"),
    "set AGENTTRUSTOPS_TEST_POSTGRES_DSN to run PostgreSQL contract tests",
)
class PostgresLedgerContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.ledger = PostgresActionLedger(
            os.environ["AGENTTRUSTOPS_TEST_POSTGRES_DSN"]
        )
        with self.ledger._connection() as connection, connection:
            connection.execute("DELETE FROM approvals")
            connection.execute("DELETE FROM action_events")
            connection.execute("DELETE FROM action_runs")

    def test_concurrent_retries_and_event_chain_match_reference_contract(self) -> None:
        calls = 0

        class Policy:
            def evaluate(self, action_name, arguments, context):
                return PolicyDecision(PolicyOutcome.ALLOW, "allowed", "postgres-v1")

        @trusted_action(
            ledger=self.ledger,
            policy=Policy(),
            risk="high",
            idempotency_key=lambda arguments, context: "fallback-key",
        )
        def commit(value: int):
            nonlocal calls
            calls += 1
            return {"value": value}

        def invoke():
            return commit.invoke_request(
                context=ActionContext(actor_id="postgres-agent"),
                arguments={"value": 42},
                idempotency_key="postgres-request-0001",
            )

        with ThreadPoolExecutor(max_workers=8) as executor:
            results = list(executor.map(lambda _: invoke(), range(16)))

        self.assertEqual(calls, 1)
        self.assertEqual(len({result.run_id for result in results}), 1)
        self.assertTrue(self.ledger.verify_event_chain(results[0].run_id))
        self.assertEqual(self.ledger.schema_info()["backend"], "postgresql")
        self.assertEqual(
            self.ledger.audit_trail(results[0].run_id)["integrity"]["mode"],
            "sha256_event_chain_postgresql",
        )


if __name__ == "__main__":
    unittest.main()
