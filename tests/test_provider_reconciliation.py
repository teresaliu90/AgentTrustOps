from __future__ import annotations

import tempfile
import threading
import unittest
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

from fastapi.testclient import TestClient

from agenttrustops import (
    ActionContext,
    ActionRegistry,
    ActionStatus,
    ApprovalDenied,
    IndeterminateOutcome,
    PolicyDecision,
    PolicyOutcome,
    ProviderLookup,
    ProviderLookupError,
    ProviderObservation,
    ProviderOutcome,
    SQLiteActionLedger,
    StaticTokenVerifier,
    VerifiedPrincipal,
    trusted_action,
)
from agenttrustops.api import create_app

INVOKER_TOKEN = "provider-invoker-token-0001"
RECONCILER_TOKEN = "provider-reconciler-token-01"


class AllowPolicy:
    def evaluate(self, action_name, arguments, context):
        return PolicyDecision(PolicyOutcome.ALLOW, "allowed", "provider-test-v1")


class SequenceProbe:
    name = "synthetic-payments"

    def __init__(self, *observations: ProviderObservation):
        self.observations = list(observations)
        self.requests: list[ProviderLookup] = []

    def lookup(self, request: ProviderLookup) -> ProviderObservation:
        self.requests.append(request)
        return self.observations.pop(0)


class FailingProbe:
    name = "unavailable-payments"

    def lookup(self, request: ProviderLookup) -> ProviderObservation:
        raise ProviderLookupError("synthetic provider unavailable")


def reconciler(*, tenant_id: str = "tenant-a") -> VerifiedPrincipal:
    return VerifiedPrincipal(
        actor_id="reconciliation-worker",
        tenant_id=tenant_id,
        roles=("agenttrustops_reconciler",),
        auth_source="test-oidc",
    )


class ProviderReconciliationTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.ledger = SQLiteActionLedger(Path(self.temporary.name) / "ledger.db")

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="payment",
            idempotency_key=lambda arguments, context: (
                f"charge:{context.tenant_id}:{arguments['invoice_id']}"
            ),
        )
        def charge_invoice(invoice_id: str, amount: int) -> dict[str, object]:
            raise IndeterminateOutcome("response lost after provider handoff")

        self.action = charge_invoice
        self.context = ActionContext(actor_id="agent-a", tenant_id="tenant-a")

    def tearDown(self) -> None:
        self.ledger.close()
        self.temporary.cleanup()

    def invoke_unknown(self):
        return self.action.invoke(
            context=self.context,
            invoice_id="INV-42",
            amount=1250,
        )

    def test_committed_lookup_uses_persisted_request_and_safe_result(self) -> None:
        unknown = self.invoke_unknown()
        probe = SequenceProbe(
            ProviderObservation(
                ProviderOutcome.COMMITTED,
                "charge found by idempotency key",
                reference="pay_safe_42",
                safe_result={"receipt_state": "settled"},
            )
        )

        completed = self.action.reconcile_from_provider(
            unknown.run_id,
            probe=probe,
            principal=reconciler(),
        )

        self.assertEqual(completed.status, ActionStatus.COMPLETED)
        self.assertEqual(
            completed.value,
            {
                "provider": "synthetic-payments",
                "provider_reference": "pay_safe_42",
                "safe_result": {"receipt_state": "settled"},
            },
        )
        self.assertEqual(probe.requests[0].idempotency_key, "charge:tenant-a:INV-42")
        self.assertEqual(
            probe.requests[0].arguments,
            {"amount": 1250, "invoice_id": "INV-42"},
        )
        self.assertEqual(
            [event["event_type"] for event in self.ledger.events(unknown.run_id)][-2:],
            ["provider.reconciliation.observed", "run.reconciled"],
        )
        public_event = self.ledger.audit_trail(unknown.run_id)["events"][-2]
        self.assertEqual(public_event["payload"]["provider"], "synthetic-payments")
        self.assertTrue(public_event["payload"]["summary"]["redacted"])
        self.assertTrue(public_event["payload"]["reference"]["redacted"])

    def test_pending_observation_keeps_unknown_until_provider_is_definitive(
        self,
    ) -> None:
        unknown = self.invoke_unknown()
        probe = SequenceProbe(
            ProviderObservation(
                ProviderOutcome.PENDING,
                "provider is still processing the charge",
            ),
            ProviderObservation(
                ProviderOutcome.COMMITTED,
                "provider later confirmed the charge",
            ),
        )

        pending = self.action.reconcile_from_provider(
            unknown.run_id,
            probe=probe,
            principal=reconciler(),
        )
        completed = self.action.reconcile_from_provider(
            unknown.run_id,
            probe=probe,
            principal=reconciler(),
        )

        self.assertEqual(pending.status, ActionStatus.UNKNOWN)
        self.assertEqual(completed.status, ActionStatus.COMPLETED)
        self.assertEqual(len(probe.requests), 2)

    def test_not_committed_lookup_resolves_failed_without_reexecution(self) -> None:
        unknown = self.invoke_unknown()
        probe = SequenceProbe(
            ProviderObservation(
                ProviderOutcome.NOT_COMMITTED,
                "no provider operation exists for the stable key",
            )
        )

        failed = self.action.reconcile_from_provider(
            unknown.run_id,
            probe=probe,
            principal=reconciler(),
        )

        self.assertEqual(failed.status, ActionStatus.FAILED)
        self.assertEqual(failed.attempt, 1)

    def test_concurrent_conflicting_observations_commit_only_one_conclusion(
        self,
    ) -> None:
        unknown = self.invoke_unknown()
        barrier = threading.Barrier(2)

        class BarrierProbe:
            name = "synthetic-payments"

            def __init__(self, outcome: ProviderOutcome):
                self.outcome = outcome

            def lookup(self, request: ProviderLookup) -> ProviderObservation:
                barrier.wait(timeout=2)
                return ProviderObservation(
                    self.outcome,
                    f"synthetic {self.outcome.value} conclusion",
                )

        def reconcile(outcome: ProviderOutcome):
            return self.action.reconcile_from_provider(
                unknown.run_id,
                probe=BarrierProbe(outcome),
                principal=reconciler(),
            )

        with ThreadPoolExecutor(max_workers=2) as pool:
            results = list(
                pool.map(
                    reconcile,
                    (ProviderOutcome.COMMITTED, ProviderOutcome.NOT_COMMITTED),
                )
            )

        self.assertEqual(results[0].status, results[1].status)
        self.assertEqual(sum(result.duplicate for result in results), 1)
        event_types = [
            event["event_type"] for event in self.ledger.events(unknown.run_id)
        ]
        self.assertEqual(event_types.count("provider.reconciliation.observed"), 1)
        self.assertEqual(event_types.count("run.reconciled"), 1)

    def test_authorization_and_provider_failures_leave_run_unknown(self) -> None:
        unknown = self.invoke_unknown()
        observer = VerifiedPrincipal(
            actor_id="viewer",
            tenant_id="tenant-a",
            roles=("agenttrustops_viewer",),
            auth_source="test-oidc",
        )

        with self.assertRaises(ApprovalDenied):
            self.action.reconcile_from_provider(
                unknown.run_id,
                probe=FailingProbe(),
                principal=observer,
            )
        with self.assertRaises(ProviderLookupError):
            self.action.reconcile_from_provider(
                unknown.run_id,
                probe=FailingProbe(),
                principal=reconciler(),
            )

        self.assertEqual(
            self.ledger.get_run(unknown.run_id)["status"],
            ActionStatus.UNKNOWN.value,
        )

    def test_observation_contract_rejects_unsafe_or_ambiguous_values(self) -> None:
        with self.assertRaises(TypeError):
            ProviderObservation("committed", "not an enum")  # type: ignore[arg-type]
        with self.assertRaisesRegex(ValueError, "JSON serializable"):
            ProviderObservation(
                ProviderOutcome.COMMITTED,
                "invalid safe result",
                safe_result={"secret": object()},
            )


class ProviderReconciliationApiTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.ledger = SQLiteActionLedger(Path(self.temporary.name) / "ledger.db")

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="message",
            idempotency_key=lambda arguments, context: "unused-by-http-gateway",
        )
        def send_message(message: str) -> dict[str, str]:
            raise IndeterminateOutcome("synthetic timeout")

        self.action = send_message
        self.probe = SequenceProbe(
            ProviderObservation(
                ProviderOutcome.COMMITTED,
                "message accepted",
                reference="msg_safe_7",
            )
        )
        verifier = StaticTokenVerifier(
            {
                INVOKER_TOKEN: VerifiedPrincipal(
                    actor_id="agent-a",
                    tenant_id="tenant-a",
                    roles=("agenttrustops_invoker", "agenttrustops_viewer"),
                    auth_source="test-oidc",
                ),
                RECONCILER_TOKEN: VerifiedPrincipal(
                    actor_id="operator-a",
                    tenant_id="tenant-a",
                    roles=("agenttrustops_reconciler", "agenttrustops_viewer"),
                    auth_source="test-oidc",
                ),
            }
        )
        registry = ActionRegistry(self.ledger, [self.action])
        self.client = TestClient(
            create_app(
                registry,
                verifier,
                provider_probes={"send_message": self.probe},
            )
        )

    def tearDown(self) -> None:
        self.client.close()
        self.ledger.close()
        self.temporary.cleanup()

    @staticmethod
    def auth(token: str) -> dict[str, str]:
        return {"Authorization": f"Bearer {token}"}

    def test_authenticated_endpoint_reconciles_from_server_owned_probe(self) -> None:
        unknown = self.client.post(
            "/v1/actions/send_message/invoke",
            headers={
                **self.auth(INVOKER_TOKEN),
                "Idempotency-Key": "message-request-key-001",
            },
            json={"arguments": {"message": "synthetic hello"}},
        ).json()

        forbidden = self.client.post(
            f"/v1/runs/{unknown['run_id']}/reconcile-from-provider",
            headers=self.auth(INVOKER_TOKEN),
        )
        completed = self.client.post(
            f"/v1/runs/{unknown['run_id']}/reconcile-from-provider",
            headers=self.auth(RECONCILER_TOKEN),
        )

        self.assertEqual(unknown["status"], "unknown")
        self.assertEqual(forbidden.status_code, 403)
        self.assertEqual(completed.status_code, 200)
        self.assertEqual(completed.json()["status"], "completed")
        self.assertNotIn("message-request-key-001", completed.text)

    def test_api_provider_failure_is_generic_and_preserves_unknown(self) -> None:
        registry = ActionRegistry(self.ledger, [self.action])
        verifier = StaticTokenVerifier(
            {
                RECONCILER_TOKEN: VerifiedPrincipal(
                    actor_id="operator-a",
                    tenant_id="tenant-a",
                    roles=("agenttrustops_reconciler",),
                    auth_source="test-oidc",
                )
            }
        )
        failing_client = TestClient(
            create_app(
                registry,
                verifier,
                provider_probes={"send_message": FailingProbe()},
            )
        )
        unknown = self.action.invoke(
            context=ActionContext(actor_id="agent-a", tenant_id="tenant-a"),
            message="synthetic hello",
        )

        response = failing_client.post(
            f"/v1/runs/{unknown.run_id}/reconcile-from-provider",
            headers=self.auth(RECONCILER_TOKEN),
        )
        failing_client.close()

        self.assertEqual(response.status_code, 502)
        self.assertNotIn("synthetic provider unavailable", response.text)
        self.assertEqual(
            self.ledger.get_run(unknown.run_id)["status"],
            ActionStatus.UNKNOWN.value,
        )
