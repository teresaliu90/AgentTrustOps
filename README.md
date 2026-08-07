# AgentTrustOps

**Stop unsafe AI-agent actions before they become business incidents.**

AgentTrustOps is an early-alpha Python SDK for policy-checked, approval-aware,
idempotent, and replayable tool execution.

## What it prevents

- A new policy selects the wrong refund rules → **release blocked**
- A timeout or retry submits the same refund ten times → **exactly one side effect**
- A high-risk action bypasses approval → **execution paused**
- An incident cannot be explained → **inspect the event trail by run ID**

This is a reference implementation using fictional orders and simulated refunds. It is not a
payment system, identity provider, fraud engine, immutable ledger, or production certification.

## Two-minute proof

Python 3.11+ is the only runtime requirement.

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e .

agenttrust eval examples/refund_ops/scenarios.json \
  --policy examples/refund_ops/policy-safe.json
```

Expected result:

```text
Release: refund-agent-safe-v0.1.0
Scenarios: 7
Wrong decisions: 0
Wrong policy decisions: 0
Duplicate side effects: 0
Approval bypasses: 0

RELEASE ALLOWED
```

Now evaluate a deliberately unsafe release:

```bash
agenttrust eval examples/refund_ops/scenarios.json \
  --policy examples/refund_ops/policy-unsafe.json
```

It returns a non-zero exit code suitable for CI:

```text
Wrong decisions: 3
Wrong policy decisions: 1
Approval bypasses: 1

RELEASE BLOCKED
```

## SDK shape

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

assert result.status == "pending_approval"
```

The wrapped function cannot be called directly. Approval, rejection, resumption, duplicate
suppression, and audit lookup remain explicit SDK operations.

## Core flow

```text
Agent tool call
      |
      v
TrustedAction -> Policy -> allow / deny / approval required
      |                         |
      v                         v
Action Ledger             named human decision
      |
      v
atomic execution claim -> business tool -> stored result
      |
      v
run ID + append-only event view
```

## What exists in v0.1

- decorator-backed `TrustedAction` SDK;
- tenant/action/idempotency uniqueness enforced in SQLite;
- policy outcomes: allow, deny, or approval required;
- named approval/rejection and explicit resume;
- append-only action events and replayable audit view;
- historical and current synthetic refund policies;
- seven deterministic release scenarios;
- a safe release that passes and an unsafe release that CI blocks;
- standard-library tests with no model, network, or API key.

## Repository map

```text
src/agenttrustops/       SDK, ledger, runtime, CLI and RefundOps reference app
examples/refund_ops/     fictional policies and release scenarios
tests/                   idempotency, approval, denial, replay and release-gate tests
docs/                    problem, non-goals, threat model and production boundaries
.github/workflows/       clean Python 3.11/3.12 verification
```

## Run the tests

```bash
PYTHONPATH=src python -m unittest discover -s tests -v
```

## Security and production boundary

Request-supplied tenant/roles are not authenticated identity. SQLite provides a reproducible
reference ledger but reports `chain_verified: false`; it is not cryptographically tamper-proof.
An external side effect may be impossible to roll back, so uncertain outcomes must be reconciled
or escalated rather than blindly retried. Read the [threat model](docs/threat-model.md) and
[production boundaries](docs/production-boundaries.md) before integrating a real tool.

## Scope discipline

The first release intentionally does not include a general workflow engine, model gateway,
multi-agent framework, Kubernetes operator, full observability platform, or real payment
connector. See [non-goals](docs/non-goals.md).

## Contributing

Bug reports, adversarial scenarios, policy adapters, and documentation improvements are welcome.
See [CONTRIBUTING.md](CONTRIBUTING.md) and [SECURITY.md](SECURITY.md).

Apache-2.0 licensed.
