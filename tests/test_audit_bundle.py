from __future__ import annotations

import base64
import copy
import json
import os
import tempfile
import unittest
from pathlib import Path

from agenttrustops.audit import (
    export_audit_bundle,
    generate_ed25519_keypair,
    verify_audit_bundle,
)
from agenttrustops.ledger import SQLiteActionLedger
from agenttrustops.refund_ops import run_refund_demo


class AuditBundleTests(unittest.TestCase):
    def setUp(self) -> None:
        self.temporary = tempfile.TemporaryDirectory()
        self.directory = Path(self.temporary.name)
        report = run_refund_demo(self.directory / "demo")
        self.ledger = SQLiteActionLedger(report["ledger"])
        self.private_key = self.directory / "audit-private.pem"
        self.public_key = self.directory / "audit-public.pem"
        generate_ed25519_keypair(self.private_key, self.public_key)

    def tearDown(self) -> None:
        self.ledger.close()
        self.temporary.cleanup()

    def test_signed_redacted_bundle_verifies_with_pinned_key(self) -> None:
        document = export_audit_bundle(
            self.ledger,
            tenant_id="default",
            signing_key_path=self.private_key,
        )
        report = verify_audit_bundle(
            document,
            trusted_public_key_path=self.public_key,
        )
        serialized = json.dumps(document)

        self.assertTrue(report["valid"])
        self.assertTrue(report["signature_verified"])
        self.assertEqual(report["trust_mode"], "pinned-key")
        self.assertEqual(report["run_count"], 1)
        self.assertNotIn("refund-agent", serialized)
        self.assertNotIn("finance-manager", serialized)
        self.assertNotIn("Approved after reviewing", serialized)
        self.assertNotIn("amount exceeds 500.00 approval threshold", serialized)
        self.assertFalse(document["payload"]["runs"][0]["sensitive_fields_included"])

    def test_payload_tampering_invalidates_digest(self) -> None:
        document = export_audit_bundle(
            self.ledger,
            signing_key_path=self.private_key,
        )
        tampered = copy.deepcopy(document)
        tampered["payload"]["runs"][0]["run"]["status"] = "completed-by-attacker"

        with self.assertRaisesRegex(ValueError, "digest"):
            verify_audit_bundle(tampered)

    def test_wrong_pinned_key_is_rejected(self) -> None:
        document = export_audit_bundle(
            self.ledger,
            signing_key_path=self.private_key,
        )
        other_private = self.directory / "other-private.pem"
        other_public = self.directory / "other-public.pem"
        generate_ed25519_keypair(other_private, other_public)

        with self.assertRaisesRegex(ValueError, "trusted key"):
            verify_audit_bundle(document, trusted_public_key_path=other_public)

    def test_recomputed_digest_cannot_bypass_signature(self) -> None:
        document = export_audit_bundle(
            self.ledger,
            signing_key_path=self.private_key,
        )
        signature = document["proof"]["signature"]
        raw = bytearray(base64.b64decode(signature["value"]))
        raw[0] ^= 1
        signature["value"] = base64.b64encode(raw).decode("ascii")

        with self.assertRaisesRegex(ValueError, "signature is invalid"):
            verify_audit_bundle(document)

    def test_unsigned_bundle_is_explicitly_digest_only(self) -> None:
        document = export_audit_bundle(self.ledger)
        report = verify_audit_bundle(document)

        self.assertTrue(report["valid"])
        self.assertFalse(report["signature_verified"])
        self.assertEqual(report["trust_mode"], "digest-only")
        with self.assertRaisesRegex(ValueError, "unsigned"):
            verify_audit_bundle(
                document,
                trusted_public_key_path=self.public_key,
            )

    def test_key_generation_is_private_and_never_overwrites(self) -> None:
        self.assertEqual(os.stat(self.private_key).st_mode & 0o077, 0)
        with self.assertRaises(FileExistsError):
            generate_ed25519_keypair(self.private_key, self.public_key)

    def test_export_refuses_a_broken_source_chain(self) -> None:
        with self.ledger._connection() as connection, connection:
            connection.execute(
                "UPDATE action_events SET payload_json = '{}' WHERE sequence = "
                "(SELECT MIN(sequence) FROM action_events)"
            )
        with self.assertRaisesRegex(ValueError, "source event chain failed"):
            export_audit_bundle(self.ledger)


if __name__ == "__main__":
    unittest.main()
