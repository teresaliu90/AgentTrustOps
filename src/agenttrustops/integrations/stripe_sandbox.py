"""Stripe Sandbox payment adapter and provider reconciliation probe.

The integration refuses live keys. It is evidence for an integration boundary,
not a production payment connector or Stripe certification.
"""

from __future__ import annotations

from collections.abc import Mapping
from datetime import UTC, datetime, timedelta
from typing import Any, Protocol, cast

from ..models import ActionExecutionContext
from ..providers import (
    ProviderLookup,
    ProviderLookupError,
    ProviderObservation,
    ProviderOutcome,
)
from ..runtime import IndeterminateOutcome

_COMMITTED_STATUSES = {"succeeded"}
_NOT_COMMITTED_STATUSES = {"canceled", "requires_payment_method"}
_PENDING_STATUSES = {
    "processing",
    "requires_action",
    "requires_capture",
    "requires_confirmation",
}
_MAX_SAFE_REPLAY_AGE = timedelta(hours=23)


class _PaymentIntentsResource(Protocol):
    def create(
        self,
        params: dict[str, Any],
        options: dict[str, str],
    ) -> Any: ...


class StripeSandboxPaymentFailed(RuntimeError):
    """A Stripe Sandbox request definitively failed before payment committed."""


class StripeSandboxPaymentAdapter:
    """Create card PaymentIntents with the governed AgentTrustOps key."""

    provider_name = "stripe-sandbox"

    def __init__(
        self,
        secret_key: str,
        *,
        payment_method: str = "pm_card_visa",
        return_url: str = "https://example.invalid/agenttrustops/stripe-return",
        fault_after_provider_response: bool = False,
        payment_intents: _PaymentIntentsResource | None = None,
        ambiguous_error_types: tuple[type[BaseException], ...] | None = None,
    ):
        key = secret_key.strip()
        if not key.startswith(("sk_test_", "rk_test_")):
            raise ValueError("Stripe Sandbox integration requires a test-mode key")
        if not payment_method.strip().startswith("pm_"):
            raise ValueError("Stripe Sandbox payment_method must be a PaymentMethod ID")
        if not return_url.strip().startswith("https://"):
            raise ValueError("Stripe Sandbox return_url must use HTTPS")
        if payment_intents is None:
            payment_intents, discovered_errors = _stripe_payment_intents(key)
            if ambiguous_error_types is None:
                ambiguous_error_types = discovered_errors
        self._payment_intents = payment_intents
        self._ambiguous_error_types = ambiguous_error_types or ()
        self.payment_method = payment_method.strip()
        self.return_url = return_url.strip()
        self.fault_after_provider_response = fault_after_provider_response

    def charge(
        self,
        *,
        invoice_id: str,
        amount: int,
        currency: str,
        execution: ActionExecutionContext,
    ) -> dict[str, Any]:
        """Create and confirm a synthetic card payment in Stripe Sandbox."""

        params = self._params(
            run_id=execution.run_id,
            invoice_id=invoice_id,
            amount=amount,
            currency=currency,
        )
        try:
            intent = self._payment_intents.create(
                params,
                {"idempotency_key": _stripe_idempotency_key(execution.idempotency_key)},
            )
        except self._ambiguous_error_types as error:
            raise IndeterminateOutcome(
                "Stripe Sandbox response was uncertain"
            ) from error
        except Exception as error:
            raise StripeSandboxPaymentFailed(
                f"Stripe Sandbox rejected the request: {type(error).__name__}"
            ) from error
        try:
            normalized = self._validated_intent(intent, params)
        except Exception as error:
            raise IndeterminateOutcome(
                "Stripe Sandbox response could not be verified"
            ) from error
        if self.fault_after_provider_response:
            raise IndeterminateOutcome(
                "fault injection after Stripe Sandbox returned a result"
            )
        status = str(normalized["status"])
        if status in _COMMITTED_STATUSES:
            return _safe_result(normalized)
        if status in _PENDING_STATUSES:
            raise IndeterminateOutcome("Stripe Sandbox payment remains pending")
        if status in _NOT_COMMITTED_STATUSES:
            raise StripeSandboxPaymentFailed(
                f"Stripe Sandbox payment did not commit: {status}"
            )
        raise IndeterminateOutcome("Stripe Sandbox returned an unknown payment status")

    def inspect(self, request: ProviderLookup) -> ProviderObservation:
        """Replay the same sandbox POST under Stripe's idempotency contract."""

        try:
            created_at = datetime.fromisoformat(request.created_at).astimezone(UTC)
            age = datetime.now(UTC) - created_at
            if age < timedelta(0) or age >= _MAX_SAFE_REPLAY_AGE:
                raise ProviderLookupError(
                    "Stripe idempotency replay window is no longer safe"
                )
            params = self._params(
                run_id=request.run_id,
                invoice_id=str(request.arguments["invoice_id"]),
                amount=int(request.arguments["amount"]),
                currency=str(request.arguments["currency"]),
            )
            intent = self._payment_intents.create(
                params,
                {"idempotency_key": _stripe_idempotency_key(request.idempotency_key)},
            )
            normalized = self._validated_intent(intent, params)
        except ProviderLookupError:
            raise
        except Exception as error:
            raise ProviderLookupError(
                "Stripe Sandbox could not return an authoritative result"
            ) from error

        status = str(normalized["status"])
        if status in _COMMITTED_STATUSES:
            outcome = ProviderOutcome.COMMITTED
        elif status in _NOT_COMMITTED_STATUSES:
            outcome = ProviderOutcome.NOT_COMMITTED
        elif status in _PENDING_STATUSES:
            outcome = ProviderOutcome.PENDING
        else:
            raise ProviderLookupError("Stripe Sandbox returned an unknown status")
        return ProviderObservation(
            outcome,
            f"Stripe Sandbox PaymentIntent status is {status}",
            reference=str(normalized["id"]),
            safe_result=_safe_result(normalized),
        )

    def _params(
        self,
        *,
        run_id: str,
        invoice_id: str,
        amount: int,
        currency: str,
    ) -> dict[str, Any]:
        invoice = invoice_id.strip()
        normalized_currency = currency.strip().lower()
        if not invoice or len(invoice) > 100:
            raise ValueError("synthetic invoice_id must contain 1 to 100 characters")
        if not isinstance(amount, int) or isinstance(amount, bool) or amount < 50:
            raise ValueError("Stripe Sandbox amount must be an integer of at least 50")
        if len(normalized_currency) != 3 or not normalized_currency.isalpha():
            raise ValueError("currency must be a three-letter code")
        return {
            "amount": amount,
            "currency": normalized_currency,
            "payment_method": self.payment_method,
            "payment_method_types": ["card"],
            "confirm": True,
            "capture_method": "automatic",
            "return_url": self.return_url,
            "metadata": {
                "agenttrustops_run_id": run_id,
                "synthetic_invoice_id": invoice,
            },
        }

    @staticmethod
    def _validated_intent(intent: Any, params: dict[str, Any]) -> dict[str, Any]:
        normalized = {
            "id": _field(intent, "id"),
            "status": _field(intent, "status"),
            "amount": _field(intent, "amount"),
            "currency": _field(intent, "currency"),
            "livemode": _field(intent, "livemode"),
            "metadata": _field(intent, "metadata"),
        }
        if normalized["livemode"] is not False:
            raise RuntimeError("Stripe response was not from Sandbox mode")
        if normalized["amount"] != params["amount"]:
            raise RuntimeError(
                "Stripe response amount does not match the governed request"
            )
        if normalized["currency"] != params["currency"]:
            raise RuntimeError(
                "Stripe response currency does not match the governed request"
            )
        metadata = normalized["metadata"]
        if not isinstance(metadata, Mapping) or any(
            metadata.get(key) != value for key, value in params["metadata"].items()
        ):
            raise RuntimeError(
                "Stripe response metadata does not match the governed run"
            )
        if not str(normalized["id"]).startswith("pi_"):
            raise RuntimeError("Stripe response has no valid PaymentIntent ID")
        return normalized


