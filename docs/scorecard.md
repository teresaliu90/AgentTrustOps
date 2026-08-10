# Unified GitHub competitiveness scorecard

Snapshot: 2026-08-10. This maintainer self-audit includes engineering, product clarity, release and
community readiness, and independently verifiable external adoption. It is not a certification.
Every score has an explicit limit; stars, tests, downloads, and maintainer usage never become
production-adoption points.

| Dimension | Weight | Score | Verifiable evidence and current limit |
|---|---:|---:|---|
| User pain and product completeness | 12% | 9.3 | intent → policy → approval → execute → unknown → reconcile → signed redacted evidence; no managed service |
| Focused differentiation | 10% | 9.3 | side-effect commit-point category, changed-request conflicts, bound authority, crash ambiguity, portable proof; narrower than full orchestration/security suites |
| Core correctness and reliability | 18% | 9.4 | atomic state/events, chain anchors, ownership/heartbeats, migrations, threaded/async/real-PostgreSQL contracts; no distributed exactly-once claim |
| Security and privacy | 12% | 9.1 | OIDC/JWKS, tenant/role separation, fail-closed OPA, CodeQL, dependency review, secret scanning, redacted signed export; no independent audit/KMS adapter |
| Deployment and operator UX | 10% | 9.0 | 60-second wheel demo, SDK/CLI/API/UI, SQLite/PostgreSQL, Docker, OIDC startup, metrics/recovery; no regional HA evidence |
| Ecosystem integrations | 10% | 8.8 | tested LangGraph, OpenAI Agents, FastMCP, OPA and reusable GitHub Action; small connector catalog |
| Testing and performance evidence | 10% | 9.1 | 74 tests, real PostgreSQL/OPA CI, package/container/action smoke, tamper/signature negatives, reproducible benchmark; no independent load lab/SLO |
| Release and supply chain | 8% | 9.2 | [v0.3.0](https://github.com/teresaliu90/AgentTrustOps/releases/tag/v0.3.0) wheel/sdist, checksums, CycloneDX SBOM, attestations and public GHCR provenance; PyPI is not claimed live |
| OSS community process | 5% | 8.4 | issue forms, Discussions, adoption ladder/funnel, governance/support/security, citation, Code of Conduct; single-maintainer bus factor |
| Verified external adoption | 5% | 1.0 | 1 star, 0 forks, and no named or privately verified production adopter at snapshot; repository activity is not adoption |

Weighted calculation:

```text
0.12×9.3 + 0.10×9.3 + 0.18×9.4 + 0.12×9.1 + 0.10×9.0
+ 0.10×8.8 + 0.10×9.1 + 0.08×9.2 + 0.05×8.4 + 0.05×1.0
= 8.726 → 8.7/10
```

## Verified v0.3.0 release evidence

- [main CI](https://github.com/teresaliu90/AgentTrustOps/actions/runs/31365351009) and
  [tag CI](https://github.com/teresaliu90/AgentTrustOps/actions/runs/31365354010) passed, including
  Python 3.11–3.13, real PostgreSQL, real OPA, package, container, dependency audit, and reusable
  action jobs;
- [CodeQL](https://github.com/teresaliu90/AgentTrustOps/actions/runs/31365350956),
  [OpenSSF Scorecard](https://github.com/teresaliu90/AgentTrustOps/actions/runs/31365351010), and the
  [release workflow](https://github.com/teresaliu90/AgentTrustOps/actions/runs/31365354005) passed;
- the public wheel was anonymously downloaded, installed without repository access, and completed
  the persisted demo; its Release digest is
  `sha256:77fc2cc1653124949a31d53da22d10215a6ca5d9508e5849d638461ffecbae86`;
- the public `ghcr.io/teresaliu90/agenttrustops:v0.3.0` OCI index was anonymously retrievable with
  digest `sha256:c0c6be36a9b3ad7390b7fedcbaca5d0f7522596290caab742cdd0dfdcbd31a7f`;
- the [v0.3 design-partner challenge](https://github.com/teresaliu90/AgentTrustOps/discussions/3)
  is public, while adoption remains scored at 1.0 until an independent report meets the evidence
  policy.

The result is **8.7/10 with real adoption included at 1.0/10**, not a score obtained by excluding
the weakest category. It means the repository is technically competitive and unusually complete
for an early narrow control-plane project. It does not mean ecosystem parity with OPA, Temporal,
LangGraph, or established guardrail projects.

## Why adoption cannot be “implemented” to 10

A maintainer can reduce adoption friction but cannot truthfully create independent organizations,
production continuity, external maintainers, or case studies. The
[verifiable adoption ladder](adoption-playbook.md) requires 20 production organizations, 10 million
cumulative governed runs, externally maintained integrations, recurring community releases, and
support evidence for 10/10. Until that evidence exists, this row stays low.

What v0.3 does change is the conversion surface: no-key 60-second proof, a 20-minute independent
challenge, two-hour integration boundary, two-week pilot checklist, consented evidence packet,
signed portable audit proof, and an explicit report form. These are legitimate leading indicators,
not retroactive adoption claims.

## What blocks 9.0 overall

- at least three verified pilots and one 30-day production deployment;
- independent security review and published remediation record;
- PostgreSQL contention/recovery/tail-latency report on disclosed infrastructure;
- tested backup/restore and regional HA evidence with RPO/RTO;
- provider contract kits and one externally maintained integration;
- second trusted maintainer and recurring external contributions.

Crossing 9.0 should come from independent proof, not another maintainer-authored feature batch.
