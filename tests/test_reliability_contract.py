from __future__ import annotations

import json
import sqlite3
import tempfile
import time
import unittest
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing
from pathlib import Path

from agenttrustops import (
    ActionContext,
    ActionStatus,
    ApprovalDenied,
    PolicyDecision,
    PolicyOutcome,
    SQLiteActionLedger,
    VerifiedPrincipal,
    trusted_action,
)
from agenttrustops.ledger import request_fingerprint
from agenttrustops.refund_ops import build_refund_action


def reconcile_principal() -> VerifiedPrincipal:
    return VerifiedPrincipal(
        actor_id="reconciliation-worker",
        tenant_id="default",
        roles=("agenttrustops_reconciler",),
        auth_source="test-oidc",
    )


class LedgerReliabilityContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.path = Path(self.temporary.name) / "ledger.db"
        self.ledger = SQLiteActionLedger(self.path)

    def tearDown(self) -> None:
        self.ledger.close()
        self.temporary.cleanup()

    def create_run(self, *, key: str = "intent-1") -> str:
        arguments = {"resource_id": "R-1", "value": 10}
        fingerprint = request_fingerprint(
            tenant_id="default",
            actor_id="test-agent",
            roles=("operator",),
            evidence=("RESOURCE:R-1",),
            action_name="change_resource",
            risk="high",
            arguments=arguments,
        )
        run, created = self.ledger.create_or_get_run(
            run_id=f"run-{key}",
            tenant_id="default",
            actor_id="test-agent",
            roles=("operator",),
            evidence=("RESOURCE:R-1",),
            action_name="change_resource",
            risk="high",
            idempotency_key=key,
            request_fingerprint=fingerprint,
            arguments=arguments,
        )
        self.assertTrue(created)
        return str(run["run_id"])

    def allow(self, run_id: str) -> None:
        self.ledger.record_policy_decision(
            run_id,
            PolicyDecision(
                PolicyOutcome.ALLOW,
                "Synthetic contract allows execution",
                "contract-v1",
                policy_digest="sha256:contract-v1",
            ),
            approval_ttl_seconds=60,
        )

    def test_state_and_policy_event_rollback_together(self) -> None:
        run_id = self.create_run()
        original = self.ledger._append_event_tx

        def fail_event(*args, **kwargs):
            raise RuntimeError("synthetic event failure")

        self.ledger._append_event_tx = fail_event
        with self.assertRaisesRegex(RuntimeError, "synthetic event failure"):
            self.allow(run_id)
        self.ledger._append_event_tx = original

        run = self.ledger.get_run(run_id)
        self.assertEqual(run["status"], ActionStatus.CREATED.value)
        self.assertIsNone(run["policy_version"])
        self.assertEqual(
            [event["event_type"] for event in self.ledger.events(run_id)],
            ["run.created"],
        )

    def test_state_and_completion_events_rollback_together(self) -> None:
        run_id = self.create_run()
        self.allow(run_id)
        self.ledger.claim_execution(run_id, owner="worker", lease_seconds=60)
        original = self.ledger._append_event_tx

        def fail_event(*args, **kwargs):
            raise RuntimeError("synthetic completion event failure")

        self.ledger._append_event_tx = fail_event
        with self.assertRaisesRegex(RuntimeError, "completion event failure"):
            self.ledger.complete_execution(
                run_id,
                owner="worker",
                result={"ok": True},
            )
        self.ledger._append_event_tx = original

        run = self.ledger.get_run(run_id)
        self.assertEqual(run["status"], ActionStatus.EXECUTING.value)
        self.assertEqual(run["execution_owner"], "worker")
        self.assertNotIn(
            "run.completed",
            [event["event_type"] for event in self.ledger.events(run_id)],
        )

    def test_request_fingerprint_is_canonical_but_rejects_non_finite_numbers(self):
        common = {
            "tenant_id": "default",
            "actor_id": "agent",
            "action_name": "action",
            "risk": "high",
        }
        first = request_fingerprint(
            **common,
            roles=("b", "a"),
            evidence=("two", "one"),
            arguments={"b": 2, "a": 1},
        )
        second = request_fingerprint(
            **common,
            roles=("a", "b"),
            evidence=("one", "two"),
            arguments={"a": 1, "b": 2},
        )

        self.assertEqual(first, second)
        with self.assertRaisesRegex(ValueError, "Out of range float values"):
            request_fingerprint(
                **common,
                roles=(),
                evidence=(),
                arguments={"amount": float("nan")},
            )

    def test_live_execution_lease_has_one_owner(self) -> None:
        run_id = self.create_run()
        self.allow(run_id)

        self.assertTrue(
            self.ledger.claim_execution(run_id, owner="worker-one", lease_seconds=60)
        )
        self.assertFalse(
            self.ledger.claim_execution(run_id, owner="worker-two", lease_seconds=60)
        )
        self.assertEqual(self.ledger.get_run(run_id)["execution_owner"], "worker-one")

    def test_execution_cannot_start_before_policy_decision(self) -> None:
        run_id = self.create_run()

        self.assertFalse(
            self.ledger.claim_execution(run_id, owner="worker", lease_seconds=60)
        )
        self.assertEqual(self.ledger.get_run(run_id)["status"], "created")

    def test_expired_lease_cannot_be_revived_by_a_late_heartbeat(self) -> None:
        run_id = self.create_run()
        self.allow(run_id)
        self.ledger.claim_execution(run_id, owner="worker", lease_seconds=1)
        time.sleep(1.05)

        self.assertFalse(
            self.ledger.heartbeat_execution(
                run_id,
                owner="worker",
                lease_seconds=60,
            )
        )

    def test_expired_execution_becomes_unknown_and_never_auto_retries(self) -> None:
        run_id = self.create_run()
        self.allow(run_id)
        self.assertTrue(
            self.ledger.claim_execution(run_id, owner="dead-worker", lease_seconds=1)
        )
        time.sleep(1.05)

        self.assertEqual(self.ledger.recover_expired_executions(), (run_id,))
        run = self.ledger.get_run(run_id)
        self.assertEqual(run["status"], ActionStatus.UNKNOWN.value)
        self.assertFalse(
            self.ledger.claim_execution(run_id, owner="retry-worker", lease_seconds=60)
        )
        self.assertEqual(self.ledger.recover_expired_executions(), ())
        self.assertEqual(
            self.ledger.events(run_id)[-1]["event_type"],
            "tool.execution.lease_expired",
        )

    def test_unknown_reconciliation_is_atomic_and_single_use(self) -> None:
        run_id = self.create_run()
        self.allow(run_id)
        self.ledger.claim_execution(run_id, owner="worker", lease_seconds=60)
        self.ledger.mark_execution_unknown(
            run_id, owner="worker", error_type="ProviderResponseLost"
        )

        self.assertTrue(
            self.ledger.reconcile_run(
                run_id,
                ActionStatus.COMPLETED,
                reason="Provider lookup confirmed commit",
                result={"provider_id": "synthetic-1"},
                principal=reconcile_principal(),
            )
        )
        self.assertFalse(
            self.ledger.reconcile_run(
                run_id,
                ActionStatus.FAILED,
                reason="A second decision is forbidden",
                principal=reconcile_principal(),
            )
        )
        self.assertEqual(self.ledger.get_run(run_id)["status"], "completed")

    def test_event_hash_chain_detects_tampering(self) -> None:
        run_id = self.create_run()
        self.allow(run_id)
        self.assertTrue(self.ledger.verify_event_chain(run_id))

        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                "UPDATE action_events SET payload_json = ? WHERE run_id = ? AND sequence = 1",
                (json.dumps({"tampered": True}), run_id),
            )

        self.assertFalse(self.ledger.verify_event_chain(run_id))
        self.assertFalse(self.ledger.audit_trail(run_id)["integrity"]["chain_verified"])
        self.ledger.close()
        self.ledger = SQLiteActionLedger(self.path)
        self.assertFalse(self.ledger.verify_event_chain(run_id))

    def test_event_chain_anchor_detects_tail_deletion(self) -> None:
        run_id = self.create_run()
        self.allow(run_id)
        self.assertTrue(self.ledger.verify_event_chain(run_id))

        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                """
                DELETE FROM action_events WHERE sequence = (
                    SELECT MAX(sequence) FROM action_events WHERE run_id = ?
                )
                """,
                (run_id,),
            )

        self.assertFalse(self.ledger.verify_event_chain(run_id))

    def test_threaded_duplicate_requests_execute_once(self) -> None:
        action, refunds = build_refund_action(
            ledger_path=Path(self.temporary.name) / "thread-ledger.db",
            refund_path=Path(self.temporary.name) / "thread-refunds.db",
            policy_config={
                "release": "thread-test",
                "selection_mode": "as_of_order",
                "approval_enabled": True,
                "require_evidence": True,
                "enforce_roles": True,
                "allowed_roles": ["refund_agent"],
            },
        )
        context = ActionContext(
            actor_id="thread-agent",
            roles=("refund_agent",),
            evidence=("ORDER:O-LOW", "LOGISTICS:O-LOW"),
        )

        def invoke():
            return action.invoke(context=context, order_id="O-LOW", amount=100)

        with ThreadPoolExecutor(max_workers=12) as executor:
            results = list(executor.map(lambda _: invoke(), range(24)))

        self.assertEqual(len({result.run_id for result in results}), 1)
        self.assertEqual(sum(not result.duplicate for result in results), 1)
        self.assertEqual(refunds.count("O-LOW"), 1)

    def test_runtime_renews_the_execution_lease_for_a_long_sync_tool(self) -> None:
        calls = 0

        class AllowPolicy:
            def evaluate(self, action_name, arguments, context):
                return PolicyDecision(PolicyOutcome.ALLOW, "allowed", "lease-v1")

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="high",
            idempotency_key=lambda arguments, context: "long-tool",
            execution_lease_seconds=1,
        )
        def long_tool() -> dict[str, bool]:
            nonlocal calls
            calls += 1
            time.sleep(1.4)
            return {"ok": True}

        context = ActionContext(actor_id="agent")
        with ThreadPoolExecutor(max_workers=2) as executor:
            first = executor.submit(long_tool.invoke, context=context)
            time.sleep(1.1)
            duplicate = long_tool.invoke(context=context)
            completed = first.result()

        self.assertEqual(completed.status, ActionStatus.COMPLETED)
        self.assertEqual(duplicate.status, ActionStatus.EXECUTING)
        self.assertTrue(duplicate.duplicate)
        self.assertEqual(calls, 1)

    def test_non_serializable_result_is_unknown_not_silently_completed(self) -> None:
        class AllowPolicy:
            def evaluate(self, action_name, arguments, context):
                return PolicyDecision(
                    PolicyOutcome.ALLOW, "allowed", "serialization-v1"
                )

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="high",
            idempotency_key=lambda arguments, context: "non-serializable",
        )
        def non_serializable():
            return object()

        result = non_serializable.invoke(context=ActionContext(actor_id="agent"))

        self.assertEqual(result.status, ActionStatus.UNKNOWN)
        self.assertIn("ResultSerializationError", result.reason)

    def test_expired_approval_is_terminal_and_cannot_execute(self) -> None:
        class ApprovalPolicy:
            def evaluate(self, action_name, arguments, context):
                return PolicyDecision(
                    PolicyOutcome.APPROVAL_REQUIRED,
                    "manager approval required",
                    "approval-v1",
                )

        @trusted_action(
            ledger=self.ledger,
            policy=ApprovalPolicy(),
            risk="high",
            idempotency_key=lambda arguments, context: "expiring-approval",
            approval_ttl_seconds=1,
        )
        def protected_tool():
            return {"executed": True}

        pending = protected_tool.invoke(context=ActionContext(actor_id="requester"))
        time.sleep(1.05)
        self.assertEqual(self.ledger.expire_approvals(), (pending.run_id,))
        self.assertEqual(self.ledger.expire_approvals(), ())
        with self.assertRaisesRegex(ApprovalDenied, "expired"):
            protected_tool.approve(
                pending.run_id,
                principal=VerifiedPrincipal(
                    actor_id="manager",
                    tenant_id="default",
                    roles=("agenttrustops_approver",),
                    auth_source="test-oidc",
                ),
                note="too late",
            )

        self.assertEqual(
            self.ledger.get_run(pending.run_id)["status"],
            ActionStatus.APPROVAL_EXPIRED.value,
        )
        with self.assertRaisesRegex(ValueError, "must be approved"):
            protected_tool.resume(pending.run_id)


if __name__ == "__main__":
    unittest.main()
