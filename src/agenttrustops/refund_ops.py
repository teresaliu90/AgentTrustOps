"""Synthetic RefundOps reference application for the AgentTrustOps SDK."""

from __future__ import annotations

import json
import sqlite3
from contextlib import closing
from dataclasses import dataclass
from datetime import date
from pathlib import Path
from tempfile import TemporaryDirectory
from typing import Any

from .ledger import SQLiteActionLedger
from .models import ActionContext, ActionStatus, PolicyDecision, PolicyOutcome
from .runtime import TrustedAction, trusted_action


@dataclass(frozen=True, slots=True)
class Order:
    order_id: str
    tenant_id: str
    ordered_at: date
    total: float


@dataclass(frozen=True, slots=True)
class RefundPolicyVersion:
    version: str
    effective_from: date
    auto_approve_limit: float


class OrderStore:
    """Deterministic synthetic orders; no customer or employer data."""

    def __init__(self):
        self._orders = {
            "O-LOW": Order("O-LOW", "default", date(2026, 8, 1), 200.0),
            "O-HIGH": Order("O-HIGH", "default", date(2026, 8, 1), 800.0),
            "O-HIST": Order("O-HIST", "default", date(2026, 5, 20), 400.0),
            "O-FOREIGN": Order("O-FOREIGN", "beta", date(2026, 8, 1), 100.0),
        }

    def get(self, order_id: str) -> Order | None:
        return self._orders.get(order_id)


class RefundStore:
    """Synthetic side-effect store with a second uniqueness boundary."""

    def __init__(self, path: str | Path):
        self.path = str(path)
        with closing(sqlite3.connect(self.path)) as connection, connection:
            connection.execute(
                """
                CREATE TABLE IF NOT EXISTS refunds (
                    refund_id INTEGER PRIMARY KEY AUTOINCREMENT,
                    order_id TEXT NOT NULL UNIQUE,
                    amount REAL NOT NULL
                )
                """
            )

    def execute(self, order_id: str, amount: float) -> dict[str, Any]:
        with closing(sqlite3.connect(self.path)) as connection, connection:
            cursor = connection.execute(
                "INSERT INTO refunds (order_id, amount) VALUES (?, ?)",
                (order_id, amount),
            )
            return {
                "refund_id": cursor.lastrowid,
                "order_id": order_id,
                "amount": amount,
            }

    def count(self, order_id: str | None = None) -> int:
        with closing(sqlite3.connect(self.path)) as connection:
            if order_id is None:
                row = connection.execute("SELECT COUNT(*) FROM refunds").fetchone()
            else:
                row = connection.execute(
                    "SELECT COUNT(*) FROM refunds WHERE order_id = ?", (order_id,)
                ).fetchone()
        return int(row[0]) if row else 0


class RefundPolicy:
    """Reference business policy with a deliberately configurable unsafe mode."""

    versions = (
        RefundPolicyVersion("refund-v2026-01", date(2026, 1, 1), 500.0),
        RefundPolicyVersion("refund-v2026-07", date(2026, 7, 1), 300.0),
    )

    def __init__(self, orders: OrderStore, config: dict[str, Any]):
        self.orders = orders
        self.config = config

    def evaluate(
        self,
        action_name: str,
        arguments: dict[str, Any],
        context: ActionContext,
    ) -> PolicyDecision:
        order_id = str(arguments.get("order_id", ""))
        order = self.orders.get(order_id)
        if action_name != "execute_refund" or order is None:
            return self._deny("order does not exist", "unresolved")

        policy = self._select_policy(order.ordered_at)
        facts = {
            "order_date": order.ordered_at.isoformat(),
            "selected_policy": policy.version,
            "auto_approve_limit": policy.auto_approve_limit,
        }
        if order.tenant_id != context.tenant_id:
            return self._deny(
                "order is outside the tenant boundary", policy.version, facts
            )

        allowed_roles = set(
            self.config.get("allowed_roles", ["refund_agent", "refund_admin"])
        )
        if self.config.get("enforce_roles", True) and not (
            allowed_roles & set(context.roles)
        ):
            return self._deny("actor role is not allowed", policy.version, facts)

        required_evidence = {f"ORDER:{order_id}", f"LOGISTICS:{order_id}"}
        if self.config.get("require_evidence", True) and not required_evidence.issubset(
            context.evidence
        ):
            return self._deny(
                "required order and logistics evidence is incomplete",
                policy.version,
                facts,
            )

        try:
            amount = float(arguments["amount"])
        except (KeyError, TypeError, ValueError):
            return self._deny("refund amount is invalid", policy.version, facts)
        if amount <= 0 or amount > order.total:
            return self._deny(
                "refund amount exceeds the eligible order total", policy.version, facts
            )

        if (
            self.config.get("approval_enabled", True)
            and amount > policy.auto_approve_limit
        ):
            return PolicyDecision(
                PolicyOutcome.APPROVAL_REQUIRED,
                f"amount exceeds {policy.auto_approve_limit:.2f} approval threshold",
                policy.version,
                facts,
            )
        return PolicyDecision(
            PolicyOutcome.ALLOW,
            "policy, identity, evidence, and amount checks passed",
            policy.version,
            facts,
        )

    def _select_policy(self, ordered_at: date) -> RefundPolicyVersion:
        if self.config.get("selection_mode", "as_of_order") == "latest":
            return self.versions[-1]
        eligible = [
            version for version in self.versions if version.effective_from <= ordered_at
        ]
        if not eligible:
            raise ValueError("no refund policy is effective for the order date")
        return eligible[-1]

    @staticmethod
    def _deny(
        reason: str,
        policy_version: str,
        facts: dict[str, Any] | None = None,
    ) -> PolicyDecision:
        return PolicyDecision(PolicyOutcome.DENY, reason, policy_version, facts or {})


