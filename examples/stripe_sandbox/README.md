# Stripe Sandbox external-evaluation path

This example creates real Stripe **Sandbox** objects, injects an ambiguous post-provider failure,
proves ten retries do not re-execute, reconciles with Stripe's idempotent replay, exercises a
pending payment, and writes a signed redacted evidence packet.

It refuses `sk_live_` and `rk_live_` keys. Use synthetic invoice IDs and Stripe test PaymentMethods
only. It is not a production connector.

## 1. Prepare

Create a Stripe Sandbox and copy a test secret key. Keep it only in your shell:

```bash
python -m venv .venv
. .venv/bin/activate
pip install -e '.[stripe,audit]'
export STRIPE_SECRET_KEY='sk_test_...'
```

Never paste the key into an issue, report, screenshot, terminal transcript, or committed file.

## 2. Run

Choose a directory that does not exist yet:

```bash
python examples/stripe_sandbox/run_evaluation.py \
  --output-dir stripe-evaluation-001
```

The runner exits non-zero unless all six scenarios pass. It deletes the temporary private signing
key after producing the signed bundle; only the public verification key remains.

Complete reconciliation promptly. The adapter refuses idempotent POST replay at 23 hours because
Stripe does not retain idempotency results forever; an old unknown run requires manual provider
investigation, not another create request.

## 3. Verify and redact

Open the Stripe test Dashboard and search for the three synthetic invoice values printed in
`sanitized-result.json`. Confirm the ambiguous invoice has exactly one PaymentIntent. Save a
redacted screenshot as `dashboard-redacted.png`.

Review every generated file before publishing. Do not publish `action-ledger.db`: it contains the
full governed request. The files intended for a consented case report are:

- `report.md` after completing every TODO;
- `sanitized-result.json`;
- `audit-bundle.json` and `audit-public-key.pem`;
- `verification.txt`;
- `dashboard-redacted.png`.

## 4. Count it honestly

A maintainer run is integration evidence but does not change adoption. One independent evaluator
using their own Sandbox, completing the run without coaching, and consenting to a report qualifies
as one external evaluation—not a production adopter.
