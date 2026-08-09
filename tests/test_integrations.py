from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agenttrustops import (
    ActionContext,
    PolicyDecision,
    PolicyOutcome,
    SQLiteActionLedger,
    as_langgraph_node,
    trusted_action,
)


class AllowPolicy:
    def evaluate(self, action_name, arguments, context):
        return PolicyDecision(PolicyOutcome.ALLOW, "allowed", "adapter-v1")


class LangGraphAdapterTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.ledger = SQLiteActionLedger(Path(self.temporary.name) / "ledger.db")

    def tearDown(self) -> None:
        self.ledger.close()
        self.temporary.cleanup()

    def test_sync_node_returns_a_partial_state_and_suppresses_duplicate_execution(self):
        calls = 0

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="medium",
            idempotency_key=lambda arguments, context: "unused-by-adapter",
        )
        def send_message(message: str):
            nonlocal calls
            calls += 1
            return {"sent": message}

        node = as_langgraph_node(
            send_message,
            context=lambda state: ActionContext(actor_id="graph-agent"),
            idempotency_key=lambda state: state["request_id"],
        )
        state = {
            "request_id": "graph-request-0001",
            "arguments": {"message": "hello"},
        }

        first = node(state)
        second = node(state)

        self.assertEqual(first, second)
        self.assertEqual(first["agenttrustops"]["status"], "completed")
        self.assertNotIn("idempotency_key", first["agenttrustops"])
        self.assertEqual(calls, 1)

    def test_async_node_awaits_async_trusted_action(self):
        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="medium",
            idempotency_key=lambda arguments, context: "unused-by-adapter",
        )
        async def notify(channel: str):
            await asyncio.sleep(0)
            return {"channel": channel}

        node = as_langgraph_node(
            notify,
            context=lambda state: ActionContext(actor_id="graph-agent"),
            arguments=lambda state: {"channel": state["channel"]},
            idempotency_key=lambda state: state["request_id"],
            result_key="governed_action",
        )
        result = asyncio.run(
            node({"request_id": "graph-request-0002", "channel": "ops"})
        )

        self.assertEqual(result["governed_action"]["status"], "completed")
        self.assertEqual(result["governed_action"]["value"]["channel"], "ops")


if __name__ == "__main__":
    unittest.main()
