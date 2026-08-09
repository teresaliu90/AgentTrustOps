"""AgentTrustOps command line entry point."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .ledger import SQLiteActionLedger
from .observability import collect_operational_snapshot, render_prometheus
from .refund_ops import (
    OrderStore,
    build_refund_action_on_ledger,
    evaluate_release,
    load_json,
    run_refund_demo,
)


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
    ledger = SQLiteActionLedger(args.ledger)
    trail = ledger.audit_trail(args.run_id)
    if trail is None:
        print("Run not found")
        return 1
    print(json.dumps(trail, ensure_ascii=False, indent=2))
    return 0


def _doctor(args: argparse.Namespace) -> int:
    ledger = SQLiteActionLedger(args.ledger)
    snapshot = collect_operational_snapshot(
        ledger,
        tenant_id=args.tenant,
        verify_integrity=True,
        integrity_limit=args.limit,
    )
    report = snapshot.to_dict()
    report["healthy"] = report["integrity"]["invalid"] == 0
    print(json.dumps(report, ensure_ascii=False, indent=2))
    return 0 if report["healthy"] else 2


def _metrics(args: argparse.Namespace) -> int:
    ledger = SQLiteActionLedger(args.ledger)
    snapshot = collect_operational_snapshot(
        ledger,
        tenant_id=args.tenant,
        verify_integrity=args.verify_integrity,
    )
    print(render_prometheus(snapshot), end="")
    return 0


def _recover(args: argparse.Namespace) -> int:
    ledger = SQLiteActionLedger(args.ledger)
    expired = ledger.expire_approvals(tenant_id=args.tenant)
    recovered = ledger.recover_expired_executions(tenant_id=args.tenant)
    print(
        json.dumps(
            {
                "recovered_executions": len(recovered),
                "execution_run_ids": recovered,
                "expired_approvals": len(expired),
                "approval_run_ids": expired,
            },
            indent=2,
        )
    )
    return 0


def _serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ModuleNotFoundError as error:
        raise SystemExit(
            "The API extra is required: pip install 'agenttrustops[api]'"
        ) from error

    from .api import create_app
    from .auth import StaticTokenVerifier
    from .models import ActionContext
    from .registry import ActionRegistry

    policy = (
        load_json(args.policy)
        if args.policy is not None
        else {
            "release": "refund-control-plane-v0.2",
            "selection_mode": "as_of_order",
            "approval_enabled": True,
            "require_evidence": True,
            "enforce_roles": True,
            "allowed_roles": ["refund_agent", "refund_admin"],
        }
    )
    postgres_dsn = os.getenv(args.postgres_dsn_env)
    ledger: SQLiteActionLedger
    if postgres_dsn:
        from .postgres import PostgresActionLedger

        ledger = PostgresActionLedger(postgres_dsn)
    elif args.ledger is not None:
        ledger = SQLiteActionLedger(args.ledger)
    else:
        raise SystemExit(
            "serve requires --ledger or the PostgreSQL DSN environment variable"
        )
    action, _ = build_refund_action_on_ledger(
        ledger=ledger,
        refund_path=args.refunds,
        policy_config=policy,
    )
    orders = OrderStore()

    def resolve_refund_evidence(principal, action_name, arguments, evidence_refs):
        if action_name != "execute_refund":
            raise ValueError("unsupported action")
        unknown_refs = set(evidence_refs) - {"order-record", "logistics-record"}
        if unknown_refs:
            raise ValueError("unknown evidence reference")
        order_id = str(arguments.get("order_id", ""))
        order = orders.get(order_id)
        if order is None or order.tenant_id != principal.tenant_id:
            evidence: tuple[str, ...] = ()
        else:
            evidence = tuple(
                claim
                for reference, claim in (
                    ("order-record", f"ORDER:{order_id}"),
                    ("logistics-record", f"LOGISTICS:{order_id}"),
                )
                if reference in evidence_refs
            )
        return ActionContext(
            actor_id=principal.actor_id,
            tenant_id=principal.tenant_id,
            roles=principal.roles,
            evidence=evidence,
            metadata={"evidence_source": "synthetic-refund-demo"},
        )

    app = create_app(
        ActionRegistry(action.ledger, [action]),
        StaticTokenVerifier.from_json(args.identities),
        context_resolver=resolve_refund_evidence,
    )
    uvicorn.run(app, host=args.host, port=args.port, access_log=False)
    return 0


def _demo(args: argparse.Namespace) -> int:
    report = run_refund_demo(args.output_dir)
    print("RefundOps approval walkthrough")
    print(f"Run ID: {report['run_id']}")
    print(f"States: {' -> '.join(report['states'])}")
    print(f"Refund side effects: {report['refund_count']}")
    print(f"Events: {' -> '.join(report['events'])}")
    print(f"Ledger: {report['ledger']}")
    print()
    print(f"Replay: agenttrust replay {report['run_id']} --ledger {report['ledger']}")
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

    replay = subparsers.add_parser("replay", help="print a redacted run event view")
    replay.add_argument("run_id")
    replay.add_argument("--ledger", type=Path, required=True)
    replay.set_defaults(handler=_replay)

    demo = subparsers.add_parser(
        "demo", help="persist an approval, execution, and replay walkthrough"
    )
    demo.add_argument("--output-dir", type=Path, default=Path("demo-runs"))
    demo.set_defaults(handler=_demo)

    doctor = subparsers.add_parser(
        "doctor", help="verify the schema and tamper-evident event chains"
    )
    doctor.add_argument("--ledger", type=Path, required=True)
    doctor.add_argument("--tenant")
    doctor.add_argument("--limit", type=int, default=10000)
    doctor.set_defaults(handler=_doctor)

    metrics = subparsers.add_parser(
        "metrics", help="render privacy-safe durable Prometheus metrics"
    )
    metrics.add_argument("--ledger", type=Path, required=True)
    metrics.add_argument("--tenant")
    metrics.add_argument("--verify-integrity", action="store_true")
    metrics.set_defaults(handler=_metrics)

    recover = subparsers.add_parser(
        "recover", help="move expired executions to unknown for reconciliation"
    )
    recover.add_argument("--ledger", type=Path, required=True)
    recover.add_argument("--tenant")
    recover.set_defaults(handler=_recover)

    serve = subparsers.add_parser(
        "serve", help="run the authenticated RefundOps reference control plane"
    )
    serve.add_argument("--ledger", type=Path)
    serve.add_argument(
        "--postgres-dsn-env",
        default="AGENTTRUSTOPS_POSTGRES_DSN",
        help="environment variable containing a PostgreSQL DSN",
    )
    serve.add_argument("--refunds", type=Path, required=True)
    serve.add_argument("--identities", type=Path, required=True)
    serve.add_argument("--policy", type=Path)
    serve.add_argument("--host", default="127.0.0.1")
    serve.add_argument("--port", type=int, default=8787)
    serve.set_defaults(handler=_serve)
    return parser


def main(argv: list[str] | None = None) -> int:
    args = build_parser().parse_args(argv)
    return int(args.handler(args))


if __name__ == "__main__":
    raise SystemExit(main())
