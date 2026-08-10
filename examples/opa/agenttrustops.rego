package agenttrustops

import rego.v1

default decision := {
    "outcome": "deny",
    "reason": "action is not covered by this policy",
    "policy_version": "refunds-2026-08-10",
    "policy_digest": "example-not-a-production-bundle-digest",
}

decision := {
    "outcome": "allow",
    "reason": "verified refund remains within autonomous limit",
    "policy_version": "refunds-2026-08-10",
    "policy_digest": "example-not-a-production-bundle-digest",
    "facts": {"autonomous_limit": 500},
} if {
    input.action_name == "execute_refund"
    input.arguments.amount <= 500
    "refund_agent" in input.context.roles
    count(input.context.evidence) >= 2
}

decision := {
    "outcome": "approval_required",
    "reason": "verified refund exceeds autonomous limit",
    "policy_version": "refunds-2026-08-10",
    "policy_digest": "example-not-a-production-bundle-digest",
    "facts": {"autonomous_limit": 500},
} if {
    input.action_name == "execute_refund"
    input.arguments.amount > 500
    "refund_agent" in input.context.roles
    count(input.context.evidence) >= 2
}
