# OPA example

Run a local OPA server from the repository root:

```bash
opa run --server examples/opa/agenttrustops.rego
```

Configure the adapter only for this local HTTP process:

```python
policy = OPAPolicy(
    "http://127.0.0.1:8181",
    "agenttrustops/decision",
    allow_insecure_http=True,
)
```

Production OPA endpoints must use HTTPS. Replace the example digest with the immutable digest from
your signed policy-bundle build; the literal example value is intentionally not presented as a real
bundle digest.
