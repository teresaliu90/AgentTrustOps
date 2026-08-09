# Contributing

Thank you for helping make risky agent actions easier to reason about.

## Local verification

```bash
python -m venv .venv
source .venv/bin/activate
pip install -e '.[api,postgres,oidc,dev]'
ruff check .
ruff format --check .
python -m unittest discover -s tests -v
agenttrust eval examples/refund_ops/scenarios.json \
  --policy examples/refund_ops/policy-safe.json
```

The unsafe policy command is expected to exit with status 1 and print `RELEASE BLOCKED`.

PostgreSQL contract tests run in CI. Locally, set `AGENTTRUSTOPS_TEST_POSTGRES_DSN` to a disposable
test database. The test clears AgentTrustOps tables in that database; never point it at production.

## Good first contributions

- add one adversarial synthetic release scenario;
- improve a safe error or boundary explanation;
- add a policy example that does not require a model or external credential;
- test behavior under repeated or reordered calls.

Do not include employer code, customer data, production prompts, credentials, or proprietary
policies. Keep each pull request focused and include a test for behavioral changes.

Changes to the state machine, fingerprint, approval binding, event hashing, or schema must include
migration notes and failure-path tests.

Use the structured issue forms for reproducible bugs and adversarial scenario proposals. For a
security vulnerability, follow [SECURITY.md](SECURITY.md) instead of opening a public issue.
