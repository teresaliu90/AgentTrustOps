"""Dependency-free LangGraph node adapter.

The returned callable follows LangGraph's state-in/partial-state-out convention
without importing LangGraph. A graph can branch on ``status`` to pause for
approval or route ``unknown`` runs to reconciliation.
"""

from __future__ import annotations

from collections.abc import Awaitable, Callable, Mapping
from typing import Any

from ..models import ActionContext
from ..runtime import TrustedAction

State = Mapping[str, Any]
ContextFactory = Callable[[State], ActionContext]
ArgumentsFactory = Callable[[State], dict[str, Any]]
IdempotencyKeyFactory = Callable[[State], str]


def as_langgraph_node(
    action: TrustedAction,
    *,
    context: ContextFactory,
    idempotency_key: IdempotencyKeyFactory,
    arguments: ArgumentsFactory | None = None,
    result_key: str = "agenttrustops",
) -> Callable[[State], dict[str, Any]] | Callable[[State], Awaitable[dict[str, Any]]]:
    """Adapt a trusted action into a LangGraph-compatible node callable."""

    if not result_key.strip():
        raise ValueError("result_key cannot be empty")
    arguments_factory = arguments or _default_arguments

    if action.is_async:

        async def async_node(state: State) -> dict[str, Any]:
            result = await action.invoke_request_async(
                context=context(state),
                arguments=arguments_factory(state),
                idempotency_key=idempotency_key(state),
            )
            return {result_key: result.to_public_dict()}

        return async_node

    def sync_node(state: State) -> dict[str, Any]:
        result = action.invoke_request(
            context=context(state),
            arguments=arguments_factory(state),
            idempotency_key=idempotency_key(state),
        )
        return {result_key: result.to_public_dict()}

    return sync_node


def _default_arguments(state: State) -> dict[str, Any]:
    value = state.get("arguments")
    if not isinstance(value, Mapping):
        raise TypeError("state['arguments'] must be a mapping")
    return dict(value)
