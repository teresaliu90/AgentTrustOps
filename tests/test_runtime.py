from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agenttrustops import (
    ActionContext,
    ActionStatus,
    SQLiteActionLedger,
    trusted_action,
)
from agenttrustops.refund_ops import build_refund_action

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


if __name__ == "__main__":
    unittest.main()
