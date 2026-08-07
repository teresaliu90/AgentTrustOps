"""AgentTrustOps command line entry point."""

from __future__ import annotations

import argparse
import json
from pathlib import Path

from .ledger import SQLiteActionLedger
from .refund_ops import evaluate_release


def _eval(args: argparse.Namespace) -> int:
    report = evaluate_release(args.scenarios, args.policy)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
    else:
        print(f"Release: {report['release']}")
        print(f"Scenarios: {report['scenarios']}")
        print(f"Wrong decisions: {report['wrong_decisions']}")
        print(f"Wrong policy decisions: {report['wrong_policy_decisions']}")
        print(f"Duplicate side effects: {report['duplicate_side_effects']}")
        print(f"Approval bypasses: {report['approval_bypasses']}")
        print()
        print("RELEASE ALLOWED" if report["release_allowed"] else "RELEASE BLOCKED")
    return 0 if report["release_allowed"] else 1


def _replay(args: argparse.Namespace) -> int:
    trail = SQLiteActionLedger(args.ledger).audit_trail(args.run_id)
    if trail is None:
        print("Run not found")
        return 1
    print(json.dumps(trail, ensure_ascii=False, indent=2))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="agenttrust",
        description="Guard risky agent actions with policy, approval, idempotency, and replay.",
    )
    subparsers = parser.add_subparsers(dest="command", required=True)

    evaluate = subparsers.add_parser(
        "eval", help="evaluate an agent release against scenarios"
    )
    evaluate.add_argument("scenarios", type=Path)
    evaluate.add_argument("--policy", type=Path, required=True)
    evaluate.add_argument("--json", action="store_true")
    evaluate.set_defaults(handler=_eval)

    replay = subparsers.add_parser("replay", help="print an immutable run event view")
    replay.add_argument("run_id")
    replay.add_argument("--ledger", type=Path, required=True)
    replay.set_defaults(handler=_replay)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
