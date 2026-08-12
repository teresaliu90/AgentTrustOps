# Production boundaries

AgentTrustOps v0.3 is a beta-quality foundation with a deployable control plane and PostgreSQL
contract tests. It does not certify a particular business integration.

- **Identity:** `ActionContext` remains an SDK trust-boundary input. The HTTP adapter instead derives
  actor/tenant/roles through `IdentityVerifier`; applications must supply production-grade OIDC,
  workload identity, or mTLS verification. The optional OIDC verifier covers signed JWT/JWKS
  validation but still requires correct provider-specific issuer, audience, and claim mapping.
- **Evidence:** the API accepts opaque references, not authoritative evidence. A server-side
  resolver must fetch or validate facts from systems of record.
- **Integrity:** event chains detect changes but are not immutable against an administrator who can
  rewrite and rehash the whole database. Signed redacted bundles protect portable evidence after
  export; use independently controlled append-only/WORM storage when immutability is required.
- **Exactly once:** database claims stop duplicate local execution. Distributed exactly-once is not
  claimed; the provider must also enforce a stable idempotency key.
- **Crash window:** ambiguous provider results and abandoned leases become `unknown`, suppressing
  blind retry until verified reconciliation.
- **Sensitive data:** default views redact payloads, but the reference schema stores arguments,
  evidence, and results. Minimize, tokenize, encrypt, or omit them according to retention policy.
- **Availability:** PostgreSQL supports multiple processes, but the repository does not ship a
  regional HA topology or measured SLO.
- **Adoption:** tests and demos are technical evidence, not proof of production use or compliance.

The included fictional RefundOps adapter never contacts a payment system and must not be mistaken
for a production financial integration.
