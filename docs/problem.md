# Problem statement

Tool-using agents cross a boundary that ordinary chat systems do not: a model output may create a
ticket, send a message, modify a record, or move money. Model quality scores alone do not prevent
duplicate, unauthorized, unapproved, or historically incorrect actions.

AgentTrustOps treats each side-effecting call as a governed Action. Before code crosses the
side-effect boundary, a policy returns one of three explicit outcomes: allow, deny, or require
approval. One idempotency identity represents one business intent, and the action ledger records
the decision and outcome under a public run ID.

The first reference problem is a fictional refund workflow because it makes the risk concrete:
policy versions change, historical orders exist, large amounts need approval, retries happen, and
an incorrect duplicate can cause direct loss. The repository never connects to a real payment
provider and contains no employer or customer data.

## Success criteria for v0.1

1. Ten identical requests produce exactly one synthetic refund.
2. A high-value refund cannot execute before a named approval.
3. A historical order uses the policy effective on its order date.
4. Missing evidence, wrong roles, and cross-tenant orders are denied.
5. A deliberately unsafe release is blocked by a deterministic CLI evaluation.
6. A run ID returns the ordered policy, approval, execution, and completion events.
