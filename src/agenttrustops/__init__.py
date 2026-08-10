"""Public AgentTrustOps SDK surface."""

from .auth import (
    AuthenticationError,
    IdentityVerifier,
    OIDCJWTVerifier,
    StaticTokenVerifier,
)
from .errors import (
    AgentTrustOpsError,
    ApprovalDenied,
    IdempotencyConflict,
    InvalidTransition,
)
from .integrations import (
    OPAPolicy,
    as_langgraph_node,
    as_mcp_tool_handler,
    as_openai_agents_tool,
    register_fastmcp_action,
)
from .ledger import SQLiteActionLedger
from .models import (
    ActionContext,
    ActionResult,
    ActionStatus,
    PolicyDecision,
    PolicyOutcome,
    VerifiedPrincipal,
)
from .observability import (
    OperationalSnapshot,
    collect_operational_snapshot,
    render_prometheus,
)
from .postgres import PostgresActionLedger
from .registry import ActionRegistry
from .runtime import IndeterminateOutcome, TrustedAction, trusted_action

__all__ = [
    "ActionContext",
    "ActionRegistry",
    "ActionResult",
    "ActionStatus",
    "AgentTrustOpsError",
    "ApprovalDenied",
    "AuthenticationError",
    "IdempotencyConflict",
    "IdentityVerifier",
    "IndeterminateOutcome",
    "InvalidTransition",
    "OIDCJWTVerifier",
    "OPAPolicy",
    "OperationalSnapshot",
    "PolicyDecision",
    "PolicyOutcome",
    "PostgresActionLedger",
    "SQLiteActionLedger",
    "StaticTokenVerifier",
    "TrustedAction",
    "VerifiedPrincipal",
    "as_langgraph_node",
    "as_mcp_tool_handler",
    "as_openai_agents_tool",
    "collect_operational_snapshot",
    "register_fastmcp_action",
    "render_prometheus",
    "trusted_action",
]

__version__ = "0.2.0"
