"""AgentTrustOps command line entry point."""

from __future__ import annotations

import argparse
import json
import os
from pathlib import Path

from .audit import (
    export_audit_bundle,
    generate_ed25519_keypair,
    read_audit_bundle,
    verify_audit_bundle,
    write_audit_bundle,
)
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


def _audit_keygen(args: argparse.Namespace) -> int:
    report = generate_ed25519_keypair(args.private_key, args.public_key)
    print(json.dumps(report, indent=2))
    return 0


def _open_operational_ledger(args: argparse.Namespace):
    postgres_dsn = os.getenv(args.postgres_dsn_env)
    if postgres_dsn:
        from .postgres import PostgresActionLedger

        return PostgresActionLedger(postgres_dsn)
    if args.ledger is not None:
        return SQLiteActionLedger(args.ledger)
    raise SystemExit(
        "command requires --ledger or the PostgreSQL DSN environment variable"
    )


def _audit_export(args: argparse.Namespace) -> int:
    ledger = _open_operational_ledger(args)
    try:
        document = export_audit_bundle(
            ledger,
            tenant_id=args.tenant,
            limit=args.limit,
            signing_key_path=args.signing_key,
        )
        write_audit_bundle(args.output, document)
    finally:
        ledger.close()
    print(
        json.dumps(
            {
                "output": str(args.output),
                "run_count": document["payload"]["run_count"],
                "digest": document["proof"]["digest"],
                "signed": document["proof"]["signature"] is not None,
            },
            indent=2,
        )
    )
    return 0


def _audit_verify(args: argparse.Namespace) -> int:
    try:
        report = verify_audit_bundle(
            read_audit_bundle(args.bundle),
            trusted_public_key_path=args.public_key,
        )
    except ValueError as error:
        print(json.dumps({"valid": False, "error": str(error)}, indent=2))
        return 2
    print(json.dumps(report, indent=2))
    return 0


def _build_identity_verifier(args: argparse.Namespace):
    from .auth import OIDCJWTVerifier, StaticTokenVerifier

    oidc = {
        "issuer": args.oidc_issuer or os.getenv("AGENTTRUSTOPS_OIDC_ISSUER"),
        "audience": args.oidc_audience or os.getenv("AGENTTRUSTOPS_OIDC_AUDIENCE"),
        "jwks_url": args.oidc_jwks_url or os.getenv("AGENTTRUSTOPS_OIDC_JWKS_URL"),
    }
    configured = [name for name, value in oidc.items() if value]
    if args.identities is not None and configured:
        raise SystemExit("choose exactly one auth mode: --identities or OIDC")
    if args.identities is not None:
        return StaticTokenVerifier.from_json(args.identities)
    if configured and len(configured) != len(oidc):
        missing = ", ".join(name for name, value in oidc.items() if not value)
        raise SystemExit(f"incomplete OIDC configuration; missing: {missing}")
    if configured:
        return OIDCJWTVerifier(
            issuer=str(oidc["issuer"]),
            audience=str(oidc["audience"]),
            jwks_url=str(oidc["jwks_url"]),
            tenant_claim=args.oidc_tenant_claim,
            roles_claim=args.oidc_roles_claim,
            allow_insecure_http=args.oidc_allow_insecure_http,
        )
    raise SystemExit(
        "authentication is required: use --identities for a local demo or configure OIDC"
    )


def _serve(args: argparse.Namespace) -> int:
    try:
        import uvicorn
    except ModuleNotFoundError as error:
        raise SystemExit(
            "The API extra is required: pip install 'agenttrustops[api]'"
        ) from error

    from .api import create_app
    from .models import ActionContext
    from .registry import ActionRegistry

    identity_verifier = _build_identity_verifier(args)
    policy = (
        load_json(args.policy)
        if args.policy is not None
        else {
            "release": "refund-control-plane-v0.3",
            "selection_mode": "as_of_order",
            "approval_enabled": True,
            "require_evidence": True,
            "enforce_roles": True,
            "allowed_roles": ["refund_agent", "refund_admin"],
        }
    )
    ledger = _open_operational_ledger(args)
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
        identity_verifier,
        context_resolver=resolve_refund_evidence,
    )
    try:
        uvicorn.run(app, host=args.host, port=args.port, access_log=False)
    finally:
        ledger.close()
    return 0


def _demo(args: argparse.Namespace) -> int:
    report = run_refund_demo(args.output_dir)
    if args.json:
        print(json.dumps(report, ensure_ascii=False, indent=2))
        return 0
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
    demo.add_argument("--json", action="store_true")
    demo.set_defaults(handler=_demo)

    keygen = subparsers.add_parser(
        "audit-keygen", help="create a non-overwriting Ed25519 audit keypair"
    )
    keygen.add_argument("--private-key", type=Path, required=True)
    keygen.add_argument("--public-key", type=Path, required=True)
    keygen.set_defaults(handler=_audit_keygen)

    audit_export = subparsers.add_parser(
        "audit-export", help="export redacted, optionally signed audit evidence"
    )
    audit_export.add_argument("--ledger", type=Path)
    audit_export.add_argument(
        "--postgres-dsn-env", default="AGENTTRUSTOPS_POSTGRES_DSN"
    )
    audit_export.add_argument("--tenant")
    audit_export.add_argument("--limit", type=int, default=1000)
    audit_export.add_argument("--signing-key", type=Path)
    audit_export.add_argument("--output", type=Path, required=True)
    audit_export.set_defaults(handler=_audit_export)

    audit_verify = subparsers.add_parser(
        "audit-verify", help="verify an audit bundle without ledger access"
    )
    audit_verify.add_argument("bundle", type=Path)
    audit_verify.add_argument("--public-key", type=Path)
    audit_verify.set_defaults(handler=_audit_verify)

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
    serve.add_argument(
        "--identities",
        type=Path,
        help="permission-restricted static identities for local demos only",
    )
    serve.add_argument("--oidc-issuer")
    serve.add_argument("--oidc-audience")
    serve.add_argument("--oidc-jwks-url")
    serve.add_argument("--oidc-tenant-claim", default="tenant_id")
    serve.add_argument("--oidc-roles-claim", default="roles")
    serve.add_argument("--oidc-allow-insecure-http", action="store_true")
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
