# Architecture and state machine

AgentTrustOps is deliberately a side-effect governance layer, not an agent planner or workflow
engine. The trusted application resolves identity and evidence, then submits a concrete action.

## Components

1. `TrustedAction` is the intended application route to protected business code. It is not a
   sandbox against trusted host code that retains the underlying Python function.
2. An `ActionPolicy` returns allow, deny, or approval required plus a version and digest.
3. The ledger commits the state transition and its audit event in one transaction.
4. The executor acquires a time-bounded ownership lease and renews it while code runs.
5. The control plane derives actor, tenant, and roles from an `IdentityVerifier`.
6. A server-side `InvocationContextResolver` resolves evidence; request bodies cannot assert
   actor, tenant, or roles.
7. Server-owned provider probes can inspect uncertain outcomes from persisted request identity.
8. Operators inspect privacy-safe durable metrics and reconcile exceptional outcomes.

## State machine

```text
created ── policy deny ─────────────────────────────► denied
   │
   ├── approval required ─► pending_approval ─┬────► rejected
   │                                          ├────► approval_expired
   │                                          └────► approved ─┐
   │                                                          │
   └── policy allow ───────────────────────────────────────────┤
                                                              ▼
                                                         executing
                                                       /     |      \
                                              completed   failed   unknown
                                                                     │
                                               provider/manual reconcile
                                                               /           \
                                                       completed           failed
```

Terminal and uncertain states cannot be executed again. An `unknown` run can only be resolved by
an authenticated same-tenant principal with a reconciliation role. A provider-backed resolution
derives lookup inputs from the persisted run and treats `pending` or lookup failure as still
unknown; it never executes the action again.

## Idempotency contract

The uniqueness key is `(tenant_id, action_name, idempotency_key)`. The ledger also stores a
SHA-256 fingerprint over actor, tenant, normalized roles/evidence, action, risk, canonical
arguments, and trusted resolver metadata.

- same key + same fingerprint: return the existing run;
- same key + different fingerprint: reject with `IdempotencyConflict` / HTTP 409;
- no second policy evaluation, evidence generation, approval request, or side effect occurs.

The business provider should receive its own stable idempotency key as a second boundary.

## Transaction and crash model

State changes and events share a database transaction. PostgreSQL obtains a per-run row lock before
appending an event so concurrent retries cannot fork the hash chain. Execution ownership uses a
compare-and-set transition plus a renewable lease.

If a live process has a definite provider response, it commits completed or failed. If it loses the
response, is cancelled, returns a non-serializable result, or abandons an expired lease, the outcome
is `unknown`. Automatic retry is forbidden because it could duplicate an already committed effect.

## Audit integrity

Each event hash covers run ID, event type, canonical payload, timestamp, and the previous event
hash. The run record atomically anchors the event count and latest hash so tail deletion is also
detectable. This detects modification, removal, and reordering, but it is tamper-evident—not
immutable: a database administrator able to rewrite the whole history and anchor can recompute
them. Export events to an independently controlled WORM or SIEM destination when regulatory
immutability is required.
