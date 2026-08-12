# Threat model

## Protected assets

- authority to invoke a side-effecting business tool;
- action arguments, evidence, tenant and role scope;
- approval/reconciliation identity and notes;
- idempotency keys and stored provider results;
- policy version/digest and ordered action events.

## Covered threats

- changed arguments, actor, roles, evidence, action, or risk reusing an idempotency key;
- direct calls to the decorated `TrustedAction` object;
- execution before a successful policy decision;
- fail-open policy exceptions;
- high-risk actions bypassing approval;
- cross-tenant approval, reconciliation, listing, or audit access;
- self-approval and missing approval/reconciliation roles;
- approval replay after request/policy change or expiry;
- concurrent workers claiming the same action;
- dead executors remaining stuck or being automatically retried;
- state changes committing without their audit event;
- event modification, removal, or reordering detectable by the per-run hash chain;
- raw actor, arguments, evidence, and idempotency key exposed by default list/audit views;
- actor, tenant, and role spoofing through HTTP request-body fields.

## Partially covered

- **Identity:** the API requires an `IdentityVerifier` and ships asymmetric OIDC/JWKS verification.
  Provider-specific discovery, claim mapping, workload identity, and mTLS remain deployment work.
- **Audit integrity:** hash chains are tamper-evident, not immutable against a database
  administrator who can recompute the entire history.
- **Provider crashes:** leases and `IndeterminateOutcome` prevent blind retry. Server-owned probes
  provide a guarded lookup contract, but correctness still depends on each provider's consistency
  and idempotency guarantees.
- **Sensitive storage:** public views are redacted, while the reference schema retains arguments,
  evidence, and results for explainability.
- **Invocation results:** a successful invoke returns the action-defined result to the authorized
  caller. Action authors must return a privacy-safe shape; AgentTrustOps does not infer sensitive
  fields.

## Not covered

- compromised host/application code, direct use of `action.function`, identity provider, database
  administrator, or approver;
- SQL/database credentials leaked outside AgentTrustOps;
- prompt injection or malicious tool behavior not represented in policy inputs;
- two organizations choosing inconsistent business idempotency identities;
- provider behavior that ignores its own idempotency contract;
- fraud detection, legal conclusions, certification, disaster recovery, DDoS protection, or
  regional availability.

## Required production controls

Verify OIDC/workload/mTLS identity, terminate TLS at a trusted boundary, use least-privilege database
roles, encrypt data and backups, minimize stored payloads, use provider-native idempotency, export
audit events to independently controlled storage, rate-limit callers, monitor unknown/expired runs,
test backup restore, and exercise the real provider's crash/reconciliation semantics.
