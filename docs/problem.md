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
an incorrect duplicate can cause direct loss. RefundOps is synthetic and contains no employer or
customer data; the optional Stripe example connects only to Sandbox and refuses live keys.

## Success criteria through v0.3

1. Ten identical requests produce exactly one synthetic refund.
2. A high-value refund cannot execute before a named approval.
3. A historical order uses the policy effective on its order date.
4. Missing evidence, wrong roles, and cross-tenant orders are denied.
5. A deliberately unsafe release is blocked by a deterministic CLI evaluation.
6. A run ID returns the ordered policy, approval, execution, and completion events.
7. Reusing a key with any changed governed input produces a conflict.
8. State and audit events roll back together when either write fails.
9. A dead executor lease becomes unknown and cannot be revived or blindly retried.
10. Approval and reconciliation require verified, same-tenant, authorized principals.
11. Default API and audit responses omit sensitive bodies and idempotency keys.
12. The contract runs through an authenticated API on SQLite and PostgreSQL.
13. The reference server can fail closed into either static-demo or OIDC/JWKS authentication.
14. A redacted export refuses a broken source chain and detects offline payload/signature tampering
    against a pinned public key.
