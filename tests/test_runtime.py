from __future__ import annotations

import asyncio
import tempfile
import unittest
from pathlib import Path

from agenttrustops import (
    ActionContext,
    ActionStatus,
    IndeterminateOutcome,
    PolicyDecision,
    PolicyOutcome,
    SQLiteActionLedger,
    trusted_action,
)
from agenttrustops.refund_ops import build_refund_action, run_refund_demo

SAFE_POLICY = {
    "release": "test-safe",
    "selection_mode": "as_of_order",
    "approval_enabled": True,
    "require_evidence": True,
    "enforce_roles": True,
    "allowed_roles": ["refund_agent", "refund_admin"],
}


def context(
    order_id: str, *, roles: tuple[str, ...] = ("refund_agent",)
) -> ActionContext:
    return ActionContext(
        actor_id="test-agent",
        tenant_id="default",
        roles=roles,
        evidence=(f"ORDER:{order_id}", f"LOGISTICS:{order_id}"),
    )


class TrustedActionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        root = Path(self.temporary.name)
        self.action, self.refunds = build_refund_action(
            ledger_path=root / "ledger.db",
            refund_path=root / "refunds.db",
            policy_config=SAFE_POLICY,
        )

    def tearDown(self) -> None:
        self.temporary.cleanup()

    def test_direct_function_call_is_blocked(self) -> None:
        with self.assertRaisesRegex(TypeError, "use .invoke"):
            self.action(order_id="O-LOW", amount=200)

    def test_ten_retries_execute_exactly_one_refund(self) -> None:
        results = [
            self.action.invoke(context=context("O-LOW"), order_id="O-LOW", amount=200)
            for _ in range(10)
        ]

        self.assertEqual(results[0].status, ActionStatus.COMPLETED)
        self.assertTrue(all(result.run_id == results[0].run_id for result in results))
        self.assertTrue(all(result.duplicate for result in results[1:]))
        self.assertEqual(self.refunds.count("O-LOW"), 1)

    def test_high_risk_refund_waits_for_approval_then_resumes(self) -> None:
        pending = self.action.invoke(
            context=context("O-HIGH"), order_id="O-HIGH", amount=800
        )

        self.assertEqual(pending.status, ActionStatus.PENDING_APPROVAL)
        self.assertEqual(self.refunds.count("O-HIGH"), 0)
        approved = self.action.approve(
            pending.run_id,
            approver_id="finance-manager",
            note="Synthetic scenario approved for testing",
        )
        self.assertEqual(approved.status, ActionStatus.APPROVED)
        completed = self.action.resume(pending.run_id)

        self.assertEqual(completed.status, ActionStatus.COMPLETED)
        self.assertEqual(self.refunds.count("O-HIGH"), 1)

    def test_missing_evidence_is_denied_without_side_effect(self) -> None:
        missing = ActionContext(
            actor_id="test-agent",
            roles=("refund_agent",),
            evidence=("ORDER:O-LOW",),
        )

        result = self.action.invoke(context=missing, order_id="O-LOW", amount=200)

        self.assertEqual(result.status, ActionStatus.DENIED)
        self.assertEqual(self.refunds.count(), 0)

    def test_policy_exception_fails_closed_without_running_tool(self) -> None:
        executions: list[str] = []

        class BrokenPolicy:
            def evaluate(self, action_name, arguments, action_context):
                raise RuntimeError("private policy detail")

        @trusted_action(
            ledger=SQLiteActionLedger(Path(self.temporary.name) / "broken-policy.db"),
            policy=BrokenPolicy(),
            risk="financial",
            idempotency_key=lambda arguments, action_context: "broken-policy-test",
        )
        def dangerous_tool() -> dict[str, bool]:
            executions.append("executed")
            return {"executed": True}

        result = dangerous_tool.invoke(context=ActionContext(actor_id="test-agent"))

        self.assertEqual(result.status, ActionStatus.DENIED)
        self.assertEqual(executions, [])
        self.assertNotIn("private policy detail", result.reason)

    def test_replay_contains_policy_approval_execution_and_completion(self) -> None:
        pending = self.action.invoke(
            context=context("O-HIGH"), order_id="O-HIGH", amount=800
        )
        self.action.approve(
            pending.run_id,
            approver_id="finance-manager",
            note="Approved after reviewing synthetic order evidence",
        )
        self.action.resume(pending.run_id)

        trail = self.action.audit_trail(pending.run_id)
        self.assertIsNotNone(trail)
        event_types = [event["event_type"] for event in trail["events"]]
        self.assertEqual(
            event_types,
            [
                "run.created",
                "policy.checked",
                "approval.requested",
                "approval.approved",
                "run.resumed",
                "tool.execution.started",
                "tool.execution.succeeded",
                "run.completed",
            ],
        )
        self.assertEqual(
            trail["integrity"],
            {"chain_verified": False, "mode": "sqlite_reference_ledger"},
        )

    def test_persistent_demo_completes_once_and_keeps_replay_ledger(self) -> None:
        report = run_refund_demo(Path(self.temporary.name) / "demo-runs")

        self.assertEqual(
            report["states"], ["pending_approval", "approved", "completed"]
        )
        self.assertEqual(report["refund_count"], 1)
        self.assertTrue(Path(report["ledger"]).is_file())
        trail = SQLiteActionLedger(report["ledger"]).audit_trail(report["run_id"])
        self.assertIsNotNone(trail)
        self.assertEqual(trail["events"][-1]["event_type"], "run.completed")


class AsyncTrustedActionTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.ledger = SQLiteActionLedger(Path(self.temporary.name) / "async-ledger.db")

    def tearDown(self) -> None:
        self.temporary.cleanup()

    @staticmethod
    def _allow_policy():
        class AllowPolicy:
            def evaluate(self, action_name, arguments, action_context):
                return PolicyDecision(
                    outcome=PolicyOutcome.ALLOW,
                    reason="Synthetic async action allowed",
                    policy_version="async-test-v1",
                )

        return AllowPolicy()

    def _action(self, function):
        return trusted_action(
            ledger=self.ledger,
            policy=self._allow_policy(),
            risk="synthetic",
            idempotency_key=lambda arguments, action_context: (
                f"async:{action_context.tenant_id}:{arguments['item_id']}"
            ),
        )(function)

    async def test_async_action_completes_and_stores_result(self) -> None:
        async def fetch_item(item_id: str) -> dict[str, str]:
            await asyncio.sleep(0)
            return {"item_id": item_id, "state": "updated"}

        action = self._action(fetch_item)
        result = await action.invoke_async(
            context=ActionContext(actor_id="test-agent"), item_id="A-1"
        )

        self.assertEqual(result.status, ActionStatus.COMPLETED)
        self.assertEqual(result.value, {"item_id": "A-1", "state": "updated"})
        self.assertEqual(
            self.ledger.get_run(result.run_id)["result"],
            {"item_id": "A-1", "state": "updated"},
        )

    async def test_async_action_waits_for_approval_then_resumes(self) -> None:
        class ApprovalPolicy:
            def evaluate(self, action_name, arguments, action_context):
                return PolicyDecision(
                    outcome=PolicyOutcome.APPROVAL_REQUIRED,
                    reason="Synthetic approval required",
                    policy_version="async-approval-v1",
                )

        executions: list[str] = []

        @trusted_action(
            ledger=self.ledger,
            policy=ApprovalPolicy(),
            risk="high",
            idempotency_key=lambda arguments, action_context: "async-approval:A-2",
        )
        async def update_item(item_id: str) -> dict[str, str]:
            executions.append(item_id)
            return {"item_id": item_id}

        pending = await update_item.invoke_async(
            context=ActionContext(actor_id="test-agent"), item_id="A-2"
        )
        self.assertEqual(pending.status, ActionStatus.PENDING_APPROVAL)
        self.assertEqual(executions, [])

        update_item.approve(
            pending.run_id,
            approver_id="test-reviewer",
            note="Approved synthetic async test",
        )
        completed = await update_item.resume_async(pending.run_id)

        self.assertEqual(completed.status, ActionStatus.COMPLETED)
        self.assertEqual(executions, ["A-2"])

    async def test_concurrent_duplicate_async_calls_execute_once(self) -> None:
        executions: list[str] = []

        async def update_item(item_id: str) -> dict[str, str]:
            executions.append(item_id)
            await asyncio.sleep(0.02)
            return {"item_id": item_id}

        action = self._action(update_item)
        first, second = await asyncio.gather(
            action.invoke_async(
                context=ActionContext(actor_id="agent-one"), item_id="A-3"
            ),
            action.invoke_async(
                context=ActionContext(actor_id="agent-two"), item_id="A-3"
            ),
        )

        self.assertEqual(first.run_id, second.run_id)
        self.assertEqual(executions, ["A-3"])
        self.assertEqual({first.duplicate, second.duplicate}, {False, True})

    async def test_sync_invoke_on_async_action_creates_no_orphan_run(self) -> None:
        async def update_item(item_id: str) -> dict[str, str]:
            return {"item_id": item_id}

        action = self._action(update_item)
        with self.assertRaisesRegex(TypeError, "invoke_async"):
            action.invoke(context=ActionContext(actor_id="test-agent"), item_id="A-4")

        result = await action.invoke_async(
            context=ActionContext(actor_id="test-agent"), item_id="A-4"
        )
        self.assertFalse(result.duplicate)
        self.assertEqual(result.status, ActionStatus.COMPLETED)

    async def test_async_tool_failure_becomes_safe_failed_state(self) -> None:
        async def update_item(item_id: str) -> dict[str, str]:
            raise RuntimeError(f"private failure for {item_id}")

        action = self._action(update_item)
        result = await action.invoke_async(
            context=ActionContext(actor_id="test-agent"), item_id="A-5"
        )

        self.assertEqual(result.status, ActionStatus.FAILED)
        self.assertEqual(result.reason, "tool execution failed: RuntimeError")
        self.assertNotIn("private failure", result.reason)
        self.assertEqual(
            self.ledger.events(result.run_id)[-1]["event_type"],
            "tool.execution.failed",
        )

    def test_indeterminate_tool_outcome_requires_explicit_reconciliation(self) -> None:
        def charge_card(item_id: str) -> dict[str, str]:
            raise IndeterminateOutcome("provider response was lost")

        action = self._action(charge_card)
        unknown = action.invoke(
            context=ActionContext(actor_id="test-agent"), item_id="A-6"
        )

        self.assertEqual(unknown.status, ActionStatus.UNKNOWN)
        retry = action.invoke(
            context=ActionContext(actor_id="test-agent"), item_id="A-6"
        )
        self.assertTrue(retry.duplicate)
        self.assertEqual(retry.status, ActionStatus.UNKNOWN)

        completed = action.reconcile(
            unknown.run_id,
            outcome="completed",
            operator_id="reconciliation-worker",
            note="Provider lookup confirms the charge committed",
            result={"provider_id": "p-123"},
        )
        self.assertEqual(completed.status, ActionStatus.COMPLETED)
        self.assertEqual(completed.value, {"provider_id": "p-123"})
        self.assertEqual(
            self.ledger.events(unknown.run_id)[-1]["event_type"],
            "run.reconciled",
        )

        with self.assertRaisesRegex(ValueError, "waiting for reconciliation"):
            action.reconcile(
                unknown.run_id,
                outcome="failed",
                operator_id="reconciliation-worker",
                note="Second resolution is not allowed",
            )

    async def test_async_cancellation_marks_run_unknown_before_reraising(self) -> None:
        async def call_provider(item_id: str) -> dict[str, str]:
            raise asyncio.CancelledError

        action = self._action(call_provider)
        with self.assertRaises(asyncio.CancelledError):
            await action.invoke_async(
                context=ActionContext(actor_id="test-agent"), item_id="A-7"
            )

        run = self.ledger.create_or_get_run(
            run_id="unused",
            tenant_id="default",
            actor_id="test-agent",
            roles=(),
            evidence=(),
            action_name=action.name,
            risk="synthetic",
            idempotency_key="async:default:A-7",
            arguments={"item_id": "A-7"},
        )[0]
        self.assertEqual(run["status"], ActionStatus.UNKNOWN.value)


if __name__ == "__main__":
    unittest.main()
