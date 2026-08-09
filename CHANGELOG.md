# Changelog

All notable changes are documented here. The project follows semantic versioning while pre-1.0
minor releases may contain clearly documented breaking changes.

## [Unreleased]

## [0.2.0] - 2026-08-08

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
