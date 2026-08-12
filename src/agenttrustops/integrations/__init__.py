"""Optional framework adapters built on the core TrustedAction contract."""

from .langgraph import as_langgraph_node
from .mcp import as_mcp_tool_handler, register_fastmcp_action
from .opa import OPAPolicy
from .openai_agents import as_openai_agents_tool
from .stripe_sandbox import (
    StripeSandboxPaymentAdapter,
    StripeSandboxPaymentFailed,
    StripeSandboxPaymentProbe,
)

__all__ = [
    "OPAPolicy",
    "StripeSandboxPaymentAdapter",
    "StripeSandboxPaymentFailed",
    "StripeSandboxPaymentProbe",
    "as_langgraph_node",
    "as_mcp_tool_handler",
    "as_openai_agents_tool",
    "register_fastmcp_action",
]
