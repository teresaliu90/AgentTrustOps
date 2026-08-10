from __future__ import annotations

import json
import unittest
from unittest.mock import patch

from agenttrustops import ActionContext, OPAPolicy, PolicyOutcome


class FakeResponse:
    def __init__(self, body: dict) -> None:
        self.body = json.dumps(body).encode()

    def __enter__(self):
        return self

    def __exit__(self, *args):
        return False

    def read(self, limit: int) -> bytes:
        return self.body[:limit]


class OPAPolicyTests(unittest.TestCase):
    def test_requires_tls_by_default(self) -> None:
        with self.assertRaisesRegex(ValueError, "requires HTTPS"):
            OPAPolicy("http://opa.internal:8181", "agenttrust/decision")

    def test_translates_a_versioned_opa_decision(self) -> None:
        policy = OPAPolicy("https://opa.internal", "agenttrust/decision")
        response = FakeResponse(
            {
                "result": {
                    "outcome": "approval_required",
                    "reason": "amount exceeds autonomous limit",
                    "policy_version": "refunds-42",
                    "policy_digest": "sha256:abc",
                    "facts": {"limit": 500},
                }
            }
        )
        with patch(
            "agenttrustops.integrations.opa.urlopen", return_value=response
        ) as call:
            decision = policy.evaluate(
                "refund",
                {"amount": 800},
                ActionContext(
                    actor_id="agent-1",
                    tenant_id="tenant-a",
                    roles=("refund_agent",),
                    evidence=("ORDER:O-1",),
                ),
            )

        self.assertIs(decision.outcome, PolicyOutcome.APPROVAL_REQUIRED)
        self.assertEqual(decision.policy_version, "refunds-42")
        request = call.call_args.args[0]
        sent = json.loads(request.data)
        self.assertEqual(sent["input"]["context"]["tenant_id"], "tenant-a")
        self.assertEqual(sent["input"]["arguments"]["amount"], 800)

    def test_rejects_undefined_or_malformed_decisions(self) -> None:
        policy = OPAPolicy("https://opa.internal", "agenttrust/decision")
        with (
            patch(
                "agenttrustops.integrations.opa.urlopen",
                return_value=FakeResponse({"result": {"outcome": "allow"}}),
            ),
            self.assertRaisesRegex(ValueError, "invalid decision contract"),
        ):
            policy.evaluate("refund", {}, ActionContext(actor_id="agent-1"))


if __name__ == "__main__":
    unittest.main()
