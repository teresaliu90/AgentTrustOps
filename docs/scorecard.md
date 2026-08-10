# Unified GitHub competitiveness scorecard

Snapshot: 2026-08-10. This self-audit deliberately includes engineering, GitHub release/community
readiness, and real external adoption. It is not an independent certification and does not convert
stars, tests, or maintainer usage into production customers.

| Dimension | Weight | Score | Verifiable evidence and remaining limit |
|---|---:|---:|---|
| User pain and product completeness | 12% | 9.2 | invoke → policy → approval → execute → unknown → reconcile → audit; operator console and incident runbook |
| Focused differentiation | 10% | 8.8 | fingerprint conflicts, bound approvals, leases, no blind retry, privacy-safe event chain; deliberately narrower than orchestration suites |
| Core correctness and reliability | 18% | 9.3 | atomic state/events, chain anchors, ownership/heartbeats, migrations, threaded/async/real-PostgreSQL contracts; no distributed exactly-once claim |
| Security and privacy | 12% | 8.7 | OIDC/JWKS, tenant/role separation, CSP console, CodeQL, dependency review, OpenSSF Scorecard, fail-closed OPA; no independent audit yet |
| Deployment and operator UX | 10% | 8.7 | SDK, CLI, FastAPI, SQLite/PostgreSQL, Docker/Compose, metrics, browser operations console; no hosted managed service or regional HA reference |
| Ecosystem integrations | 10% | 8.7 | tested LangGraph, OpenAI Agents SDK 0.19, FastMCP 1.29, OPA Data API 1.17, and generic workflow-engine contract; connector catalog is still small |
| Testing and performance evidence | 10% | 8.8 | 64 tests, real PostgreSQL/OPA CI, package/action/container smoke, unsafe release gate, reproducible 1,000+1,000 SQLite probe; no independent load lab or SLO |
| Release and supply chain | 8% | 9.0 | composite GitHub Action, wheel/sdist, checksums, CycloneDX SBOM, attestations, GHCR provenance, manual PyPI Trusted Publishing path |
| OSS community process | 5% | 8.0 | issue forms, adopter consent policy, governance/support/security docs, citation, Code of Conduct, contributor path; single-maintainer bus factor remains |
| Verified external adoption | 5% | 1.0 | no named or privately verified production adopter; one star is interest, not adoption, and the adopter registry is intentionally empty |

Weighted result after the `v0.2.0` Release and GHCR jobs are green: **8.49/10, reported as 8.5/10**.
Until those external artifacts resolve publicly, the release/supply-chain row must be discounted and
the result remains below 8.5.

## Why the adoption score stays low

Actual adoption is included, scored separately, and cannot be fixed by repository code. The project
will raise it only with consented evidence in `ADOPTERS.md`: a named deployment, a privately verified
anonymous deployment, or a design-partner pilot with version/backend/integration and volume band.
Maintainer demos, CI runs, downloads, clones, and synthetic workloads do not qualify.

## Competitive interpretation

An 8.5 here means the repository is unusually complete and adoptable for a new, narrow control-plane
project—not that it has the ecosystem power of OPA, Temporal, LangGraph, or established guardrail and
observability vendors. AgentTrustOps has a strong technical wedge where those categories overlap:
one risky side effect governed consistently across identity, policy, human approval, retry, crash,
reconciliation, and redacted audit. The adapters make it complementary to incumbent ecosystems.

## What blocks a defensible 9.0

- at least two independently verifiable design-partner or production deployments;
- an independent security review and published remediation record;
- measured PostgreSQL contention, recovery, and tail-latency results on disclosed infrastructure;
- a regional HA reference deployment and tested restore/failover procedure;
- more external contributors and a second trusted maintainer;
- provider-certified side-effect connectors or a broader maintained integration catalog.
