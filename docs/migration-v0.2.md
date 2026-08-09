# Migrating from v0.1 to v0.2

SQLite files are migrated in place to schema version 2 and retain existing runs/events. Back up the
file before opening it with v0.2.

## Breaking API changes

- `approve` and `reject` now require `principal=VerifiedPrincipal(...)`; arbitrary approver strings
  are rejected.
- `reconcile` now requires a verified same-tenant principal with the configured reconciliation
  role.
- Sensitive audit fields are redacted by default. A same-tenant principal with
  `agenttrustops_auditor` is required for the full view.
- Reusing an idempotency key with changed actor, roles, evidence, risk, or arguments raises
  `IdempotencyConflict` instead of silently returning the first answer.
- Integrity reports now identify `sha256_event_chain_sqlite` and correctly state that SQLite is
  tamper-evident rather than immutable.

## Operational steps

1. Stop writers and back up the v0.1 database.
2. Install v0.2 and open the database once in a staging environment.
3. Run `agenttrust doctor --ledger <path>` and inspect any invalid chain.
4. Update approval and reconciliation callers to use identities derived from a trusted adapter.
5. Exercise retries with both identical and deliberately changed inputs.
6. Deploy and alert on unknown, expired approval, lease expiry, and integrity metrics.
