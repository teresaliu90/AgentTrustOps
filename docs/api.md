# HTTP API

Install `agenttrustops[api]`, register only trusted actions, provide an `IdentityVerifier`, and
provide a server-side evidence resolver for policies that require evidence. The reference server:

```bash
cp examples/api-identities.example.json /tmp/agenttrust-identities.json
chmod 600 /tmp/agenttrust-identities.json
agenttrust serve \
  --ledger /tmp/agenttrust-actions.db \
  --refunds /tmp/agenttrust-refunds.db \
  --identities /tmp/agenttrust-identities.json
```

Static tokens are only a local demo verifier. Production code should implement `IdentityVerifier`
with workload identity or mTLS, or configure the included asymmetric `OIDCJWTVerifier`:

```python
from agenttrustops import OIDCJWTVerifier

verifier = OIDCJWTVerifier(
    issuer="https://identity.example",
    audience="agenttrustops-api",
    jwks_url="https://identity.example/.well-known/jwks.json",
)
```

It requires HTTPS by default, caches JWKS keys, fixes the allowed asymmetric algorithms, verifies
signature/issuer/audience/expiry, and maps configured tenant/role claims into `VerifiedPrincipal`.

## Endpoints

| Method and path | Required role | Purpose |
|---|---|---|
| `GET /healthz`, `GET /readyz` | public | liveness and ledger readiness |
| `GET /v1/actions` | `agenttrustops_viewer` | list registered governed actions |
| `POST /v1/actions/{name}/invoke` | `agenttrustops_invoker` | submit an action with `Idempotency-Key` |
| `GET /v1/runs` | `agenttrustops_viewer` | tenant-scoped run list |
| `GET /v1/runs/{id}/audit` | viewer; auditor for full fields | verify and inspect the event trail |
| `GET /v1/approvals` | `agenttrustops_viewer` | tenant approval inbox |
| `POST /v1/runs/{id}/approve` or `/reject` | action approval role | record a bound decision |
| `POST /v1/runs/{id}/resume` | `agenttrustops_executor` | execute an approved action |
| `POST /v1/runs/{id}/reconcile` | action reconciliation role | resolve an unknown outcome |
| `POST /v1/operations/recover` | `agenttrustops_operator` | move expired leases to unknown |
| `GET /metrics` | `agenttrustops_observer` | tenant-scoped Prometheus text |

## Approval walkthrough

Invoke as shown in the README and copy the returned `run_id`:

```bash
curl -sS -X POST "http://localhost:8787/v1/runs/$RUN_ID/approve" \
  -H 'Authorization: Bearer local-demo-manager-token-change-me' \
  -H 'Content-Type: application/json' \
  -d '{"note":"Reviewed synthetic order and logistics records"}'

curl -sS -X POST "http://localhost:8787/v1/runs/$RUN_ID/resume" \
  -H 'Authorization: Bearer local-demo-manager-token-change-me'
```

Default action responses never include authorization credentials, idempotency keys, original
request bodies, evidence bodies, or identity claims. The same request/key returns byte-equivalent
JSON content apart from transport headers. Different content with the same key returns HTTP 409.

## Trust boundary

`InvokeRequest` accepts only `arguments` and opaque `evidence_refs`; extra actor, tenant, or role
fields are rejected. The application resolver must fetch or validate evidence from an authoritative
system. Passing user/model text through as verified evidence defeats the policy boundary.
