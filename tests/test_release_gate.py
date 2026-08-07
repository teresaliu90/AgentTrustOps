from __future__ import annotations

import unittest
from pathlib import Path

from agenttrustops.refund_ops import evaluate_release

ROOT = Path(__file__).resolve().parents[1]
SCENARIOS = ROOT / "examples" / "refund_ops" / "scenarios.json"


class ReleaseGateTests(unittest.TestCase):
    def test_safe_policy_is_allowed(self) -> None:
        report = evaluate_release(
            SCENARIOS,
            ROOT / "examples" / "refund_ops" / "policy-safe.json",
        )

        self.assertTrue(report["release_allowed"])
        self.assertEqual(report["scenarios"], 7)
        self.assertEqual(report["wrong_decisions"], 0)
        self.assertEqual(report["wrong_policy_decisions"], 0)
        self.assertEqual(report["approval_bypasses"], 0)
        self.assertEqual(report["duplicate_side_effects"], 0)

    def test_unsafe_policy_is_blocked_for_explainable_reasons(self) -> None:
        report = evaluate_release(
            SCENARIOS,
            ROOT / "examples" / "refund_ops" / "policy-unsafe.json",
        )

        self.assertFalse(report["release_allowed"])
        self.assertEqual(report["wrong_decisions"], 3)
        self.assertEqual(report["wrong_policy_decisions"], 1)
        self.assertEqual(report["approval_bypasses"], 1)
        self.assertEqual(report["duplicate_side_effects"], 0)


if __name__ == "__main__":
    unittest.main()
