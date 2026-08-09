## Change

Describe the user problem and the governed-action behavior that changes.

## Safety contract

- [ ] Idempotency behavior is unchanged or covered by a conflict/retry test.
- [ ] Approval, tenant, and verified-role boundaries are covered by tests.
- [ ] Crash/unknown/reconciliation behavior is explicit where side effects are involved.
- [ ] No credentials, customer data, production prompts, or proprietary policies are included.
- [ ] `ruff check .`, `ruff format --check .`, and the full test suite pass.

## Evidence

Include commands, test output, and any migration or rollback notes.
