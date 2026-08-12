"""Run a real Stripe Sandbox evaluation and write privacy-safe evidence."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path
from uuid import uuid4

from agenttrustops import (
    ActionContext,
    ActionExecutionContext,
    IdempotencyConflict,
    IndeterminateOutcome,
    PolicyDecision,
    PolicyOutcome,
    SQLiteActionLedger,
    StripeSandboxPaymentAdapter,
    StripeSandboxPaymentProbe,
    VerifiedPrincipal,
    export_audit_bundle,
    generate_ed25519_keypair,
    trusted_action,
    verify_audit_bundle,
    write_audit_bundle,
)


class AllowSandboxPayment:
    def evaluate(self, action_name, arguments, context):
        return PolicyDecision(
            PolicyOutcome.ALLOW,
            "synthetic Stripe Sandbox payment allowed",
            "stripe-sandbox-evaluation-v1",
        )


def build_action(ledger, adapter, *, name, evaluation_id, inject_response_loss=False):
    @trusted_action(
        ledger=ledger,
        policy=AllowSandboxPayment(),
        risk="sandbox-payment",
        name=name,
        idempotency_key=lambda args, ctx: (
            f"stripe-sandbox:{ctx.tenant_id}:{evaluation_id}:{args['invoice_id']}"
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
        if inject_response_loss:
            raise IndeterminateOutcome("evaluation fault after provider response")
        return result

    return charge


def main() -> None:
    parser = argparse.ArgumentParser(
        description="Run AgentTrustOps against real Stripe Sandbox objects"
    )
    parser.add_argument("--output-dir", required=True, type=Path)
    parser.add_argument("--currency", default="hkd")
    parser.add_argument("--amount", default=1250, type=int)
    args = parser.parse_args()

    secret_key = os.environ.get("STRIPE_SECRET_KEY", "")
    if not secret_key:
        raise SystemExit(
            "Set STRIPE_SECRET_KEY to a Stripe test key; never paste it into GitHub."
        )
    output = args.output_dir.resolve()
    output.mkdir(parents=True, exist_ok=False)
    evaluation_id = uuid4().hex[:10]
    ledger = SQLiteActionLedger(output / "action-ledger.db")
    context = ActionContext(actor_id="sandbox-evaluator", tenant_id="sandbox")
    operator = VerifiedPrincipal(
        actor_id="sandbox-reconciler",
        tenant_id="sandbox",
        roles=("agenttrustops_reconciler",),
        auth_source="local-sandbox-evaluation",
    )

    normal_adapter = StripeSandboxPaymentAdapter(secret_key)
    fault_adapter = StripeSandboxPaymentAdapter(secret_key)
    pending_adapter = StripeSandboxPaymentAdapter(
        secret_key,
        payment_method="pm_card_authenticationRequired",
    )
    normal_action = build_action(
        ledger,
        normal_adapter,
        name="stripe_sandbox_normal",
        evaluation_id=evaluation_id,
    )
    fault_action = build_action(
        ledger,
        fault_adapter,
        name="stripe_sandbox_ambiguous",
        evaluation_id=evaluation_id,
        inject_response_loss=True,
    )
    pending_action = build_action(
        ledger,
        pending_adapter,
        name="stripe_sandbox_pending",
        evaluation_id=evaluation_id,
    )

    normal_invoice = f"ATOPS-{evaluation_id}-NORMAL"
    ambiguous_invoice = f"ATOPS-{evaluation_id}-AMBIGUOUS"
    pending_invoice = f"ATOPS-{evaluation_id}-PENDING"
    normal = normal_action.invoke(
        context=context,
        invoice_id=normal_invoice,
        amount=args.amount,
        currency=args.currency,
    )
    unknown = fault_action.invoke(
        context=context,
        invoice_id=ambiguous_invoice,
        amount=args.amount,
        currency=args.currency,
    )
    retries = [
        fault_action.invoke(
            context=context,
            invoice_id=ambiguous_invoice,
            amount=args.amount,
            currency=args.currency,
        )
        for _ in range(10)
    ]
    changed_request_blocked = False
    try:
        fault_action.invoke(
            context=context,
            invoice_id=ambiguous_invoice,
            amount=args.amount + 50,
            currency=args.currency,
        )
    except IdempotencyConflict:
        changed_request_blocked = True
    reconciled = fault_action.reconcile_from_provider(
        unknown.run_id,
        probe=StripeSandboxPaymentProbe(fault_adapter),
        principal=operator,
    )
    pending = pending_action.invoke(
        context=context,
        invoice_id=pending_invoice,
        amount=args.amount,
        currency=args.currency,
    )
    pending_after_probe = pending_action.reconcile_from_provider(
        pending.run_id,
        probe=StripeSandboxPaymentProbe(pending_adapter),
        principal=operator,
    )

    scenarios = {
        "normal_payment_completed": normal.status.value == "completed",
        "fault_became_unknown": unknown.status.value == "unknown",
        "ten_retries_same_run": all(
            item.duplicate and item.run_id == unknown.run_id for item in retries
        ),
        "changed_amount_blocked": changed_request_blocked,
        "provider_reconciliation_completed": (
            reconciled.status.value == "completed" and reconciled.attempt == 1
        ),
        "pending_remained_unknown": pending_after_probe.status.value == "unknown",
    }
    if not all(scenarios.values()):
        raise RuntimeError(f"Stripe Sandbox evaluation failed: {scenarios}")

    private_key = output / ".temporary-audit-private.pem"
    public_key = output / "audit-public-key.pem"
    generate_ed25519_keypair(private_key, public_key)
    try:
        bundle = export_audit_bundle(
            ledger,
            tenant_id="sandbox",
            signing_key_path=private_key,
        )
    finally:
        private_key.unlink(missing_ok=True)
    write_audit_bundle(output / "audit-bundle.json", bundle)
    verification = verify_audit_bundle(
        bundle,
        trusted_public_key_path=public_key,
    )
    result = {
        "schema": "agenttrustops-stripe-sandbox-evaluation-v1",
        "evaluation_id": evaluation_id,
        "provider": "Stripe Sandbox",
        "livemode": False,
        "scenarios": scenarios,
        "run_ids": {
            "normal": normal.run_id,
            "ambiguous": unknown.run_id,
            "pending": pending.run_id,
        },
        "safe_provider_references": {
            "normal": normal.value["payment_intent_id"],
            "ambiguous": reconciled.value["safe_result"]["payment_intent_id"],
        },
        "audit_verification": verification,
        "dashboard_search_values": [
            normal_invoice,
            ambiguous_invoice,
            pending_invoice,
        ],
        "claim_boundary": (
            "Sandbox integration evidence only; not production adoption or real money."
        ),
    }
    (output / "sanitized-result.json").write_text(
        json.dumps(result, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    (output / "verification.txt").write_text(
        json.dumps(verification, indent=2, sort_keys=True) + "\n",
        encoding="utf-8",
    )
    ledger.close()
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
