from __future__ import annotations

import contextlib
import io
import json
import os
import tempfile
import unittest
from datetime import UTC, datetime, timedelta
from pathlib import Path

import jwt
from cryptography.hazmat.primitives.asymmetric import rsa

from agenttrustops import (
    AuthenticationError,
    OIDCJWTVerifier,
    StaticTokenVerifier,
    VerifiedPrincipal,
)
from agenttrustops.cli import main
from agenttrustops.refund_ops import build_refund_action


class AuthenticationTests(unittest.TestCase):
    def test_static_verifier_hashes_and_verifies_credentials(self) -> None:
        principal = VerifiedPrincipal(
            actor_id="operator",
            tenant_id="default",
            roles=("agenttrustops_operator",),
            auth_source="test",
        )
        verifier = StaticTokenVerifier({"a-long-static-token": principal})

        self.assertEqual(verifier.verify("a-long-static-token"), principal)
        with self.assertRaises(AuthenticationError):
            verifier.verify("wrong-static-token")
        self.assertNotIn("a-long-static-token", repr(verifier.__dict__))

    def test_identity_file_must_be_permission_restricted(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            path = Path(directory) / "identities.json"
            path.write_text(
                json.dumps(
                    {
                        "identities": [
                            {
                                "token": "permission-test-token",
                                "actor_id": "operator",
                                "tenant_id": "default",
                                "roles": ["agenttrustops_operator"],
                            }
                        ]
                    }
                ),
                encoding="utf-8",
            )
            os.chmod(path, 0o644)
            with self.assertRaisesRegex(ValueError, "must not be readable"):
                StaticTokenVerifier.from_json(path)
            os.chmod(path, 0o600)
            self.assertEqual(
                StaticTokenVerifier.from_json(path)
                .verify("permission-test-token")
                .actor_id,
                "operator",
            )

    def test_oidc_verifier_checks_signature_issuer_audience_expiry_and_claims(self):
        private_key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
        public_key = private_key.public_key()
        verifier = OIDCJWTVerifier(
            issuer="https://identity.example",
            audience="agenttrustops-api",
            jwks_url="https://identity.example/.well-known/jwks.json",
        )

        class SigningKey:
            key = public_key

        class JWKSClient:
            @staticmethod
            def get_signing_key_from_jwt(credential):
                return SigningKey()

        verifier._jwks_client = JWKSClient()
        now = datetime.now(UTC)
        claims = {
            "iss": "https://identity.example",
            "aud": "agenttrustops-api",
            "sub": "oidc-user",
            "tenant_id": "acme",
            "roles": ["agenttrustops_viewer"],
            "iat": now,
            "exp": now + timedelta(minutes=5),
        }
        token = jwt.encode(
            claims, private_key, algorithm="RS256", headers={"kid": "k1"}
        )

        principal = verifier.verify(token)
        self.assertEqual(principal.actor_id, "oidc-user")
        self.assertEqual(principal.tenant_id, "acme")
        self.assertEqual(principal.auth_source, "oidc:https://identity.example")

        wrong_audience = jwt.encode(
            {**claims, "aud": "another-api"},
            private_key,
            algorithm="RS256",
            headers={"kid": "k1"},
        )
        with self.assertRaises(AuthenticationError):
            verifier.verify(wrong_audience)

        invalid_roles = jwt.encode(
            {**claims, "roles": "agenttrustops_viewer"},
            private_key,
            algorithm="RS256",
            headers={"kid": "k1"},
        )
        with self.assertRaisesRegex(AuthenticationError, "string array"):
            verifier.verify(invalid_roles)

    def test_oidc_verifier_rejects_insecure_discovery_and_symmetric_algorithms(self):
        with self.assertRaisesRegex(ValueError, "must use https"):
            OIDCJWTVerifier(
                issuer="http://identity.example",
                audience="api",
                jwks_url="http://identity.example/jwks.json",
            )
        with self.assertRaisesRegex(ValueError, "asymmetric"):
            OIDCJWTVerifier(
                issuer="https://identity.example",
                audience="api",
                jwks_url="https://identity.example/jwks.json",
                algorithms=("HS256",),
            )


class OperationalCliTests(unittest.TestCase):
    def test_doctor_and_metrics_inspect_a_real_ledger(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            ledger_path = Path(directory) / "ledger.db"
            action, _ = build_refund_action(
                ledger_path=ledger_path,
                refund_path=Path(directory) / "refunds.db",
                policy_config={
                    "release": "cli-test",
                    "selection_mode": "as_of_order",
                    "approval_enabled": True,
                    "require_evidence": True,
                    "enforce_roles": True,
                },
            )
            action.ledger.close()

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["doctor", "--ledger", str(ledger_path)])
            report = json.loads(stdout.getvalue())
            self.assertEqual(exit_code, 0)
            self.assertTrue(report["healthy"])
            self.assertEqual(report["backend"], "sqlite")

            stdout = io.StringIO()
            with contextlib.redirect_stdout(stdout):
                exit_code = main(["metrics", "--ledger", str(ledger_path)])
            self.assertEqual(exit_code, 0)
            self.assertIn("agenttrustops_runs", stdout.getvalue())


if __name__ == "__main__":
    unittest.main()
