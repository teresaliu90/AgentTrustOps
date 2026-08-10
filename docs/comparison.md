# Competitive position: own the side-effect commit point

Snapshot: 2026-08-10. AgentTrustOps competes for a narrow responsibility: enforcing the transaction
between agent intent and an irreversible or costly business mutation. It normally composes with,
rather than replaces, the projects below.

## Category map

| Project | Demonstrated center of gravity | Where AgentTrustOps plugs in | Source |
|---|---|---|---|
| LangGraph | Low-level orchestration for long-running, stateful agents | Put the governed commit boundary inside graph/tool nodes | [official repository](https://github.com/langchain-ai/langgraph) |
| Temporal | Durable execution, retries, timers, and distributed workflow state | Let the workflow schedule work while AgentTrustOps owns approval, request identity, and side-effect evidence | [official repository](https://github.com/temporalio/temporal) |
| Open Policy Agent | General policy-as-code and a mature policy ecosystem | Use OPA for `allow`/`approval_required` while AgentTrustOps persists and enforces the remaining lifecycle | [official repository](https://github.com/open-policy-agent/opa) |
| Promptfoo | Evaluation and red teaming for LLM applications | Run broad model/security tests, then use AgentTrustOps as the production mutation gate | [official repository](https://github.com/promptfoo/promptfoo) |
| NeMo Guardrails | Programmable guardrails for LLM application behavior | Keep content/conversation controls separate from the durable side-effect transaction | [official repository](https://github.com/NVIDIA-NeMo/Guardrails) |
| Invariant Guardrails | Rule-based agent trace and MCP/LLM proxy guardrailing | Add durable claims, approval binding, crash ambiguity, reconciliation, and portable evidence | [official repository](https://github.com/invariantlabs-ai/invariant) |
| mcp-agent | MCP-native agent construction, examples, and durable workflow integrations | Register governed MCP tools while authority stays outside model arguments | [official repository](https://github.com/lastmile-ai/mcp-agent) |

The established projects have much larger communities and broader scopes. AgentTrustOps does not
compete by duplicating them. Its wedge is the cross-layer invariant none of those categories alone
owns: **the same risky request, verified authority, policy digest, human decision, execution claim,
uncertain outcome, reconciliation, and redacted evidence remain one durable record.**

## GitHub community reality

These counts came from the GitHub repository API on 2026-08-10. Stars and forks are not production
adoption, but they are useful evidence of reach, review surface, and contributor gravity.

| Repository | Stars | Forks | Honest interpretation |
|---|---:|---:|---|
| [LangGraph](https://github.com/langchain-ai/langgraph) | 39,341 | 6,609 | Agent-runtime reach AgentTrustOps cannot currently match |
| [Temporal](https://github.com/temporalio/temporal) | 22,204 | 1,800 | Mature durable-execution community and operations depth |
| [OPA](https://github.com/open-policy-agent/opa) | 12,086 | 1,648 | Mature policy ecosystem, adopters, governance, and security history |
| [mcp-agent](https://github.com/lastmile-ai/mcp-agent) | 8,495 | 877 | Strong MCP developer funnel and maintained examples |
| [Invariant](https://github.com/invariantlabs-ai/invariant) | 441 | 47 | Established specialist agent-guardrail reach |
| [AgentTrustOps](https://github.com/teresaliu90/AgentTrustOps) | 1 | 0 | Technically credible early project; no verified production adopter |

AgentTrustOps is therefore **not yet ecosystem-competitive** on reach. It is product-competitive on
one high-value boundary: the side-effect lifecycle that begins after an agent proposes a call and
does not end until an uncertain provider result is reconciled and portable evidence is verified.
The adoption plan is designed to test whether that wedge earns a community rather than assuming it
will.

## Executable differentiators

These claims are linked to tests or runnable commands rather than screenshots:

1. Same key + same full request returns the stored public answer without new evidence-chain events;
   same key + changed actor, tenant, roles, evidence, risk, arguments, or metadata is a hard conflict.
2. Approval binds verified principal, tenant, role, request fingerprint, policy version/digest,
   expiry, note, and separation of duties.
3. Transactional execution ownership plus heartbeats makes abandoned workers `unknown`; automatic
   execution is suppressed until an authenticated operator reconciles the provider result.
4. State and event append commit atomically on SQLite and PostgreSQL, with per-run count/head-anchored
   SHA-256 chains.
5. Default HTTP/audit views omit credentials, idempotency keys, raw identities, arguments, evidence,
   results, and sensitive event fields.
6. Redacted audit bundles refuse invalid source chains, support Ed25519 signing, and verify offline
   with a separately pinned public key.
7. OIDC/JWKS, static-demo auth, OPA, LangGraph, OpenAI Agents, and FastMCP adapters keep verified
   authority outside model-controlled arguments.
8. Safe and deliberately unsafe policy fixtures run as a reusable GitHub release gate with no model,
   API key, network dependency, or nondeterministic judge.

Run the focused evidence locally:

```bash
python -m unittest \
  tests.test_reliability_contract \
  tests.test_audit_bundle \
  tests.test_auth_and_cli \
  tests.test_integrations -v
```

## Where competitors are still stronger

- Temporal has a mature multi-language durable-execution ecosystem and operational platform.
- OPA has CNCF governance, broad integrations, public adopters, and independent security history.
- LangGraph and mcp-agent have far larger agent-developer reach and example ecosystems.
- Promptfoo, NeMo Guardrails, and Invariant cover much broader evaluation/content/trace threat
  surfaces.

AgentTrustOps currently has no verified production adopter, managed cloud, regional HA evidence,
provider-certified connector, independent security audit, or multi-maintainer governance. Those
gaps are not converted into points through repository polish. The [adoption ladder](adoption-playbook.md)
and [roadmap](../ROADMAP.md) state what evidence closes them.
