from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from fastapi.testclient import TestClient

from agenttrustops import (
    ActionContext,
    ActionRegistry,
    StaticTokenVerifier,
    VerifiedPrincipal,
)
from agenttrustops.api import create_app
from agenttrustops.refund_ops import build_refund_action

INVOKER_TOKEN = "invoke-token-0000000001"
MANAGER_TOKEN = "manager-token-000000001"
FOREIGN_TOKEN = "foreign-token-000000001"


class ApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        directory = Path(self.temporary.name)
        self.action, self.refunds = build_refund_action(
            ledger_path=directory / "ledger.db",
            refund_path=directory / "refunds.db",
            policy_config={
                "release": "api-test",
                "selection_mode": "as_of_order",
                "approval_enabled": True,
                "require_evidence": True,
                "enforce_roles": True,
                "allowed_roles": ["refund_agent"],
            },
        )
        registry = ActionRegistry(self.action.ledger, [self.action])
        verifier = StaticTokenVerifier(
            {
                INVOKER_TOKEN: VerifiedPrincipal(
                    actor_id="refund-agent",
                    tenant_id="default",
                    roles=(
                        "agenttrustops_invoker",
                        "agenttrustops_viewer",
                        "refund_agent",
                    ),
                    auth_source="test-oidc",
                ),
                MANAGER_TOKEN: VerifiedPrincipal(
                    actor_id="finance-manager",
                    tenant_id="default",
                    roles=(
                        "agenttrustops_approver",
                        "agenttrustops_auditor",
                        "agenttrustops_executor",
                        "agenttrustops_observer",
                        "agenttrustops_operator",
                        "agenttrustops_viewer",
                    ),
                    auth_source="test-oidc",
                ),
                FOREIGN_TOKEN: VerifiedPrincipal(
                    actor_id="foreign-manager",
                    tenant_id="beta",
                    roles=(
                        "agenttrustops_approver",
                        "agenttrustops_auditor",
                        "agenttrustops_viewer",
                    ),
                    auth_source="test-oidc",
                ),
            }
        )

        def resolve_context(principal, action_name, arguments, evidence_refs):
            evidence: tuple[str, ...] = ()
            if evidence_refs == ("verified-order-record", "verified-logistics-record"):
                order_id = str(arguments.get("order_id", ""))
                evidence = (f"ORDER:{order_id}", f"LOGISTICS:{order_id}")
            return ActionContext(
                actor_id=principal.actor_id,
                tenant_id=principal.tenant_id,
                roles=principal.roles,
                evidence=evidence,
                metadata={"evidence_source": "test-record-system"},
            )

        self.client = TestClient(
            create_app(registry, verifier, context_resolver=resolve_context)
        )

    def tearDown(self) -> None:
        self.client.close()
        self.action.ledger.close()
        self.temporary.cleanup()

    @staticmethod
    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def invoke_high(self, *, key: str = "request-key-high-001", amount: int = 800):
        return self.client.post(
            "/v1/actions/execute_refund/invoke",
            headers={**self.auth(INVOKER_TOKEN), "Idempotency-Key": key},
            json={
                "arguments": {"order_id": "O-HIGH", "amount": amount},
                "evidence_refs": [
                    "verified-order-record",
                    "verified-logistics-record",
                ],
            },
        )

    def test_health_is_public_but_control_plane_requires_authentication(self) -> None:
        self.assertEqual(self.client.get("/healthz").status_code, 200)
        response = self.client.get("/v1/actions")
        self.assertEqual(response.status_code, 401)
        self.assertEqual(response.headers["www-authenticate"], "Bearer")

    def test_console_shell_is_public_hardened_and_keeps_api_authenticated(self) -> None:
        page = self.client.get("/ui")
        css = self.client.get("/ui/control-plane.css")
        script = self.client.get("/ui/control-plane.js")

        self.assertEqual(page.status_code, 200)
        self.assertIn("AgentTrustOps Control Plane", page.text)
        self.assertIn("default-src 'none'", page.headers["content-security-policy"])
        self.assertEqual(page.headers["x-content-type-options"], "nosniff")
        self.assertTrue(css.headers["content-type"].startswith("text/css"))
        self.assertTrue(script.headers["content-type"].startswith("text/javascript"))
        self.assertNotIn("localStorage", script.text)
        self.assertNotIn("sessionStorage", script.text)
        self.assertIn("reconcile-from-provider", script.text)
        self.assertEqual(self.client.get("/v1/runs").status_code, 401)

    def test_retry_returns_the_same_public_answer_without_regeneration(self) -> None:
        first = self.invoke_high()
        run_id = first.json()["run_id"]
        original_chain = self.action.ledger.events(run_id)
        second = self.invoke_high()

        self.assertEqual(first.status_code, 200)
        self.assertEqual(first.json(), second.json())
        self.assertEqual(first.json()["status"], "pending_approval")
        self.assertEqual(self.refunds.count("O-HIGH"), 0)
        self.assertEqual(self.action.ledger.events(run_id), original_chain)
        self.assertEqual(self.action.ledger.get_run(run_id)["duplicate_count"], 1)

    def test_same_idempotency_key_with_different_body_is_conflict(self) -> None:
        self.assertEqual(self.invoke_high(amount=800).status_code, 200)
        conflict = self.invoke_high(amount=700)
        self.assertEqual(conflict.status_code, 409)
        self.assertIn("different governed request", conflict.json()["detail"])

    def test_sensitive_identity_and_idempotency_fields_are_not_in_response(
        self,
    ) -> None:
        response = self.invoke_high()
        serialized = response.text

        self.assertNotIn("request-key-high-001", serialized)
        self.assertNotIn(INVOKER_TOKEN, serialized)
        self.assertNotIn("verified-order-record", serialized)
        self.assertNotIn("refund-agent", serialized)

    def test_approval_and_resume_form_a_complete_authenticated_workflow(self) -> None:
        pending = self.invoke_high().json()
        run_id = pending["run_id"]

        self_approval = self.client.post(
            f"/v1/runs/{run_id}/approve",
            headers=self.auth(INVOKER_TOKEN),
            json={"note": "agent tries to approve itself"},
        )
        self.assertEqual(self_approval.status_code, 403)

        approved = self.client.post(
            f"/v1/runs/{run_id}/approve",
            headers=self.auth(MANAGER_TOKEN),
            json={"note": "finance manager verified the synthetic order"},
        )
        self.assertEqual(approved.status_code, 200)
        self.assertEqual(approved.json()["status"], "approved")

        completed = self.client.post(
            f"/v1/runs/{run_id}/resume",
            headers=self.auth(MANAGER_TOKEN),
        )
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["status"], "completed")
        self.assertEqual(self.refunds.count("O-HIGH"), 1)

    def test_audit_is_tenant_scoped_and_role_redacted(self) -> None:
        run_id = self.invoke_high().json()["run_id"]
        viewer = self.client.get(
            f"/v1/runs/{run_id}/audit",
            headers=self.auth(INVOKER_TOKEN),
        )
        auditor = self.client.get(
            f"/v1/runs/{run_id}/audit",
            headers=self.auth(MANAGER_TOKEN),
        )
        foreign = self.client.get(
            f"/v1/runs/{run_id}/audit",
            headers=self.auth(FOREIGN_TOKEN),
        )

        self.assertFalse(viewer.json()["sensitive_fields_included"])
        self.assertTrue(auditor.json()["sensitive_fields_included"])
        self.assertEqual(foreign.status_code, 404)

    def test_request_cannot_supply_actor_tenant_or_roles(self) -> None:
        response = self.client.post(
            "/v1/actions/execute_refund/invoke",
            headers={
                **self.auth(INVOKER_TOKEN),
                "Idempotency-Key": "request-key-spoof-001",
            },
            json={
                "arguments": {"order_id": "O-HIGH", "amount": 800},
                "evidence_refs": [],
                "actor_id": "admin",
                "tenant_id": "beta",
                "roles": ["agenttrustops_approver"],
            },
        )
        self.assertEqual(response.status_code, 422)

    def test_metrics_are_authenticated_and_privacy_safe(self) -> None:
        self.invoke_high()
        forbidden = self.client.get("/metrics", headers=self.auth(INVOKER_TOKEN))
        metrics = self.client.get("/metrics", headers=self.auth(MANAGER_TOKEN))

        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(metrics.status_code, 200)
        self.assertIn("agenttrustops_runs", metrics.text)
        self.assertNotIn("refund-agent", metrics.text)
        self.assertNotIn("O-HIGH", metrics.text)


if __name__ == "__main__":
    unittest.main()
