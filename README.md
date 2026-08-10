# AgentTrustOps

[![CI](https://github.com/teresaliu90/AgentTrustOps/actions/workflows/ci.yml/badge.svg)](https://github.com/teresaliu90/AgentTrustOps/actions/workflows/ci.yml)
[![CodeQL](https://github.com/teresaliu90/AgentTrustOps/actions/workflows/codeql.yml/badge.svg)](https://github.com/teresaliu90/AgentTrustOps/actions/workflows/codeql.yml)
[![Python 3.11–3.13](https://img.shields.io/badge/python-3.11%E2%80%933.13-blue)](https://www.python.org/)
[![Apache 2.0](https://img.shields.io/badge/license-Apache--2.0-green)](LICENSE)
[![Release](https://img.shields.io/github/v/release/teresaliu90/AgentTrustOps?display_name=tag)](https://github.com/teresaliu90/AgentTrustOps/releases)
[![OpenSSF Scorecard](https://api.scorecard.dev/projects/github.com/teresaliu90/AgentTrustOps/badge)](https://scorecard.dev/viewer/?uri=github.com/teresaliu90/AgentTrustOps)

**The side-effect control plane for AI agents.**

Agent frameworks help a model decide which tool to call. AgentTrustOps governs whether a risky
tool call may execute, who must approve it, how retries are deduplicated, and what operators do
when the provider outcome is uncertain.

It sits between an agent runtime and business APIs:

```text
Agent / workflow
       │ proposed action + stable Idempotency-Key
       ▼
AgentTrustOps ── policy ── deny
       │          │
       │          └──────── approval inbox ── verified approver
       │
       ├── transactional execution lease ── business API
       ├── unknown outcome ──────────────── reconciliation
       └── redacted, tamper-evident audit + durable metrics
```

## The operational problems it solves

| Incident pattern | AgentTrustOps contract |
|---|---|
| A retry repeats a refund, email, deployment, or data mutation | Same key + same request returns the stored run; same key + different request is a `409` conflict |
| A model or caller claims an admin role | HTTP identity is derived from a verified credential, never from request-body actor/tenant/roles |
| A high-risk action bypasses a human | Approval is bound to tenant, request fingerprint, policy digest, expiry, role, and separation of duties |
| A worker crashes after the provider may have committed | Execution lease expires to `unknown`; it is never blindly retried |
| An operator cannot explain an incident | State and event append are one transaction; each per-run event is SHA-256 chained |
| Audit endpoints leak prompts, evidence, tokens, or keys | Public responses omit credentials and idempotency keys; audit is redacted unless a same-tenant auditor is verified |
| A safer policy regresses before release | Deterministic adversarial scenarios block CI without a model, network, or API key |

## Five-minute runnable proof

Install the attested release wheel directly from GitHub:

```bash
pip install "agenttrustops[api] @ https://github.com/teresaliu90/AgentTrustOps/releases/download/v0.2.0/agenttrustops-0.2.0-py3-none-any.whl"
```

For development from the repository, use the editable path below.

### Local SDK and release gate

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[api,postgres,oidc,dev]'

agenttrust eval examples/refund_ops/scenarios.json \
  --policy examples/refund_ops/policy-safe.json
python -m unittest discover -s tests -v
```

The safe policy reports `RELEASE ALLOWED`. The deliberately unsafe policy exits non-zero:

```bash
agenttrust eval examples/refund_ops/scenarios.json \
  --policy examples/refund_ops/policy-unsafe.json
```

### Authenticated control plane with PostgreSQL

```bash
docker compose up --build
```

Open `http://localhost:8787/ui` for the built-in approval, resume, and reconciliation console. The
browser keeps the bearer credential in memory only; refresh or **Clear** removes it. Every operation
still passes through the API's tenant and role checks.

The included identities and database password are conspicuous local-demo values. With the stack
running, submit a high-value synthetic refund:

```bash
curl -sS http://localhost:8787/v1/actions/execute_refund/invoke \
  -H 'Authorization: Bearer local-demo-invoker-token-change-me' \
  -H 'Idempotency-Key: refund-demo-request-0001' \
  -H 'Content-Type: application/json' \
  -d '{
    "arguments": {"order_id": "O-HIGH", "amount": 800},
    "evidence_refs": ["order-record", "logistics-record"]
  }'
```

The response is `pending_approval`. Repeating the exact request returns the same public result and
does not regenerate evidence or execute another side effect. Changing the amount while reusing
the key returns a conflict. See [the API walkthrough](docs/api.md) for approval and resumption.

## SDK

```python
from agenttrustops import ActionContext, SQLiteActionLedger, trusted_action

ledger = SQLiteActionLedger("actions.db")


@trusted_action(
    ledger=ledger,
    policy=refund_policy,
    risk="financial",
    idempotency_key=lambda args, ctx: f"refund:{ctx.tenant_id}:{args['order_id']}",
)
def execute_refund(order_id: str, amount: float):
    return payment_adapter.refund(order_id, amount)


result = execute_refund.invoke(
    context=ActionContext(
        actor_id="refund-agent",
        tenant_id="acme",
        roles=("refund_agent",),
        evidence=("ORDER:O-001", "LOGISTICS:O-001"),
    ),
    order_id="O-001",
    amount=800,
)
```

Direct calls to the wrapped function are blocked. Async actions use `invoke_async`. Gateways use
`invoke_request` / `invoke_request_async` to supply the caller's `Idempotency-Key` explicitly.

Approvals require a principal created by a trusted authentication adapter:

```python
from agenttrustops import VerifiedPrincipal

action.approve(
    result.run_id,
    principal=VerifiedPrincipal(
        actor_id="finance-manager",
        tenant_id="acme",
        roles=("agenttrustops_approver",),
        auth_source="verified-oidc",
    ),
    note="Reviewed order and logistics records",
)
completed = action.resume(result.run_id)
```

Constructing `VerifiedPrincipal` does not itself authenticate anyone. Only an OIDC, workload
identity, mTLS, or equivalent trusted adapter should construct one in production.

## Crash-safe unknown outcomes

No middleware can infer whether a remote side effect committed after a connection was lost.
Adapters signal that ambiguity explicitly:

```python
from agenttrustops import IndeterminateOutcome

try:
    return provider.charge(order_id, amount)
except ProviderResponseLost as error:
    raise IndeterminateOutcome from error
```

The run becomes `unknown`; duplicate execution stays suppressed. A verified reconciliation worker
checks the provider and resolves the run once. Execution leases and automatic heartbeats also move
abandoned workers to this safe state.

## Deployment choices

| Backend | Intended use | Concurrency |
|---|---|---|
| `SQLiteActionLedger` | SDK evaluation, tests, single-instance services | WAL + transactional write serialization |
| `PostgresActionLedger` | Multi-process control-plane deployments | row-level claims and per-run event-chain locks |

Install optional components with `agenttrustops[api]`, `agenttrustops[postgres]`,
`agenttrustops[oidc]`, `agenttrustops[openai]`, and `agenttrustops[mcp]`. The FastAPI control plane includes authenticated
invocation, browser approval inbox, rejection, resume, reconciliation,
tenant-scoped audit, recovery, health/readiness, and Prometheus metrics. Run `agenttrust doctor` to
verify schema access and event chains.

## Framework integration

Adapters are included for LangGraph, OpenAI Agents SDK, MCP hosts, and OPA. The dependency-free
LangGraph adapter returns a state-in/partial-state-out node:

```python
from agenttrustops import as_langgraph_node

refund_node = as_langgraph_node(
    execute_refund,
    context=context_from_trusted_graph_config,
    arguments=lambda state: state["refund_arguments"],
    idempotency_key=lambda state: state["request_id"],
)
```

Branch on `state["agenttrustops"]["status"]` for `pending_approval` or `unknown`. All adapters keep
verified identity and retry authority outside model-visible arguments. AgentTrustOps composes with
orchestration, policy, evaluation, and observability systems rather than replacing them. See
[integrations](docs/integrations.md) and the [honest comparison](docs/comparison.md).

## Use it as a GitHub release gate

```yaml
- uses: teresaliu90/AgentTrustOps@v0.2.0
  with:
    scenarios: scenarios/refund.json
    policy: policies/refund.json
```

The composite action installs the exact referenced repository revision and exits non-zero when a
scenario violates the release contract. Versioned GitHub Releases attach wheels, source archives,
SHA-256 checksums, a CycloneDX SBOM, and GitHub artifact attestations. The release workflow also
publishes an SBOM/provenance-attested image to GHCR. PyPI Trusted Publishing is prepared but is not
claimed as live until the package page exists; see [publishing](docs/publishing.md).

## Guarantees and non-guarantees

AgentTrustOps provides enforceable local/database contracts: fail-closed policy evaluation,
request-fingerprint idempotency conflicts, atomic state/event transitions, bound approvals,
single-owner execution claims, explicit unknown outcomes, and privacy-safe default views.

It does **not** claim distributed exactly-once delivery, cryptographic immutability, identity
verification by a Python dataclass, rollback of irreversible side effects, compliance
certification, or real-world adoption that has not happened. Provider-native idempotency remains a
required second boundary.

## Documentation

- [Architecture and state machine](docs/architecture.md)
- [HTTP API and end-to-end walkthrough](docs/api.md)
- [Operations, PostgreSQL, metrics, backup, and incident runbook](docs/operations.md)
- [Security model and privacy defaults](docs/threat-model.md)
- [Production boundaries](docs/production-boundaries.md)
- [Framework integrations](docs/integrations.md)
- [Performance methodology and reproducible probe](docs/performance.md)
- [Release artifacts, GHCR, and PyPI publishing](docs/publishing.md)
- [Competitive comparison](docs/comparison.md)
- [Evidence-based scorecard](docs/scorecard.md)
- [Independent design-partner feedback kit](docs/design-partner-feedback-kit.md)
- [Adopter evidence policy](ADOPTERS.md), [governance](GOVERNANCE.md), and [support](SUPPORT.md)
- [Migration from v0.1](docs/migration-v0.2.md)
- [Roadmap](ROADMAP.md) and [changelog](CHANGELOG.md)

## Project status

v0.2 is a tested beta-quality foundation, not a compliance-certified managed service. CI covers
Python 3.11–3.13, SQLite, a real PostgreSQL service, the API and browser-control workflow,
concurrency/crash contracts, package installation, dependency audit, adapter contracts, a reusable
release action, and a deliberately unsafe release. Contributions, real design-partner reports, and
adversarial scenarios are welcome under the [contribution guide](CONTRIBUTING.md).

Apache-2.0 licensed.
