# Integrations

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

## Temporal and other workflow engines

Call `invoke_request` inside an activity and use the workflow/activity identity as the stable
idempotency key. AgentTrustOps governs the business side effect; the workflow engine governs
scheduling and orchestration. An activity retry will receive the existing run instead of executing
again. Unknown outcomes must be resolved before the workflow proceeds.

## OPA and policy engines

Implement the small `ActionPolicy.evaluate` protocol and translate the engine response into
`PolicyDecision`. Store the policy bundle/version digest in `policy_digest` so approval remains
bound to exactly what was evaluated. Treat engine timeouts and invalid output as failures; the
runtime fails closed.

## Evaluation and observability tools

Promptfoo or similar scenario systems can generate adversarial cases for `agenttrust eval`.
AgentOps/OpenTelemetry can trace reasoning and model calls while AgentTrustOps remains the durable
enforcement/audit record for business side effects. Correlate by run ID, never by copying secrets or
full prompts into metric labels.
