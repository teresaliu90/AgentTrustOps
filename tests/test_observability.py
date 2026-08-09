from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from agenttrustops import (
    ActionContext,
    ActionStatus,
    collect_operational_snapshot,
    render_prometheus,
)
from agenttrustops.refund_ops import build_refund_action


class ObservabilityTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.action, _ = build_refund_action(
            ledger_path=directory / "ledger.db",
            refund_path=directory / "refunds.db",
            policy_config={
                "release": "metrics-test",
                "selection_mode": "as_of_order",
                "approval_enabled": True,
                "require_evidence": True,
                "enforce_roles": True,
                "allowed_roles": ["refund_agent"],
            },
        )

    def tearDown(self) -> None:
        self.action.ledger.close()
        self.temporary.cleanup()

    def test_snapshot_uses_durable_counts_without_sensitive_values(self) -> None:
        context = ActionContext(
            actor_id="secret-agent",
            roles=("refund_agent",),
            evidence=("ORDER:O-HIGH", "LOGISTICS:O-HIGH"),
        )
        result = self.action.invoke(context=context, order_id="O-HIGH", amount=800)
        self.assertEqual(result.status, ActionStatus.PENDING_APPROVAL)

        snapshot = collect_operational_snapshot(
            self.action.ledger,
            tenant_id="default",
            verify_integrity=True,
        )
        document = snapshot.to_dict()
        self.assertEqual(document["status_counts"]["pending_approval"], 1)
        self.assertEqual(document["approval_counts"]["pending_approval"], 1)
        self.assertEqual(document["integrity"]["invalid"], 0)
        self.assertNotIn("secret-agent", str(document))
        self.assertNotIn("O-HIGH", str(document))

    def test_prometheus_output_has_stable_metric_names_and_labels(self) -> None:
        self.action.invoke(
            context=ActionContext(actor_id="agent", roles=("refund_agent",)),
            order_id="O-LOW",
            amount=100,
        )
        rendered = render_prometheus(
            collect_operational_snapshot(self.action.ledger, tenant_id="default")
        )

        self.assertIn(
            'agenttrustops_runs{status="denied",tenant="default"} 1', rendered
        )
        self.assertIn("agenttrustops_events_total", rendered)
        self.assertIn("agenttrustops_duplicate_retries_total", rendered)
        self.assertNotIn("refund_agent", rendered)
        self.assertNotIn("O-LOW", rendered)
        self.assertTrue(rendered.endswith("\n"))


if __name__ == "__main__":
    unittest.main()
