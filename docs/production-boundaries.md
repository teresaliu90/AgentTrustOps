# Production boundaries

AgentTrustOps v0.1 is an early-alpha reference SDK. It proves local decision and idempotency
contracts against fictional data; it does not certify a production integration.

## Important boundaries

- **Identity:** `ActionContext` values are application inputs. The SDK does not authenticate them.
- **Ledger integrity:** events are append-only through the public API, but SQLite files can be
  modified by an administrator. Audit views report `chain_verified: false`.
- **Exactly-once language:** the demo prevents duplicate local execution for one stable
  idempotency identity. Distributed exactly-once delivery is not claimed.
- **Crash window:** if an external provider succeeds and the process crashes before storing the
  result, the run requires provider reconciliation or manual handling.
- **Approval:** a production approval actor must come from authenticated identity and policy, not
  an arbitrary request field.
- **Sensitive data:** the demo stores action arguments for explainability. Production adapters
  must redact, tokenize, encrypt, or avoid sensitive fields according to retention policy.
- **Compensation:** some side effects cannot be reversed. Unknown outcomes must pause and escalate
  rather than automatically retry.

These boundaries are acceptance criteria for future production adapters, not hidden roadmap
details.
