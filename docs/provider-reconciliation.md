# Provider-backed reconciliation

An action can reach `unknown` when a payment, deployment, message, or other provider may have
accepted the request but the worker did not receive a definitive response. Retrying at that point
can duplicate the side effect. Guessing that it succeeded can silently lose work.

AgentTrustOps can now ask a server-owned provider probe for an authoritative conclusion. The caller
supplies only the run ID. The lookup key, tenant, action, and arguments come from the persisted
governed request, so an agent cannot forge a provider result through the HTTP body.

## Outcome contract

| Provider outcome | Run transition | Meaning |
|---|---|---|
| `committed` | `unknown → completed` | The provider authoritatively found the operation |
| `not_committed` | `unknown → failed` | The provider authoritatively confirmed no operation committed |
| `pending` | remains `unknown` | The provider cannot yet make a definitive claim |
| lookup exception | remains `unknown` | Availability failure is not evidence of success or failure |

Every accepted lookup appends `provider.reconciliation.observed`. A definitive result and its
`run.reconciled` event commit in the same database transaction, so concurrent reconcilers cannot
record contradictory winning conclusions. None of these paths executes the protected action again.

## Implement a probe

```python
from agenttrustops import (
    ProviderLookup,
    ProviderLookupError,
    ProviderObservation,
    ProviderOutcome,
)


class PaymentProbe:
    name = "payment-sandbox"

    def lookup(self, request: ProviderLookup) -> ProviderObservation:
        try:
            operation = payment_client.get_by_idempotency_key(request.idempotency_key)
        except TimeoutError as error:
            raise ProviderLookupError("payment lookup unavailable") from error

        if operation is None:
            return ProviderObservation(
                ProviderOutcome.NOT_COMMITTED,
                "no operation exists for the stable key",
            )
        if operation.pending:
            return ProviderObservation(
                ProviderOutcome.PENDING,
                "provider operation is not final",
                reference=operation.privacy_safe_reference,
            )
        return ProviderObservation(
            ProviderOutcome.COMMITTED,
            "provider operation is final",
            reference=operation.privacy_safe_reference,
            safe_result={"receipt_state": "settled"},
        )
```

The probe must be deterministic for a stable key and must query an authoritative provider API or
system of record. Absence is `not_committed` only when the provider guarantees that its lookup is
complete and strongly consistent enough for that conclusion. Otherwise return `pending`.

## SDK and HTTP wiring

Call the SDK directly with a verified, same-tenant reconciliation principal:

```python
result = charge_invoice.reconcile_from_provider(
    run_id,
    probe=PaymentProbe(),
    principal=verified_reconciler,
)
```

Or register probes by action name when constructing the control plane:

```python
app = create_app(
    registry,
    identity_verifier,
    provider_probes={"charge_invoice": PaymentProbe()},
)
```

An authenticated reconciler can then call:

```bash
curl -sS -X POST \
  "https://agenttrustops.example/v1/runs/$RUN_ID/reconcile-from-provider" \
  -H "Authorization: Bearer $RECONCILER_TOKEN"
```

The endpoint accepts no outcome, result, key, or arguments. Missing probes return 409. Provider
availability failures return a generic 502 and deliberately leave the run `unknown`.

Run the dependency-free synthetic example from a checkout:

```bash
python examples/provider_reconciliation.py
```

## Security and privacy checklist

- Keep provider credentials in the server-owned adapter, never in action arguments or prompts.
- Give the probe read-only lookup authority where the provider permits it.
- Forward the original stable idempotency key to the provider during execution and lookup.
- Put only reviewed, non-secret values in `summary`, `reference`, and `safe_result`; they are stored.
- Never copy a raw provider response into the ledger.
- Rate-limit and monitor repeated `pending` lookups; define a provider-specific reconciliation SLO.
- Preserve manual reconciliation for exceptional investigations, but require evidence in the note.

This contract reduces blind operational judgment. It does not claim distributed exactly-once
delivery and cannot compensate for a provider that lacks authoritative lookup or stable
idempotency semantics.
