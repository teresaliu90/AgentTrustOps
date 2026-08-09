# Roadmap

## Shipped in v0.2

- strict idempotency fingerprints, transactional event chain, execution leases, bound approvals;
- authenticated control-plane API and privacy-safe metrics/audit;
- SQLite and PostgreSQL backends, Docker Compose, LangGraph adapter, release gate, and CI contracts.

## Next candidates

- workload-identity and mTLS examples plus provider-specific OIDC claim recipes;
- transactional outbox exporters for OpenTelemetry/SIEM/WORM storage;
- policy adapters for OPA and Cedar with signed bundle digests;
- a minimal approval and reconciliation web UI;
- schema migration tooling with offline planning and rollback guidance;
- provider adapter contracts for payment, messaging, deployment, and database mutation APIs;
- external design partners, anonymized adoption evidence, SLO measurements, and independent security
  review.

Roadmap items are proposals, not promises. Security and correctness defects take priority over
feature breadth. External adoption and certification will only be claimed with verifiable evidence.
