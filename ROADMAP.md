# Roadmap

## Shipped in v0.3

- portable, redacted audit bundles with source-chain refusal, SHA-256 digest, optional Ed25519
  signing, pinned-key offline verification, and non-overwriting CLI workflow;
- production OIDC/JWKS authentication selectable directly from the reference-server CLI;
- one-command, no-key, persisted demo with machine-readable output.

## Shipped after v0.3

- server-owned provider reconciliation contract with persisted lookup inputs, three-state
  observations, authenticated HTTP wiring, privacy-safe audit events, and a synthetic example.

## Shipped in v0.2

- strict idempotency fingerprints, transactional event chains, execution leases, unknown outcomes,
  reconciliation, and verified bound approvals;
- authenticated API and browser console, privacy-safe audit/metrics, recovery and runbook;
- SQLite/PostgreSQL, Docker Compose, LangGraph, OpenAI Agents, FastMCP, OPA, release action, real
  backend contracts, package artifacts, SBOM, attestations, GHCR, CodeQL, and OpenSSF Scorecard.

## Next milestones

### Reliability and independent review

- publish measured PostgreSQL contention, recovery, and tail-latency results on disclosed
  infrastructure;
- complete an independent security review with a public remediation record;
- test backup/restore and document explicit RPO/RTO boundaries.

### Production operations

- KMS signing adapter plus append-only/WORM exporter and checkpointed scheduled exports;
- schema migration planning/rollback tooling and documented zero-downtime compatibility window.

### Ecosystem depth

- production provider kits for payments, messaging, deployments, and database mutations;
- workload-identity and mTLS examples plus provider-specific OIDC claim recipes;
- maintained OpenTelemetry/SIEM export.

Roadmap items are proposals, not promises. Security and correctness defects take priority over
feature breadth. Certification, HA, and provider compatibility are claimed only with independently
verifiable evidence.
