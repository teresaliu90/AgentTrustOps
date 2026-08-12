# Changelog

All notable changes are documented here. The project follows semantic versioning while pre-1.0
minor releases may contain clearly documented breaking changes.

## [Unreleased]

### Added

- server-owned provider probes that atomically resolve unknown outcomes from persisted governed
  requests;
- explicit `committed`, `not_committed`, and `pending` provider observations, with privacy-reviewed
  audit evidence and fail-safe handling of provider outages;
- authenticated provider-reconciliation API and console control, contract tests, documentation,
  and executable synthetic payment example.

## [0.3.0] - 2026-08-10

### Added

- portable redacted audit bundles with source-chain verification, canonical SHA-256 digests,
  optional Ed25519 signatures, pinned-key offline verification, and non-overwriting CLI commands;
- direct OIDC/JWKS configuration for the reference server through CLI flags or environment;
- machine-readable output for the persisted no-key demo;
- adoption ladder, product conversion funnel, evidence-linked category comparison, and redesigned
  GitHub first-screen narrative.

### Changed

- the README leads with a 60-second wheel-to-proof path and the side-effect commit-point wedge;
- the roadmap distinguishes already shipped OPA/UI/integration work from external proof milestones;
- production operations document signed export and OIDC startup boundaries.

### Security

- audit exports are always redacted, refuse broken source chains, and can be verified against a
  separately distributed trusted public key;
- static-demo identities and OIDC are mutually exclusive, and partial authentication configuration
  fails closed.

## [0.2.0] - 2026-08-10

### Added

- request fingerprints and hard idempotency conflicts;
- atomic run/event transitions and SHA-256 per-run event chains with count/head anchors;
- execution ownership leases, automatic heartbeats, crash recovery, and explicit reconciliation;
- verified, tenant-scoped, role-bound, expiring approvals with separation of duties;
- redacted-by-default audit and public action responses;
- authenticated FastAPI control plane, approval inbox, health/readiness, recovery, and metrics;
- asymmetric OIDC/JWKS verification with strict issuer, audience, expiry, algorithm, and claim checks;
- PostgreSQL backend, Docker image, Compose deployment, and database contract CI;
- dependency-free LangGraph adapter;
- OpenAI Agents SDK, MCP host, and fail-closed OPA adapters;
- built-in authenticated operations console for approvals, resume, and reconciliation;
- reusable GitHub release-gate action and adoption/design-partner intake;
- reproducible SQLite performance probe and CI benchmark artifact;
- GitHub Release wheels, checksums, CycloneDX SBOM, attestations, and GHCR publishing workflow;
- OpenSSF Scorecard publication and pull-request dependency review;
- package build verification, dependency audit, CodeQL, and expanded concurrency/API tests.

### Changed

- approval and reconciliation APIs require `VerifiedPrincipal`;
- unknown provider outcomes can never be automatically retried;
- project status moves from v0.1 early-alpha proof to a v0.2 beta-quality foundation.

### Fixed

- an idempotency key can no longer replay an old result for changed arguments or actor;
- state changes can no longer commit without their audit event;
- abandoned `executing` runs no longer remain stuck indefinitely;
- default audit output no longer exposes raw arguments, evidence, result, actor, or key.

## [0.1.0] - 2026-08-07

- Initial policy, approval, SQLite idempotency, replay, async, reconciliation, and release-gate
  reference implementation.
