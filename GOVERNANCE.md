# Governance

AgentTrustOps is currently maintainer-led. The maintainer is responsible for release signing, security response, compatibility decisions, and the final merge decision for changes to trusted execution boundaries.

## How decisions are made

- Bug fixes and documentation improvements use normal pull-request review.
- Changes to ledger integrity, identity, approval, idempotency, or reconciliation require tests that exercise the relevant failure boundary.
- Breaking API or storage changes require a migration note and a public discussion before release.
- Product direction is discussed in GitHub issues. Decisions record the user problem, rejected alternatives, safety impact, and rollout or migration plan.

## Growing beyond one maintainer

A contributor may be invited as a reviewer after multiple substantive, safe contributions. Commit access requires sustained participation and explicit acceptance of the Code of Conduct and security process. No reviewer approves their own sensitive-boundary change.

The project will document changes to maintainership here and in `CODEOWNERS`. Until the reviewer group grows, the single-maintainer bus factor is an explicit project risk rather than a hidden claim of community governance.
