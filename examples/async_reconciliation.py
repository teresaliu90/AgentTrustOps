"""Run the crash-safe unknown -> reconciliation flow without a provider."""

from __future__ import annotations

import asyncio
import tempfile
from pathlib import Path

from agenttrustops import (
    ActionContext,
    IndeterminateOutcome,
    PolicyDecision,
    PolicyOutcome,
    SQLiteActionLedger,
    trusted_action,
)


class AllowPolicy:
    def evaluate(self, action_name, arguments, context):
        return PolicyDecision(
            outcome=PolicyOutcome.ALLOW,
            reason="Synthetic demo action allowed",
            policy_version="demo-v1",
        )


async def main() -> None:
    with tempfile.TemporaryDirectory() as directory:
        ledger = SQLiteActionLedger(Path(directory) / "ledger.db")
        provider_calls = 0

        @trusted_action(
            ledger=ledger,
            policy=AllowPolicy(),
            risk="financial",
            idempotency_key=lambda args, ctx: (
                f"charge:{ctx.tenant_id}:{args['order_id']}"
            ),
        )
        async def charge(order_id: str, amount: int) -> dict[str, object]:
            nonlocal provider_calls
            provider_calls += 1
            raise IndeterminateOutcome("provider response was lost")

        context = ActionContext(actor_id="demo-agent", tenant_id="demo")
        unknown = await charge.invoke_async(
            context=context, order_id="O-001", amount=800
        )
        retry = await charge.invoke_async(context=context, order_id="O-001", amount=800)
        completed = charge.reconcile(
            unknown.run_id,
            outcome="completed",
            operator_id="demo-reconciliation-worker",
            note="Synthetic provider lookup confirms the charge",
            result={"provider_id": "provider-001", "amount": 800},
        )

        print(f"Initial result: {unknown.status.value}")
        print(f"Retry result: {retry.status.value} (duplicate={retry.duplicate})")
        print(f"Reconciled result: {completed.status.value}")
        print(f"Provider calls: {provider_calls}")
        print("Expected: unknown -> unknown -> completed, with one provider call")


if __name__ == "__main__":
    asyncio.run(main())
