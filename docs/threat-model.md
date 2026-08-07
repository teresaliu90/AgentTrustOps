# Threat model

## Assets

- authority to invoke a side-effecting business tool;
- action arguments and evidence references;
- tenant and role scope;
- approval identity and note;
- idempotency identity and stored result;
- ordered action events.

## Threats covered by the reference SDK

- repeated requests using the same tenant/action/idempotency identity;
- direct invocation that bypasses the `TrustedAction` wrapper;
- missing required evidence;
- disallowed roles and cross-tenant synthetic orders;
- high-value actions attempting to bypass approval;
- using the latest policy for a historical order;
- exception details leaking stack traces through the action result;
- unexplainable decisions without an ordered run event view.

## Threats not solved by the reference SDK

- compromised application code or database administrators;
- forged identity claims supplied by an untrusted gateway;
- tampering with the SQLite database on disk;
- two independent systems using inconsistent idempotency identities;
- a process crash after an external provider commits a side effect but before the local result is
  persisted;
- malicious tool implementations, supply-chain compromise, prompt injection outside the policy
  inputs, or secrets exposed by the host application;
- real payment reconciliation, fraud detection, legal compliance, or disaster recovery.

## Required production controls

A real deployment must bind identity through OIDC/SSO or a trusted service identity, encrypt data,
externalize authorization policy, use a durable transactional design or provider idempotency,
redact sensitive payloads, export audit events, monitor abuse, back up and restore state, and test
crash windows with the real provider's reconciliation semantics.