class StripeSandboxPaymentProbe:
    """AgentTrustOps provider probe backed by the same Stripe adapter."""

    name = StripeSandboxPaymentAdapter.provider_name

    def __init__(self, adapter: StripeSandboxPaymentAdapter):
        self.adapter = adapter

    def lookup(self, request: ProviderLookup) -> ProviderObservation:
        return self.adapter.inspect(request)


def _field(value: Any, name: str) -> Any:
    if isinstance(value, Mapping):
        return value.get(name)
    return getattr(value, name, None)


def _safe_result(intent: Mapping[str, Any]) -> dict[str, Any]:
    return {
        "payment_intent_id": str(intent["id"]),
        "status": str(intent["status"]),
        "amount": int(intent["amount"]),
        "currency": str(intent["currency"]),
        "livemode": False,
    }


def _stripe_idempotency_key(value: str) -> str:
    key = value.strip()
    if not 1 <= len(key) <= 255:
        raise ValueError("Stripe idempotency key must contain 1 to 255 characters")
    return key


def _stripe_payment_intents(
    secret_key: str,
) -> tuple[_PaymentIntentsResource, tuple[type[BaseException], ...]]:
    try:
        import stripe
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "Stripe Sandbox support requires: pip install 'agenttrustops[stripe]'"
        ) from error
    client = stripe.StripeClient(secret_key)
    ambiguous: tuple[type[BaseException], ...] = (
        stripe.APIConnectionError,
        stripe.APIError,
        stripe.RateLimitError,
    )
    return cast(_PaymentIntentsResource, client.v1.payment_intents), ambiguous
