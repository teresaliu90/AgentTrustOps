"""Reproducible local SQLite throughput probe, not a production SLO claim."""

from __future__ import annotations

import argparse
import json
import platform
import statistics
import tempfile
import time
from pathlib import Path

from agenttrustops import (
    ActionContext,
    PolicyDecision,
    PolicyOutcome,
    SQLiteActionLedger,
    trusted_action,
)


class AllowPolicy:
    def evaluate(self, action_name, arguments, context):
        return PolicyDecision(PolicyOutcome.ALLOW, "benchmark allow", "benchmark-v1")


def percentile(samples: list[float], fraction: float) -> float:
    ordered = sorted(samples)
    return ordered[min(len(ordered) - 1, int((len(ordered) - 1) * fraction))]


def summarize(samples: list[float]) -> dict[str, float]:
    return {
        "mean_ms": round(statistics.fmean(samples) * 1000, 3),
        "p50_ms": round(percentile(samples, 0.50) * 1000, 3),
        "p95_ms": round(percentile(samples, 0.95) * 1000, 3),
        "operations_per_second": round(len(samples) / sum(samples), 2),
    }


def run(iterations: int) -> dict:
    with tempfile.TemporaryDirectory() as directory:
        ledger = SQLiteActionLedger(Path(directory) / "benchmark.db")
        executions = 0

        @trusted_action(
            ledger=ledger,
            policy=AllowPolicy(),
            risk="benchmark",
            idempotency_key=lambda arguments, context: str(arguments["request_id"]),
        )
        def record(request_id: str):
            nonlocal executions
            executions += 1
            return {"recorded": request_id}

        context = ActionContext(actor_id="benchmark-agent")
        unique_samples = []
        for index in range(iterations):
            started = time.perf_counter()
            record.invoke(context=context, request_id=f"unique-{index:08d}")
            unique_samples.append(time.perf_counter() - started)

        duplicate_samples = []
        for _ in range(iterations):
            started = time.perf_counter()
            record.invoke(context=context, request_id="duplicate-00000001")
            duplicate_samples.append(time.perf_counter() - started)

        ledger.verify_all_event_chains()
        result = {
            "schema": "agenttrustops-benchmark-v1",
            "python": platform.python_version(),
            "platform": platform.platform(),
            "iterations_per_case": iterations,
            "unique": summarize(unique_samples),
            "duplicate_retry": summarize(duplicate_samples),
            "protected_function_executions": executions,
            "expected_function_executions": iterations + 1,
            "integrity_verified": executions == iterations + 1,
        }
        ledger.close()
        return result


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--iterations", type=int, default=500)
    parser.add_argument("--output", type=Path)
    args = parser.parse_args()
    if not 10 <= args.iterations <= 100_000:
        parser.error("--iterations must be between 10 and 100000")
    result = run(args.iterations)
    rendered = json.dumps(result, indent=2, sort_keys=True)
    if args.output:
        args.output.write_text(rendered + "\n", encoding="utf-8")
    print(rendered)
    return 0 if result["integrity_verified"] else 1


if __name__ == "__main__":
    raise SystemExit(main())
