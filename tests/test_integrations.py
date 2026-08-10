from __future__ import annotations

import asyncio
import json
import sys
import tempfile
import types
import unittest
from pathlib import Path
from unittest.mock import patch

from agenttrustops import (
    ActionContext,
    PolicyDecision,
    PolicyOutcome,
    SQLiteActionLedger,
    as_langgraph_node,
    as_mcp_tool_handler,
    as_openai_agents_tool,
    register_fastmcp_action,
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

    def test_mcp_handler_uses_server_context_and_suppresses_duplicate_execution(self):
        calls = 0

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="high",
            idempotency_key=lambda arguments, context: "unused-by-adapter",
        )
        def create_ticket(title: str):
            nonlocal calls
            calls += 1
            return {"title": title}

        handler = as_mcp_tool_handler(
            create_ticket,
            context=lambda: ActionContext(
                actor_id="mcp-service",
                tenant_id="verified-tenant",
                roles=("ticket_writer",),
            ),
            idempotency_key=lambda arguments: "mcp-request-0001",
        )
        first = asyncio.run(handler({"title": "Investigate"}))
        second = asyncio.run(handler({"title": "Investigate"}))

        self.assertEqual(first, second)
        self.assertEqual(first["status"], "completed")
        self.assertNotIn("idempotency_key", first)
        self.assertEqual(calls, 1)

    def test_fastmcp_registration_matches_installed_sdk_contract(self):
        try:
            from mcp.server.fastmcp import FastMCP
        except ModuleNotFoundError:
            self.skipTest("mcp optional dependency is not installed")

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="medium",
            idempotency_key=lambda arguments, context: "unused-by-adapter",
        )
        def update_record(record_id: str):
            return {"record_id": record_id}

        server = FastMCP("agenttrustops-contract")
        register_fastmcp_action(
            server,
            update_record,
            context=lambda: ActionContext(actor_id="verified-mcp-client"),
            idempotency_key=lambda arguments: "mcp-contract-0001",
        )
        tools = asyncio.run(server.list_tools())
        registered = next(tool for tool in tools if tool.name == "update_record")
        self.assertIn("arguments", registered.inputSchema["properties"])

    def test_openai_agents_tool_uses_runtime_context_not_model_authority(self):
        calls = 0

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="high",
            idempotency_key=lambda arguments, context: "unused-by-adapter",
        )
        def provision_environment(name: str):
            nonlocal calls
            calls += 1
            return {"name": name}

        class FakeFunctionTool:
            def __init__(self, **kwargs):
                self.__dict__.update(kwargs)

        fake_agents = types.ModuleType("agents")
        fake_agents.FunctionTool = FakeFunctionTool
        runtime_context = object()
        with patch.dict(sys.modules, {"agents": fake_agents}):
            tool = as_openai_agents_tool(
                provision_environment,
                params_json_schema={
                    "type": "object",
                    "properties": {"name": {"type": "string"}},
                    "required": ["name"],
                    "additionalProperties": False,
                },
                context=lambda supplied, arguments: ActionContext(
                    actor_id="verified-openai-agent",
                    tenant_id="runtime-tenant",
                ),
                idempotency_key=lambda supplied, arguments: "agents-call-0001",
            )

        first = json.loads(
            asyncio.run(tool.on_invoke_tool(runtime_context, '{"name":"sandbox"}'))
        )
        second = json.loads(
            asyncio.run(tool.on_invoke_tool(runtime_context, '{"name":"sandbox"}'))
        )
        self.assertEqual(first, second)
        self.assertNotIn("idempotency_key", first)
        self.assertEqual(calls, 1)

    def test_openai_agents_tool_matches_installed_sdk_contract(self):
        try:
            from agents import FunctionTool
        except ModuleNotFoundError:
            self.skipTest("openai-agents optional dependency is not installed")

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="medium",
            idempotency_key=lambda arguments, context: "unused-by-adapter",
        )
        def schedule_job(name: str):
            return {"name": name}

        tool = as_openai_agents_tool(
            schedule_job,
            params_json_schema={
                "type": "object",
                "properties": {"name": {"type": "string"}},
                "required": ["name"],
                "additionalProperties": False,
            },
            context=lambda supplied, arguments: ActionContext(actor_id="agent"),
            idempotency_key=lambda supplied, arguments: "agents-contract-0001",
        )
        self.assertIsInstance(tool, FunctionTool)


if __name__ == "__main__":
    unittest.main()