def build_refund_action(
    *,
    ledger_path: str | Path,
    refund_path: str | Path,
    policy_config: dict[str, Any],
) -> tuple[TrustedAction, RefundStore]:
    ledger = SQLiteActionLedger(ledger_path)
    orders = OrderStore()
    refunds = RefundStore(refund_path)
    policy = RefundPolicy(orders, policy_config)

    @trusted_action(
        ledger=ledger,
        policy=policy,
        risk="financial",
        idempotency_key=lambda arguments, context: (
            f"refund:{context.tenant_id}:{arguments['order_id']}"
        ),
    )
    def execute_refund(order_id: str, amount: float) -> dict[str, Any]:
        return refunds.execute(order_id, amount)

    return execute_refund, refunds


def load_json(path: str | Path) -> dict[str, Any]:
    return json.loads(Path(path).read_text(encoding="utf-8"))


def evaluate_release(
    scenarios_path: str | Path,
    policy_path: str | Path,
) -> dict[str, Any]:
    scenarios_document = load_json(scenarios_path)
    policy_document = load_json(policy_path)
    metrics = {
        "release": policy_document["release"],
        "scenarios": 0,
        "wrong_decisions": 0,
        "wrong_policy_decisions": 0,
        "approval_bypasses": 0,
        "duplicate_side_effects": 0,
        "results": [],
    }
    with TemporaryDirectory(prefix="agenttrust-eval-") as directory:
        for index, scenario in enumerate(scenarios_document["scenarios"]):
            action, refunds = build_refund_action(
                ledger_path=Path(directory) / f"ledger-{index}.db",
                refund_path=Path(directory) / f"refunds-{index}.db",
                policy_config=policy_document,
            )
            context = ActionContext(
                actor_id=scenario.get("actor_id", "synthetic-agent"),
                tenant_id=scenario.get("tenant_id", "default"),
                roles=tuple(scenario.get("roles", [])),
                evidence=tuple(scenario.get("evidence", [])),
            )
            result = action.invoke(
                context=context,
                order_id=scenario["order_id"],
                amount=scenario["amount"],
            )
            for _ in range(int(scenario.get("repeat", 1)) - 1):
                result = action.invoke(
                    context=context,
                    order_id=scenario["order_id"],
                    amount=scenario["amount"],
                )

            expected_status = scenario["expected_status"]
            expected_policy = scenario.get("expected_policy")
            decision_correct = result.status.value == expected_status
            policy_correct = (
                expected_policy is None or result.policy_version == expected_policy
            )
            if not decision_correct:
                metrics["wrong_decisions"] += 1
            if not policy_correct:
                metrics["wrong_policy_decisions"] += 1
            if (
                expected_status == ActionStatus.PENDING_APPROVAL.value
                and result.status is ActionStatus.COMPLETED
            ):
                metrics["approval_bypasses"] += 1
            refund_count = refunds.count(scenario["order_id"])
            if refund_count > 1:
                metrics["duplicate_side_effects"] += refund_count - 1
            metrics["scenarios"] += 1
            metrics["results"].append(
                {
                    "id": scenario["id"],
                    "expected_status": expected_status,
                    "actual_status": result.status.value,
                    "expected_policy": expected_policy,
                    "actual_policy": result.policy_version,
                    "refund_count": refund_count,
                    "passed": decision_correct and policy_correct and refund_count <= 1,
                }
            )

    blocking_metrics = (
        "wrong_decisions",
        "wrong_policy_decisions",
        "approval_bypasses",
        "duplicate_side_effects",
    )
    metrics["release_allowed"] = all(metrics[key] == 0 for key in blocking_metrics)
    return metrics
