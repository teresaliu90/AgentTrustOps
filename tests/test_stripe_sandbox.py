from __future__ import annotations

import asyncio
import tempfile
import unittest
from copy import deepcopy
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

from agenttrustops import (
    ActionContext,
    ActionExecutionContext,
    ActionStatus,
    IdempotencyConflict,
    IndeterminateOutcome,
    PolicyDecision,
    PolicyOutcome,
    ProviderLookup,
    ProviderLookupError,
    SQLiteActionLedger,
    StripeSandboxPaymentAdapter,
    StripeSandboxPaymentProbe,
    VerifiedPrincipal,
    trusted_action,
)


class AllowPolicy:
    def evaluate(self, action_name, arguments, context):
        return PolicyDecision(PolicyOutcome.ALLOW, "allowed", "stripe-test-v1")


class FakeConnectionError(Exception):
    pass


class FakePaymentIntents:
    def __init__(
        self,
        *,
        status: str = "succeeded",
        fail: BaseException | None = None,
        mismatched_amount: bool = False,
    ):
        self.status = status
        self.fail = fail
        self.mismatched_amount = mismatched_amount
        self.requests: list[tuple[dict[str, Any], dict[str, str]]] = []
        self._responses: dict[str, tuple[dict[str, Any], dict[str, Any]]] = {}

    def create(self, params: dict[str, Any], options: dict[str, str]):
        self.requests.append((deepcopy(params), dict(options)))
        if self.fail is not None:
            raise self.fail
        key = options["idempotency_key"]
        existing = self._responses.get(key)
        if existing is not None:
            previous_params, response = existing
            if previous_params != params:
                raise ValueError("idempotency parameters changed")
            return deepcopy(response)
        response = {
            "id": f"pi_test_{len(self._responses) + 1}",
            "status": self.status,
            "amount": params["amount"] + (1 if self.mismatched_amount else 0),
            "currency": params["currency"],
            "livemode": False,
            "metadata": dict(params["metadata"]),
            "client_secret": "must_never_be_returned_or_persisted",
        }
        self._responses[key] = (deepcopy(params), response)
        return deepcopy(response)

    @property
    def unique_payment_count(self) -> int:
        return len(self._responses)


def reconciler() -> VerifiedPrincipal:
    return VerifiedPrincipal(
        actor_id="stripe-reconciler",
        tenant_id="sandbox",
        roles=("agenttrustops_reconciler",),
        auth_source="test-oidc",
    )


class TrustedExecutionContextTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.ledger = SQLiteActionLedger(Path(self.temporary.name) / "ledger.db")

    def tearDown(self) -> None:
        self.ledger.close()
        self.temporary.cleanup()

    def test_gateway_key_is_injected_and_cannot_be_supplied_as_an_argument(
        self,
    ) -> None:
        received: list[ActionExecutionContext] = []

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="payment",
            idempotency_key=lambda arguments, context: "sdk-generated-key",
            execution_context_parameter="execution",
        )
        def charge(invoice_id: str, *, execution: ActionExecutionContext):
            received.append(execution)
            return {"invoice_id": invoice_id}

        result = charge.invoke_request(
            context=ActionContext(actor_id="agent", tenant_id="sandbox"),
            arguments={"invoice_id": "SYN-1"},
            idempotency_key="gateway-request-key-001",
        )

        self.assertEqual(result.status, ActionStatus.COMPLETED)
        self.assertEqual(received[0].run_id, result.run_id)
        self.assertEqual(received[0].tenant_id, "sandbox")
        self.assertEqual(received[0].idempotency_key, "gateway-request-key-001")
        self.assertEqual(received[0].attempt, 1)
        with self.assertRaisesRegex(ValueError, "supplied only"):
            charge.invoke(
                context=ActionContext(actor_id="agent", tenant_id="sandbox"),
                invoice_id="SYN-2",
                execution="forged",
            )

    def test_async_action_receives_the_same_trusted_context_contract(self) -> None:
        received: list[ActionExecutionContext] = []

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="message",
            idempotency_key=lambda arguments, context: "async-key-001",
            execution_context_parameter="execution",
        )
        async def notify(message: str, *, execution: ActionExecutionContext):
            await asyncio.sleep(0)
            received.append(execution)
            return {"message": message}

        result = asyncio.run(
            notify.invoke_async(
                context=ActionContext(actor_id="agent", tenant_id="sandbox"),
                message="hello",
            )
        )

        self.assertEqual(result.status, ActionStatus.COMPLETED)
        self.assertEqual(received[0].idempotency_key, "async-key-001")


class StripeSandboxContractTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.ledger = SQLiteActionLedger(Path(self.temporary.name) / "ledger.db")
        self.context = ActionContext(actor_id="payment-agent", tenant_id="sandbox")

    def tearDown(self) -> None:
        self.ledger.close()
        self.temporary.cleanup()

    def build_action(
        self,
        fake: FakePaymentIntents,
        *,
        fault_after_provider_response: bool,
        payment_method: str = "pm_card_visa",
        name: str = "charge_stripe_sandbox",
    ):
        adapter = StripeSandboxPaymentAdapter(
            "sk_test_contract",
            payment_method=payment_method,
            payment_intents=fake,
            ambiguous_error_types=(FakeConnectionError,),
        )

        @trusted_action(
            ledger=self.ledger,
            policy=AllowPolicy(),
            risk="payment",
            name=name,
            idempotency_key=lambda arguments, context: (
                f"stripe:{context.tenant_id}:{arguments['invoice_id']}"
            ),
            execution_context_parameter="execution",
        )
        def charge(
            invoice_id: str,
            amount: int,
            currency: str,
            *,
            execution: ActionExecutionContext,
        ):
            result = adapter.charge(
                invoice_id=invoice_id,
                amount=amount,
                currency=currency,
                execution=execution,
            )
            if fault_after_provider_response:
                raise IndeterminateOutcome("test fault after provider response")
            return result

        return charge, adapter

    def test_ambiguous_payment_retries_once_and_reconciles_from_stripe(self) -> None:
        fake = FakePaymentIntents()
        action, adapter = self.build_action(
            fake,
            fault_after_provider_response=True,
        )
        arguments = {"invoice_id": "SYN-42", "amount": 1250, "currency": "hkd"}

        unknown = action.invoke(context=self.context, **arguments)
        retries = [action.invoke(context=self.context, **arguments) for _ in range(10)]
        completed = action.reconcile_from_provider(
            unknown.run_id,
            probe=StripeSandboxPaymentProbe(adapter),
            principal=reconciler(),
        )

        self.assertEqual(unknown.status, ActionStatus.UNKNOWN)
        self.assertTrue(all(result.duplicate for result in retries))
        self.assertTrue(all(result.run_id == unknown.run_id for result in retries))
        self.assertEqual(completed.status, ActionStatus.COMPLETED)
        self.assertEqual(completed.attempt, 1)
        self.assertEqual(fake.unique_payment_count, 1)
        self.assertEqual(len(fake.requests), 2)
        self.assertNotIn("client_secret", str(completed.value))
        self.assertEqual(
            [event["event_type"] for event in self.ledger.events(unknown.run_id)][-2:],
            ["provider.reconciliation.observed", "run.reconciled"],
        )

    def test_same_key_with_changed_amount_is_blocked_before_stripe(self) -> None:
        fake = FakePaymentIntents()
        action, _ = self.build_action(fake, fault_after_provider_response=False)
        first = action.invoke(
            context=self.context,
            invoice_id="SYN-43",
            amount=1250,
            currency="hkd",
        )

        with self.assertRaises(IdempotencyConflict):
            action.invoke(
                context=self.context,
                invoice_id="SYN-43",
                amount=1300,
                currency="hkd",
            )

        self.assertEqual(first.status, ActionStatus.COMPLETED)
        self.assertEqual(fake.unique_payment_count, 1)

    def test_pending_payment_remains_unknown_after_provider_probe(self) -> None:
        fake = FakePaymentIntents(status="requires_action")
        action, adapter = self.build_action(
            fake,
            fault_after_provider_response=False,
            payment_method="pm_card_authenticationRequired",
            name="charge_stripe_pending",
        )
        unknown = action.invoke(
            context=self.context,
            invoice_id="SYN-PENDING",
            amount=1250,
            currency="hkd",
        )

        pending = action.reconcile_from_provider(
            unknown.run_id,
            probe=StripeSandboxPaymentProbe(adapter),
            principal=reconciler(),
        )

        self.assertEqual(unknown.status, ActionStatus.UNKNOWN)
        self.assertEqual(pending.status, ActionStatus.UNKNOWN)
        self.assertEqual(fake.unique_payment_count, 1)

    def test_connection_failure_is_unknown_and_live_keys_are_refused(self) -> None:
        fake = FakePaymentIntents(fail=FakeConnectionError("private network detail"))
        action, _ = self.build_action(fake, fault_after_provider_response=False)

        result = action.invoke(
            context=self.context,
            invoice_id="SYN-NETWORK",
            amount=1250,
            currency="hkd",
        )

        self.assertEqual(result.status, ActionStatus.UNKNOWN)
        self.assertNotIn("private network detail", result.reason)
        with self.assertRaisesRegex(ValueError, "test-mode key"):
            StripeSandboxPaymentAdapter(
                "sk_live_forbidden",
                payment_intents=FakePaymentIntents(),
            )

    def test_unverifiable_provider_response_is_unknown_not_failed(self) -> None:
        fake = FakePaymentIntents(mismatched_amount=True)
        action, _ = self.build_action(fake, fault_after_provider_response=False)

        result = action.invoke(
            context=self.context,
            invoice_id="SYN-MISMATCH",
            amount=1250,
            currency="hkd",
        )

        self.assertEqual(result.status, ActionStatus.UNKNOWN)
        self.assertEqual(fake.unique_payment_count, 1)

    def test_old_run_refuses_idempotent_post_replay(self) -> None:
        fake = FakePaymentIntents()
        action, adapter = self.build_action(
            fake,
            fault_after_provider_response=True,
        )
        unknown = action.invoke(
            context=self.context,
            invoice_id="SYN-EXPIRED",
            amount=1250,
            currency="hkd",
        )
        old_timestamp = (datetime.now(UTC) - timedelta(hours=24)).isoformat()
        with self.ledger._connection() as connection, connection:
            connection.execute(
                "UPDATE action_runs SET created_at = ? WHERE run_id = ?",
                (old_timestamp, unknown.run_id),
            )

        with self.assertRaisesRegex(ProviderLookupError, "window"):
            action.reconcile_from_provider(
                unknown.run_id,
                probe=StripeSandboxPaymentProbe(adapter),
                principal=reconciler(),
            )

        self.assertEqual(fake.unique_payment_count, 1)
        self.assertEqual(len(fake.requests), 1)
        self.assertEqual(
            self.ledger.get_run(unknown.run_id)["status"],
            ActionStatus.UNKNOWN.value,
        )

    def test_current_official_sdk_surface_can_construct_without_network(self) -> None:
        adapter = StripeSandboxPaymentAdapter("sk_test_placeholder")
        self.assertEqual(adapter.provider_name, "stripe-sandbox")

    def test_provider_lookup_keeps_the_original_positional_arguments_contract(
        self,
    ) -> None:
        lookup = ProviderLookup("run", "action", "tenant", "key", {"invoice": "1"})
        self.assertEqual(lookup.arguments, {"invoice": "1"})
        self.assertIsNone(lookup.created_at)


if __name__ == "__main__":
    unittest.main()
