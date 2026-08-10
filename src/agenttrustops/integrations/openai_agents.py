"""OpenAI Agents SDK adapter for TrustedAction.

The model supplies action arguments only. Identity, tenant, roles, evidence,
and idempotency are resolved from the trusted Agents SDK runtime context.
"""

from __future__ import annotations

import asyncio
import json
from collections.abc import Callable, Mapping
from copy import deepcopy
from typing import Any

from ..models import ActionContext
from ..runtime import TrustedAction

OpenAIContextResolver = Callable[[Any, Mapping[str, Any]], ActionContext]
OpenAIIdempotencyResolver = Callable[[Any, Mapping[str, Any]], str]


def as_openai_agents_tool(
    action: TrustedAction,
    *,
    params_json_schema: Mapping[str, Any],
    context: OpenAIContextResolver,
    idempotency_key: OpenAIIdempotencyResolver,
    name: str | None = None,
    description: str | None = None,
) -> Any:
    """Create an Agents SDK ``FunctionTool`` backed by a governed action.

    Install ``agenttrustops[openai]``. Resolver inputs receive the Agents SDK
    ``ToolContext`` plus parsed model arguments. Resolvers must derive identity
    and the retry key from trusted application state, never from model fields.
    """

    try:
        from agents import FunctionTool
    except ModuleNotFoundError as error:
        raise ModuleNotFoundError(
            "OpenAI Agents integration requires: pip install 'agenttrustops[openai]'"
        ) from error

    schema = deepcopy(dict(params_json_schema))
    if schema.get("type") != "object":
        raise ValueError("params_json_schema must describe a JSON object")
    if not (name or action.name).strip():
        raise ValueError("tool name cannot be empty")

    async def invoke(tool_context: Any, raw_arguments: str) -> str:
        parsed = json.loads(raw_arguments)
        if not isinstance(parsed, dict):
            raise TypeError("tool arguments must decode to a JSON object")
        arguments = dict(parsed)
        resolved_context = context(tool_context, arguments)
        if not isinstance(resolved_context, ActionContext):
            raise TypeError("context resolver must return ActionContext")
        key = idempotency_key(tool_context, arguments).strip()
        if not key:
            raise ValueError("trusted idempotency resolver returned an empty key")
        if action.is_async:
            result = await action.invoke_request_async(
                context=resolved_context,
                arguments=arguments,
                idempotency_key=key,
            )
        else:
            result = await asyncio.to_thread(
                action.invoke_request,
                context=resolved_context,
                arguments=arguments,
                idempotency_key=key,
            )
        return json.dumps(
            result.to_public_dict(),
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )

    return FunctionTool(
        name=name or action.name,
        description=description
        or (action.function.__doc__ or "Governed action").strip(),
        params_json_schema=schema,
        on_invoke_tool=invoke,
    )
