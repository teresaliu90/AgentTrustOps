# Positioning and alternatives

AgentTrustOps governs the point where an agent request becomes an external side effect. It is
designed to compose with orchestration, workflow, policy, and guardrail systems—not replace them.

| If you primarily need... | Start with | Add AgentTrustOps when... |
|---|---|---|
| Stateful agent graphs and interrupts | [LangGraph](https://github.com/langchain-ai/langgraph) | a graph node must cross a policy/approval/idempotency boundary before mutating a business system |
| Durable distributed workflows | [Temporal](https://github.com/temporalio/temporal) | agent authority, bound approval, and side-effect audit need a framework-independent record |
| General policy as code | [Open Policy Agent](https://github.com/open-policy-agent/opa) | the decision must be followed by durable approval, execution claims, and reconciliation |
| Model and agent evaluation | [Promptfoo](https://github.com/promptfoo/promptfoo) | a passing evaluation must become an enforceable runtime mutation gate |
| Conversation or trace guardrails | [NeMo Guardrails](https://github.com/NVIDIA-NeMo/Guardrails) or [Invariant](https://github.com/invariantlabs-ai/invariant) | allowed tool calls still require transactional execution and uncertain-outcome handling |

## What this repository uniquely tests

These contracts are exercised in the
[reliability contract](../tests/test_reliability_contract.py),
[runtime tests](../tests/test_runtime.py), and
[provider-reconciliation tests](../tests/test_provider_reconciliation.py):

- same idempotency key and same governed request return one durable run;
- the same key with changed authority, evidence, metadata, or arguments is rejected;
- approval is bound to the request fingerprint, tenant, role, policy version/digest, and expiry;
- an expired execution lease or ambiguous provider response becomes `unknown`, never an automatic
  retry;
- a server-owned provider probe can reconcile an unknown run without accepting the outcome from
  agent arguments;
- state changes and audit events commit atomically on SQLite and PostgreSQL.

## When not to use AgentTrustOps

Do not add it for read-only tools, ordinary chat responses, or workflows already governed by an
equivalent application transaction with verified identity, durable approval, provider-native
idempotency, uncertain-outcome reconciliation, and sufficient audit evidence. It is also not a
security sandbox for untrusted Python code.

The mature projects above have substantially larger communities, operational histories, and
integration ecosystems. AgentTrustOps is currently an early-stage, single-maintainer project with
no verified production adopters. Evaluate the contract and boundaries before choosing it.
