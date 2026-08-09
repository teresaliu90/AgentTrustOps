"""Authentication boundaries for service adapters."""

from __future__ import annotations

import hashlib
import hmac
import json
from collections.abc import Mapping
from pathlib import Path
from typing import Any, Protocol
from urllib.parse import urlparse

from .errors import AgentTrustOpsError
from .models import VerifiedPrincipal


class AuthenticationError(AgentTrustOpsError):
    """Raised when a credential cannot be mapped to a verified principal."""


class IdentityVerifier(Protocol):
    """Turn a credential into identity only after validating its authenticity."""

    def verify(self, credential: str) -> VerifiedPrincipal: ...


class StaticTokenVerifier:
    """Hashed static-token verifier for local demos and internal prototypes.

    Production deployments should implement ``IdentityVerifier`` using OIDC,
    workload identity, or mTLS. Plaintext tokens are hashed immediately and are
    never returned by this class.
    """

    def __init__(self, identities: Mapping[str, VerifiedPrincipal]):
        if not identities:
            raise ValueError("at least one static identity is required")
        records: list[tuple[bytes, VerifiedPrincipal]] = []
        for token, principal in identities.items():
            if len(token) < 16:
                raise ValueError("static tokens must contain at least 16 characters")
            records.append((self._digest(token), principal))
        self._records = tuple(records)

    @staticmethod
    def _digest(token: str) -> bytes:
        return hashlib.sha256(token.encode("utf-8")).digest()

    def verify(self, credential: str) -> VerifiedPrincipal:
        candidate = self._digest(credential)
        matched: VerifiedPrincipal | None = None
        for digest, principal in self._records:
            if hmac.compare_digest(candidate, digest):
                matched = principal
        if matched is None:
            raise AuthenticationError("invalid bearer credential")
        return matched

    @classmethod
    def from_json(cls, path: str | Path) -> StaticTokenVerifier:
        """Load local demo identities from a permission-restricted JSON file."""

        identity_path = Path(path)
        if identity_path.stat().st_mode & 0o077:
            raise ValueError(
                "identity file must not be readable by group or other users"
            )
        document = json.loads(identity_path.read_text(encoding="utf-8"))
        identities: dict[str, VerifiedPrincipal] = {}
        for item in document.get("identities", []):
            identities[str(item["token"])] = VerifiedPrincipal(
                actor_id=str(item["actor_id"]),
                tenant_id=str(item["tenant_id"]),
                roles=tuple(str(role) for role in item["roles"]),
                auth_source=f"static-file:{identity_path.name}",
            )
        return cls(identities)


class OIDCJWTVerifier:
    """Verify asymmetric OIDC JWTs against a cached JWKS endpoint."""

    def __init__(
        self,
        *,
        issuer: str,
        audience: str,
        jwks_url: str,
        tenant_claim: str = "tenant_id",
        roles_claim: str = "roles",
        algorithms: tuple[str, ...] = ("RS256", "ES256"),
        leeway_seconds: int = 30,
        allow_insecure_http: bool = False,
    ):
        try:
            import jwt
        except ModuleNotFoundError as error:
            raise RuntimeError(
                "OIDC support requires: pip install 'agenttrustops[oidc]'"
            ) from error
        if not issuer.strip() or not audience.strip() or not jwks_url.strip():
            raise ValueError("issuer, audience, and jwks_url are required")
        if not allow_insecure_http:
            for name, value in (("issuer", issuer), ("jwks_url", jwks_url)):
                if urlparse(value).scheme != "https":
                    raise ValueError(f"{name} must use https")
        allowed = {"RS256", "RS384", "RS512", "ES256", "ES384", "ES512"}
        if not algorithms or not set(algorithms).issubset(allowed):
            raise ValueError(
                "only explicit asymmetric RSA or ECDSA algorithms are allowed"
            )
        if not 0 <= leeway_seconds <= 300:
            raise ValueError("leeway_seconds must be between 0 and 300")
        self.issuer = issuer.rstrip("/")
        self.audience = audience
        self.tenant_claim = tenant_claim
        self.roles_claim = roles_claim
        self.algorithms = algorithms
        self.leeway_seconds = leeway_seconds
        self._jwt = jwt
        self._jwks_client = jwt.PyJWKClient(jwks_url, cache_keys=True)

    def verify(self, credential: str) -> VerifiedPrincipal:
        try:
            signing_key = self._jwks_client.get_signing_key_from_jwt(credential)
            claims: dict[str, Any] = self._jwt.decode(
                credential,
                signing_key.key,
                algorithms=list(self.algorithms),
                audience=self.audience,
                issuer=self.issuer,
                leeway=self.leeway_seconds,
                options={"require": ["exp", "iat", "iss", "aud", "sub"]},
            )
            subject = claims["sub"]
            tenant = claims[self.tenant_claim]
            roles = claims[self.roles_claim]
            if not isinstance(subject, str) or not isinstance(tenant, str):
                raise AuthenticationError(
                    "OIDC subject and tenant claims must be strings"
                )
            if not isinstance(roles, list) or not all(
                isinstance(role, str) for role in roles
            ):
                raise AuthenticationError("OIDC roles claim must be a string array")
            return VerifiedPrincipal(
                actor_id=subject,
                tenant_id=tenant,
                roles=tuple(roles),
                auth_source=f"oidc:{self.issuer}",
            )
        except AuthenticationError:
            raise
        except (KeyError, self._jwt.PyJWTError) as error:
            raise AuthenticationError("invalid OIDC bearer credential") from error
