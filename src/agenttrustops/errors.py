"""Stable public errors for reliable action handling."""


class AgentTrustOpsError(Exception):
    """Base class for expected AgentTrustOps failures."""


class IdempotencyConflict(AgentTrustOpsError):
    """The same idempotency identity was reused for a different request."""


class InvalidTransition(AgentTrustOpsError):
    """A run cannot move from its current state to the requested state."""


class ApprovalDenied(AgentTrustOpsError):
    """The supplied principal is not authorized to decide an approval."""
