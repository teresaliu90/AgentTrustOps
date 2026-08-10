# Operations and incident runbook

## Backend selection

Use SQLite for evaluation and a single service instance. Use PostgreSQL for multiple API or worker
processes. Set `AGENTTRUSTOPS_POSTGRES_DSN` when running the reference server; credentials should
come from a secret manager rather than command-line arguments.

The current schema is created idempotently at startup. Before upgrading, back up the ledger and
read the migration notes. Run:

```bash
agenttrust doctor --ledger actions.db
agenttrust metrics --ledger actions.db --verify-integrity
```

Production authentication can be configured without a static identity file:

```bash
export AGENTTRUSTOPS_OIDC_ISSUER=https://identity.example
export AGENTTRUSTOPS_OIDC_AUDIENCE=agenttrustops-api
export AGENTTRUSTOPS_OIDC_JWKS_URL=https://identity.example/.well-known/jwks.json
agenttrust serve --refunds refunds.db
```

All three OIDC values are required. Static identities and OIDC are mutually exclusive. Insecure
HTTP discovery is rejected unless the explicit local-testing flag is supplied.

## Alerts

Recommended initial alerts:

- `unknown` runs greater than zero for more than the provider lookup SLO;
- `approval_expired` growth or pending approvals older than the business SLA;
- `tool.execution.lease_expired` growth;
- any `agenttrustops_event_chains_invalid` value greater than zero;
- sharp increases in `agenttrustops_duplicate_retries_total` or HTTP idempotency conflicts;
- failed release-gate scenarios on every policy or integration change.

Metrics contain status/event labels and counts only. They do not contain arguments, evidence,
identities, results, tokens, or idempotency keys.

## Unknown-outcome incident

1. Stop automated retries for the affected provider identity.
2. Locate the run and confirm event-chain integrity.
3. Query the provider using its idempotency key or operation reference.
4. Use a same-tenant reconciliation identity to record `completed` or `failed` with a concise note.
5. If the provider cannot determine the result, leave the run unknown and escalate; do not guess.
6. Preserve the redacted audit export and provider evidence under the organization's retention
   policy.

## Backups and retention

Back up the database using backend-native consistent snapshots. Test restore into an isolated
environment and run an integrity scan after restoration. Define separate retention periods for
run metadata, sensitive arguments/results, and independently exported audit events. The reference
schema stores arguments and results; production adapters should tokenize, encrypt, or omit fields
that are unnecessary for decisions.

For each evidence retention interval, export and immediately verify a tenant-scoped signed bundle:

```bash
agenttrust audit-export \
  --ledger actions.db \
  --tenant acme \
  --signing-key /run/secrets/audit-private.pem \
  --output acme-evidence.json
agenttrust audit-verify acme-evidence.json --public-key audit-public.pem
```

Move the verified artifact to independently administered object-lock/WORM storage. The filesystem
signing key is a reference path; production key custody should use a KMS/secret boundary. See
[portable audit evidence](audit-evidence.md).

## Scaling and availability

PostgreSQL execution claims are row-conditional and events are locked per run, so multiple control
plane processes can share one ledger. The protected provider still needs native idempotency. Run
recovery on a schedule, expose readiness separately from liveness, and use graceful shutdown long
enough for in-flight workers to commit or explicitly become unknown.

The included Compose stack is a reproducible local deployment, not a hardened production topology.
Replace demo credentials, terminate TLS at a trusted gateway, use an external PostgreSQL service,
restrict network paths, and export audit events independently.
