# Honest comparison and positioning

AgentTrustOps competes for a narrow responsibility: runtime governance of irreversible or costly
agent side effects. It should usually be composed with, not selected instead of, the tools below.

| Project category | What it does best | Gap AgentTrustOps addresses | What AgentTrustOps does not replace |
|---|---|---|---|
| LangGraph | Agent state graphs, interrupts, resumable orchestration | Request-fingerprint conflicts, bound approval identity, execution leases, side-effect audit | Graph design and model/tool orchestration |
| Temporal | Durable workflows, retries, timers, distributed scheduling | Agent-specific policy decision, evidence binding, privacy-safe action audit | General workflow infrastructure |
| OPA | General policy-as-code evaluation | End-to-end lifecycle from policy through approval, execution, unknown, and reconciliation | A mature policy language/ecosystem |
| Promptfoo | Model/prompt and red-team evaluation | Runtime enforcement plus deterministic side-effect release metrics | Broad model quality evaluation |
| AgentOps and tracing platforms | Traces, cost, latency, debugging | Blocking controls and a transactional system of record for effects | Full LLM observability UI |
| Invariant-style guardrails | Agent policy/security monitoring | Durable idempotency, approval binding, crash recovery, operator reconciliation | Broad content or interaction guardrails |

## Differentiators that are executable today

1. Same idempotency key with different actor, evidence, risk, or arguments is a hard conflict—not a
   silent replay.
2. State and audit events commit atomically, with a tamper-evident per-run chain.
3. Execution leases and heartbeats turn abandoned calls into explicit unknown outcomes.
4. Approval binds verified identity, tenant, role, request fingerprint, policy version/digest,
   expiry, note, and separation of duties.
5. Default HTTP and audit views omit idempotency keys and sensitive bodies.
6. The same contract runs locally on SQLite and concurrently on PostgreSQL.
7. Safe and deliberately unsafe policies are executable CI evidence, not screenshots.
8. OpenAI Agents, FastMCP, LangGraph, and OPA adapters preserve the same trusted-context boundary.
9. A packaged browser console makes approval, resume, and reconciliation operable without weakening
   server-side tenant or role authorization.

## Remaining gaps

The project does not yet have measured external production adoption, a hosted managed control plane,
WORM audit export, provider-certified connectors, regional HA evidence, independent security audit,
or compliance certification. Those are stated openly instead of being represented by synthetic
benchmarks or maintainer claims. See the roadmap for planned work.
