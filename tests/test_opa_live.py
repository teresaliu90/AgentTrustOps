from __future__ import annotations

import os
import unittest

from agenttrustops import ActionContext, OPAPolicy, PolicyOutcome


class LiveOPAContractTests(unittest.TestCase):
    def test_example_policy_over_real_opa_data_api(self) -> None:
        base_url = os.environ.get("AGENTTRUSTOPS_TEST_OPA_URL")
        if not base_url:
            self.skipTest("set AGENTTRUSTOPS_TEST_OPA_URL to run the live OPA contract")
        policy = OPAPolicy(
            base_url,
            "agenttrustops/decision",
            allow_insecure_http=True,
        )
        context = ActionContext(
            actor_id="refund-agent",
            roles=("refund_agent",),
            evidence=("ORDER:O-1", "LOGISTICS:O-1"),
        )

        allowed = policy.evaluate(
            "execute_refund", {"order_id": "O-1", "amount": 100}, context
        )
        approval = policy.evaluate(
            "execute_refund", {"order_id": "O-2", "amount": 800}, context
        )
        denied = policy.evaluate("unknown_action", {}, context)

        self.assertIs(allowed.outcome, PolicyOutcome.ALLOW)
        self.assertIs(approval.outcome, PolicyOutcome.APPROVAL_REQUIRED)
        self.assertIs(denied.outcome, PolicyOutcome.DENY)
        self.assertEqual(approval.policy_version, "refunds-2026-08-10")


if __name__ == "__main__":
    unittest.main()
