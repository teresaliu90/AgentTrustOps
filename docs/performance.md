# Performance evidence

AgentTrustOps publishes a reproducible latency/throughput probe, not a universal production SLO.
Database durability mode, filesystem, CPU, policy latency, provider latency, contention, and audit
payload size all affect real results.

## Run the SQLite probe

```bash
python benchmarks/benchmark_sqlite.py --iterations 1000 --output benchmark.json
```

The probe measures two end-to-end paths:

- unique allowed requests, including run creation, policy decision, execution claim, protected
  function call, result persistence, and event-chain writes;
- duplicate retries, including request-fingerprint comparison and duplicate accounting, while
  proving the protected function executes only once for the repeated key.

It verifies all event chains and exits non-zero if the execution count violates the expected
idempotency contract. CI runs a small integrity probe on Python 3.11–3.13 and publishes the Python
3.13 JSON result as a workflow artifact. The benchmark reports platform metadata so results are not
compared as though they came from identical hardware. A dated maintainer-machine reference is kept
at [`benchmarks/results/reference-local.json`](../benchmarks/results/reference-local.json); it is
evidence that the full probe ran, not a cross-machine performance promise.

## Interpreting results

Use the result as a regression baseline on the same runner class, Python version, database settings,
and workload shape. Do not use the SQLite number to size a multi-process PostgreSQL deployment.
For production capacity tests, replay a synthetic distribution of arguments and policy outcomes
against a disposable environment, include approval/unknown paths, and measure database saturation,
provider latency, recovery lag, and tail latency. Never benchmark against a live side-effecting
provider account.

The repository's PostgreSQL CI test proves row-claim and per-run chain-lock correctness under
concurrency. It is a correctness contract, not an HA, regional failover, or load certification.
