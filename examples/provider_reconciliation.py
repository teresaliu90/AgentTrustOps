"""Resolve an uncertain synthetic payment without executing it twice."""

from __future__ import annotations

import json
import tempfile
from pathlib import Path

from agenttrustops import (
    ActionContext,
    IndeterminateOutcome,
    PolicyDecision,
    PolicyOutcome,
    ProviderLookup,
    ProviderObservation,
    ProviderOutcome,
    SQLiteActionLedger,
    VerifiedPrincipal,
    trusted_action,
)


class AllowSyntheticPayment:
    def evaluate(self, action_name, arguments, context):
        return PolicyDecision(
            PolicyOutcome.ALLOW,
            "synthetic payment is allowed",
            "example-v1",
        )


class SyntheticPaymentProbe:
    """Stand-in for a provider GET-by-idempotency-key endpoint."""

    name = "synthetic-payments"

    def lookup(self, request: ProviderLookup) -> ProviderObservation:
        assert request.idempotency_key == "payment:demo:INV-42"
        return ProviderObservation(
            ProviderOutcome.COMMITTED,
            "provider found one settled operation for the stable key",
            reference="synthetic_receipt_42",
            safe_result={"receipt_state": "settled"},
        )


def main() -> None:
    with tempfile.TemporaryDirectory(prefix="agenttrustops-provider-") as directory:
        ledger = SQLiteActionLedger(Path(directory) / "actions.db")

        @trusted_action(
            ledger=ledger,
            policy=AllowSyntheticPayment(),
            risk="payment",
            idempotency_key=lambda args, ctx: (
                f"payment:{ctx.tenant_id}:{args['invoice_id']}"
            ),
        )
        def charge_invoice(invoice_id: str, amount: int) -> dict[str, object]:
            # A real adapter raises this only when the provider may have committed
            # but its response cannot be trusted or recovered locally.
            raise IndeterminateOutcome("synthetic response loss")

        uncertain = charge_invoice.invoke(
            context=ActionContext(actor_id="demo-agent", tenant_id="demo"),
            invoice_id="INV-42",
            amount=1250,
        )
        reconciled = charge_invoice.reconcile_from_provider(
            uncertain.run_id,
            probe=SyntheticPaymentProbe(),
            principal=VerifiedPrincipal(
                actor_id="demo-reconciler",
                tenant_id="demo",
                roles=("agenttrustops_reconciler",),
                auth_source="synthetic-example",
            ),
        )
        print(
            json.dumps(
                {
                    "before": uncertain.status.value,
                    "after": reconciled.status.value,
                    "attempts": reconciled.attempt,
                    "result": reconciled.value,
                    "events": [
                        event["event_type"] for event in ledger.events(uncertain.run_id)
                    ],
                },
                indent=2,
            )
        )
        ledger.close()


if __name__ == "__main__":
    main()
