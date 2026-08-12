# Integrations

Every adapter follows one rule: the model may propose business arguments, but actor, tenant, roles,
evidence, credentials, and idempotency come from trusted host state.

## Trusted provider execution context

An adapter that must forward the governed key can request a runtime-only parameter:

```python
@trusted_action(
    ledger=ledger,
    policy=policy,
    risk="payment",
    idempotency_key=payment_key,
    execution_context_parameter="execution",
)
def charge(invoice_id, amount, currency, *, execution):
    return provider.charge(
        invoice_id=invoice_id,
        amount=amount,
        currency=currency,
        execution=execution,
    )
```

`execution` is an `ActionExecutionContext` built from the persisted run after the execution lease
is claimed. It includes the exact `run_id`, `tenant_id`, `idempotency_key`, and attempt. Supplying
that parameter through SDK or HTTP arguments is rejected before policy or provider execution.

## Stripe Sandbox

Install `agenttrustops[stripe]`. `StripeSandboxPaymentAdapter` refuses live keys, forwards the
trusted AgentTrustOps idempotency key to the official Stripe SDK, validates amount/currency/run
metadata, and persists no client secret. `StripeSandboxPaymentProbe` replays the exact same Sandbox
POST under Stripe's idempotency contract; `succeeded`, non-committed, and in-progress statuses map
to the three provider outcomes.

Use the [six-scenario runner](../examples/stripe_sandbox/README.md) to produce local verification
artifacts. This is a Sandbox example, not a production connector or Stripe certification.

## LangGraph

`as_langgraph_node` has no LangGraph dependency. It returns a normal sync or async callable that
accepts graph state and returns a partial state update under `agenttrustops` by default.

```python
node = as_langgraph_node(
    action,
    context=lambda state: context_from_verified_runtime_config(state),
    arguments=lambda state: state["tool_arguments"],
    idempotency_key=lambda state: state["request_id"],
)
```

Route `pending_approval` to a graph interrupt and `unknown` to an operator/reconciliation path. Do
not let model-generated state construct a verified principal or authoritative evidence.

## OpenAI Agents SDK

Install `agenttrustops[openai]` and wrap a registered action as an Agents SDK `FunctionTool`:

```python
from agenttrustops import as_openai_agents_tool

refund_tool = as_openai_agents_tool(
    execute_refund,
    params_json_schema={
        "type": "object",
        "properties": {
            "order_id": {"type": "string"},
            "amount": {"type": "number"},
        },
        "required": ["order_id", "amount"],
        "additionalProperties": False,
    },
    context=lambda tool_ctx, args: tool_ctx.context.action_context,
    idempotency_key=lambda tool_ctx, args: tool_ctx.context.request_id,
)
```

Here `tool_ctx.context` is application context supplied to the Agents SDK run, not model-visible
JSON. The tool returns public run state; callers branch or hand off when status is
`pending_approval` or `unknown`. See the official [OpenAI Agents SDK function-tool documentation](https://openai.github.io/openai-agents-python/tools/)
and [context documentation](https://openai.github.io/openai-agents-python/context/).

## MCP servers

Install `agenttrustops[mcp]`. `register_fastmcp_action` registers an async handler on a FastMCP
server and returns it for direct contract tests. Resolve the principal from authenticated request
middleware or a request-local `ContextVar`:

```python
handler = register_fastmcp_action(
    mcp,
    execute_refund,
    context=lambda: verified_action_context.get(),
    idempotency_key=lambda arguments: authenticated_request_id.get(),
)
```

Do not expose identity or idempotency as MCP tool arguments. The host is responsible for transport
authentication and populating both request-local values before dispatch. The adapter's public
result intentionally omits the key.

## Temporal and other workflow engines

Call `invoke_request` inside an activity and use the workflow/activity identity as the stable
idempotency key. AgentTrustOps governs the business side effect; the workflow engine governs
scheduling and orchestration. An activity retry receives the existing run instead of executing
again. Unknown outcomes must be resolved before the workflow proceeds.

## OPA and policy engines

`OPAPolicy` calls an OPA Data API document over HTTPS and validates a strict result contract:

```python
from agenttrustops import OPAPolicy

policy = OPAPolicy("https://opa.internal", "agenttrustops/decision")
```

OPA receives `input.action_name`, `input.arguments`, and the trusted action context. It must return
`result.outcome`, `result.reason`, and `result.policy_version`; optional `policy_digest` binds an
approval to the evaluated bundle. Timeouts, undefined documents, HTTP errors, oversized replies,
and malformed output raise at the boundary, which the runtime converts to a fail-closed denial.
HTTP is disabled unless explicitly allowed for local testing. See OPA's official [REST API](https://www.openpolicyagent.org/docs/rest-api).
The repository includes a runnable [Rego decision document](../examples/opa/agenttrustops.rego).
CI starts pinned OPA 1.17.0 and exercises allow, approval-required, and deny through the real Data
API, so the adapter contract is not based only on a mocked HTTP response.

## Evaluation and observability tools

Promptfoo or similar scenario systems can generate adversarial cases for `agenttrust eval`.
AgentOps/OpenTelemetry can trace reasoning and model calls while AgentTrustOps remains the durable
enforcement/audit record for business side effects. Correlate by run ID, never by copying secrets or
full prompts into metric labels.
