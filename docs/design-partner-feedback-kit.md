# Design-partner feedback kit

This kit gathers independent usability evidence without requesting company data or claiming a
pilot before one exists.

## Suitable reviewers

Engineers who have built agent tools, approval workflows, payment/messaging/deployment adapters,
durable workflows, policy systems, or AI platform controls. Three independent runs are more useful
than a large number of passive stars.

## Invitation

> I maintain AgentTrustOps, an Apache-2.0 side-effect control plane for AI agents. It prevents
> changed retries, binds high-risk approval to verified identity/policy, and pauses uncertain
> provider outcomes for reconciliation. Could you spend 20–30 minutes running the synthetic Docker
> demo and tell me what would block a real integration? It uses no model, API key, company data, or
> sales process. Anonymous feedback is welcome.

For reviewers with a Stripe test account, use the
[Stripe Sandbox invitation and evidence runner](../case-studies/stripe-sandbox-invitation.md) after
the no-key task. Keep maintainer-only validation and independent evaluation in separate reports.

## Unassisted ten-minute task

1. Install the release wheel and complete `agenttrust demo` using only the README.
2. Replay the printed run and explain same-request replay versus changed-request conflict.
3. Create an audit keypair, export the printed ledger, and verify it with the pinned public key.
4. Tamper with a copy of the JSON and confirm verification fails.
5. Explain what source `chain_verified`, the export signature, and WORM storage each do—and do not—prove.

Do not coach the reviewer during the first ten minutes. Installation failures, unclear terms, and
missing navigation are primary findings.

## Interview questions

1. Which real side effect would you govern first?
2. Is the boundary between AgentTrustOps and LangGraph/Temporal/OPA clear?
3. Which identity, evidence, provider-idempotency, or reconciliation integration is missing?
4. Which response or audit field is too sensitive or insufficient?
5. What would prevent a two-week internal proof of concept?
6. Would you use the SDK, the HTTP control plane, or neither? Why?

## Record

Store only consented, minimally identifying data:

| Field | Value |
|---|---|
| Reviewer ID | anonymous code |
| Relevant experience | broad category only |
| Environment | OS, Python/Docker version |
| Time to first successful invoke | minutes or blocked |
| Completed retry/conflict/approval/audit tasks | yes/no per task |
| Highest-impact blocker | concise paraphrase |
| Follow-up accepted | yes/no |
| Permission to publish anonymized finding | explicit yes/no |

Never commit names, contact details, employer systems, credentials, private policy, or provider data.
Convert actionable findings into synthetic GitHub issues. Claim a design partner or pilot only with
explicit permission and verifiable participation.

## Initial success threshold

- three independent environments complete the persisted demo within five minutes;
- all three correctly explain same-key replay versus changed-request conflict;
- all three independently verify a signed export and reject a modified copy;
- at least two identify a plausible integration and no critical trust-boundary misunderstanding;
- every blocker is either fixed, documented, or deliberately accepted with rationale.
