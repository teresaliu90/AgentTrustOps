"""MCP-host adapter that keeps authority outside model-controlled arguments."""

from __future__ import annotations

import asyncio
from collections.abc import Callable, Mapping
from typing import Any

from ..models import ActionContext
from ..runtime import TrustedAction

MCPContextResolver = Callable[[], ActionContext]
MCPIdempotencyResolver = Callable[[Mapping[str, Any]], str]


def as_mcp_tool_handler(
    action: TrustedAction,
    *,
    context: MCPContextResolver,
    idempotency_key: MCPIdempotencyResolver,
) -> Callable[[Mapping[str, Any]], Any]:
    """Return an async handler suitable for registration with an MCP server.

    ``context`` should read verified principal data from server middleware or a
    request-local ContextVar. The model-visible arguments never include actor,
    tenant, roles, evidence, credentials, or the idempotency key.
    """

    async def handler(arguments: Mapping[str, Any]) -> dict[str, Any]:
        if not isinstance(arguments, Mapping):
            raise TypeError("MCP action arguments must be a mapping")
        copied_arguments = dict(arguments)
        resolved_context = context()
        if not isinstance(resolved_context, ActionContext):
            raise TypeError("context resolver must return ActionContext")
        key = idempotency_key(copied_arguments).strip()
        if not key:
            raise ValueError("trusted idempotency resolver returned an empty key")
        if action.is_async:
            result = await action.invoke_request_async(
                context=resolved_context,
                arguments=copied_arguments,
                idempotency_key=key,
            )
        else:
            result = await asyncio.to_thread(
                action.invoke_request,
                context=resolved_context,
                arguments=copied_arguments,
                idempotency_key=key,
            )
        return result.to_public_dict()

    handler.__name__ = action.name
    handler.__doc__ = action.function.__doc__ or "Governed MCP action"
    return handler


def register_fastmcp_action(
    server: Any,
    action: TrustedAction,
    *,
    context: MCPContextResolver,
    idempotency_key: MCPIdempotencyResolver,
    name: str | None = None,
    description: str | None = None,
) -> Callable[[Mapping[str, Any]], Any]:
    """Register a governed handler with a FastMCP-compatible server.

    Install ``agenttrustops[mcp]``. The returned handler is useful for direct
    contract testing; registration uses structured output and a single
    model-visible ``arguments`` object.
    """

    add_tool = getattr(server, "add_tool", None)
    if not callable(add_tool):
        raise TypeError("server must provide a callable add_tool method")
    handler = as_mcp_tool_handler(
        action,
        context=context,
        idempotency_key=idempotency_key,
    )
    add_tool(
        handler,
        name=name or action.name,
        description=description or handler.__doc__,
        structured_output=True,
    )
    return handler
