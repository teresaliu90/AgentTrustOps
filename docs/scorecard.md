# Engineering and product scorecard

This rubric measures open-source product and engineering readiness, not GitHub popularity. It is a
self-audit with reproducible repository evidence, not an independent certification.

| Dimension | Weight | Score | Repository evidence |
|---|---:|---:|---|
| User pain and product completeness | 15% | 9.0 | invoke → policy → approval → execute → unknown → reconcile → audit lifecycle; concrete incident patterns |
| Focused differentiation | 15% | 8.8 | request-fingerprint conflicts, bound approvals, leases, no blind retry, privacy-safe evidence chain |
| Core correctness and reliability | 20% | 9.2 | atomic state/events, canonical fingerprints, execution ownership, heartbeats, migration and crash tests |
| Security and privacy | 10% | 8.6 | OIDC/JWKS verifier, strict tenant/role binding, separation of duties, redacted defaults, CodeQL |
| Runnable deployment | 10% | 8.6 | SDK, FastAPI control plane, SQLite, PostgreSQL, Dockerfile, Compose, health and metrics |
| Testing and release evidence | 10% | 9.2 | 55 deterministic tests, threaded/async concurrency, real PostgreSQL CI contract, unsafe-policy gate |
| Documentation and developer experience | 10% | 8.8 | five-minute paths, API/operations/architecture/migration/integration docs, typed wheel and CLI |
| OSS and supply-chain governance | 5% | 8.5 | issue forms, PR checklist, CodeQL, Dependabot, dependency audit, package smoke, provenance workflow |
| External adoption evidence | 5% | 3.0 | no fabricated users, design partners, independent security review, or external contributor history |

Weighted result: **8.6/10**.

## Why it is above 8.5

The score comes from executable breadth around one painful production boundary rather than from a
large feature count. The same failure contract is exercised through the SDK, authenticated API,
SQLite, PostgreSQL, sync/async tools, CLI operations, and LangGraph adapter. The highest-weight
correctness claims have explicit failure-path tests.

## Why it is not a 9+

There is no measured external production use, hosted approval UI, independent security audit,
provider-certified connector, regional HA reference, or published SLO. Those gaps cannot be closed
honestly by adding synthetic claims. External adoption remains separately visible even though its
weight does not erase the engineering readiness of a new repository.

## Competitive interpretation

AgentTrustOps has a significant technical advantage only in its chosen niche: governance of a
single risky side effect across retries, approval, crashes, and audit. LangGraph and Temporal remain
stronger orchestration systems; OPA remains a stronger general policy ecosystem; Promptfoo remains
a broader evaluation system; observability vendors remain stronger trace UIs. The competitive
claim is composable enforcement depth, not replacement of those categories.
