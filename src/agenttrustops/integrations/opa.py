"""Fail-closed Open Policy Agent Data API adapter."""

from __future__ import annotations

import json
import ssl
from collections.abc import Mapping
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import quote, urlparse
from urllib.request import Request, urlopen

from ..models import ActionContext, PolicyDecision, PolicyOutcome


class OPAPolicy:
    """Evaluate AgentTrustOps actions against an OPA Data API document."""

    def __init__(
        self,
        base_url: str,
        decision_path: str,
        *,
        timeout_seconds: float = 3.0,
        headers: Mapping[str, str] | None = None,
        allow_insecure_http: bool = False,
        max_response_bytes: int = 1_048_576,
        ssl_context: ssl.SSLContext | None = None,
    ) -> None:
        parsed = urlparse(base_url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise ValueError("base_url must be an absolute HTTP(S) URL")
        if parsed.scheme != "https" and not allow_insecure_http:
            raise ValueError("OPA requires HTTPS unless allow_insecure_http=True")
        path = decision_path.strip("/")
        if not path:
            raise ValueError("decision_path cannot be empty")
        if not 0.05 <= timeout_seconds <= 30:
            raise ValueError("timeout_seconds must be between 0.05 and 30")
        if not 1024 <= max_response_bytes <= 16_777_216:
            raise ValueError("max_response_bytes must be between 1024 and 16777216")
        self.url = f"{base_url.rstrip('/')}/v1/data/{'/'.join(quote(p, safe='') for p in path.split('/'))}"
        self.timeout_seconds = timeout_seconds
        self.headers = dict(headers or {})
        self.max_response_bytes = max_response_bytes
        self.ssl_context = ssl_context

    def evaluate(
        self,
        action_name: str,
        arguments: dict[str, Any],
        context: ActionContext,
    ) -> PolicyDecision:
        payload = {
            "input": {
                "action_name": action_name,
                "arguments": arguments,
                "context": {
                    "actor_id": context.actor_id,
                    "tenant_id": context.tenant_id,
                    "roles": list(context.roles),
                    "evidence": list(context.evidence),
                    "metadata": context.metadata,
                },
            }
        }
        request = Request(
            self.url,
            data=json.dumps(payload, ensure_ascii=False).encode("utf-8"),
            method="POST",
            headers={"Content-Type": "application/json", **self.headers},
        )
        try:
            with urlopen(
                request,
                timeout=self.timeout_seconds,
                context=self.ssl_context,
            ) as response:
                raw = response.read(self.max_response_bytes + 1)
        except (HTTPError, URLError, TimeoutError) as error:
            raise RuntimeError(
                f"OPA evaluation unavailable: {type(error).__name__}"
            ) from error
        if len(raw) > self.max_response_bytes:
            raise ValueError("OPA response exceeded max_response_bytes")
        try:
            envelope = json.loads(raw)
        except (json.JSONDecodeError, UnicodeDecodeError) as error:
            raise ValueError("OPA returned invalid JSON") from error
        if not isinstance(envelope, dict) or not isinstance(
            envelope.get("result"), dict
        ):
            raise TypeError("OPA response must contain an object result")
        result = envelope["result"]
        try:
            outcome = PolicyOutcome(result["outcome"])
            reason = str(result["reason"])
            version = str(result["policy_version"])
        except (KeyError, ValueError, TypeError) as error:
            raise ValueError("OPA result has an invalid decision contract") from error
        facts = result.get("facts", {})
        if not isinstance(facts, dict):
            raise TypeError("OPA decision facts must be an object")
        digest = result.get("policy_digest")
        if digest is not None and not isinstance(digest, str):
            raise ValueError("OPA policy_digest must be a string")
        return PolicyDecision(outcome, reason, version, facts, digest)
