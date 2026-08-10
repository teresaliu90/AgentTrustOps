"""Portable, redacted, and optionally signed audit evidence bundles."""

from __future__ import annotations

import base64
import hashlib
import json
import os
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

BUNDLE_SCHEMA = "agenttrustops-audit-bundle-v1"
MAX_BUNDLE_BYTES = 64 * 1024 * 1024


def _canonical_json(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        allow_nan=False,
    ).encode("utf-8")


def _sha256(value: bytes) -> str:
    return "sha256:" + hashlib.sha256(value).hexdigest()


def _crypto():
    try:
        from cryptography.hazmat.primitives import serialization
        from cryptography.hazmat.primitives.asymmetric.ed25519 import (
            Ed25519PrivateKey,
            Ed25519PublicKey,
        )
    except ModuleNotFoundError as error:
        raise RuntimeError(
            "signed audit bundles require: pip install 'agenttrustops[audit]'"
        ) from error
    return serialization, Ed25519PrivateKey, Ed25519PublicKey


def _exclusive_write(path: Path, value: bytes, mode: int) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, mode)
    try:
        with os.fdopen(descriptor, "wb") as stream:
            stream.write(value)
    except BaseException:
        try:
            path.unlink()
        except FileNotFoundError:
            pass
        raise


def generate_ed25519_keypair(
    private_key_path: str | Path,
    public_key_path: str | Path,
) -> dict[str, str]:
    """Create a non-overwriting Ed25519 signing keypair."""

    serialization, Ed25519PrivateKey, _ = _crypto()
    private_path = Path(private_key_path)
    public_path = Path(public_key_path)
    if private_path.resolve() == public_path.resolve():
        raise ValueError("private and public key paths must differ")
    if private_path.exists() or public_path.exists():
        raise FileExistsError("refusing to overwrite an existing audit key")

    private_key = Ed25519PrivateKey.generate()
    private_bytes = private_key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    public_bytes = private_key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    _exclusive_write(private_path, private_bytes, 0o600)
    try:
        _exclusive_write(public_path, public_bytes, 0o644)
    except BaseException:
        private_path.unlink(missing_ok=True)
        raise
    return {
        "private_key": str(private_path),
        "public_key": str(public_path),
        "public_key_fingerprint": _sha256(_public_raw(private_key.public_key())),
    }


def _load_private_key(path: str | Path):
    serialization, Ed25519PrivateKey, _ = _crypto()
    key = serialization.load_pem_private_key(Path(path).read_bytes(), password=None)
    if not isinstance(key, Ed25519PrivateKey):
        raise TypeError("audit signing key must be an Ed25519 private key")
    return key


def _public_raw(public_key: Any) -> bytes:
    serialization, _, _ = _crypto()
    return public_key.public_bytes(
        encoding=serialization.Encoding.Raw,
        format=serialization.PublicFormat.Raw,
    )


def export_audit_bundle(
    ledger: Any,
    *,
    tenant_id: str | None = None,
    limit: int = 1000,
    signing_key_path: str | Path | None = None,
) -> dict[str, Any]:
    """Export redacted trails after verifying every source event chain."""

    runs = ledger.list_runs(tenant_id=tenant_id, limit=limit)
    trails: list[dict[str, Any]] = []
    for run in runs:
        trail = ledger.audit_trail(str(run["run_id"]))
        if trail is None:
            raise RuntimeError("a listed run disappeared during audit export")
        if trail["sensitive_fields_included"]:
            raise RuntimeError("portable audit bundles must be redacted")
        if not trail["integrity"]["chain_verified"]:
            raise ValueError(f"source event chain failed for run {run['run_id']}")
        trails.append(trail)

    payload = {
        "schema": BUNDLE_SCHEMA,
        "exported_at": datetime.now(UTC).isoformat(),
        "source": {
            "backend": str(ledger.backend_name),
            "tenant_scope": tenant_id,
        },
        "run_count": len(trails),
        "runs": trails,
    }
    canonical = _canonical_json(payload)
    proof: dict[str, Any] = {
        "digest": _sha256(canonical),
        "signature": None,
    }
    if signing_key_path is not None:
        key = _load_private_key(signing_key_path)
        raw_public = _public_raw(key.public_key())
        proof["signature"] = {
            "algorithm": "Ed25519",
            "value": base64.b64encode(key.sign(canonical)).decode("ascii"),
            "public_key": base64.b64encode(raw_public).decode("ascii"),
            "public_key_fingerprint": _sha256(raw_public),
        }
    return {"payload": payload, "proof": proof}


def write_audit_bundle(path: str | Path, document: dict[str, Any]) -> None:
    """Write a bundle as stable, human-readable JSON without silent overwrite."""

    value = json.dumps(document, ensure_ascii=False, indent=2, sort_keys=True)
    _exclusive_write(Path(path), (value + "\n").encode("utf-8"), 0o600)


def _load_public_key(path: str | Path):
    serialization, _, Ed25519PublicKey = _crypto()
    key = serialization.load_pem_public_key(Path(path).read_bytes())
    if not isinstance(key, Ed25519PublicKey):
        raise TypeError("trusted audit key must be an Ed25519 public key")
    return key


def verify_audit_bundle(
    document: dict[str, Any],
    *,
    trusted_public_key_path: str | Path | None = None,
) -> dict[str, Any]:
    """Verify bundle digest, source verdicts, and an optional pinned signature."""

    try:
        payload = document["payload"]
        proof = document["proof"]
        if payload["schema"] != BUNDLE_SCHEMA:
            raise ValueError("unsupported audit bundle schema")
        canonical = _canonical_json(payload)
        if proof["digest"] != _sha256(canonical):
            raise ValueError("audit bundle digest does not match its payload")
        runs = payload["runs"]
        if payload["run_count"] != len(runs):
            raise ValueError("audit bundle run count does not match its payload")
        if any(trail["sensitive_fields_included"] for trail in runs):
            raise ValueError("audit bundle contains sensitive audit fields")
        if any(not trail["integrity"]["chain_verified"] for trail in runs):
            raise ValueError("audit bundle records a failed source event chain")

        signature = proof.get("signature")
        trust_mode = "digest-only"
        signer_fingerprint: str | None = None
        if signature is not None:
            from cryptography.exceptions import InvalidSignature

            if signature.get("algorithm") != "Ed25519":
                raise ValueError("unsupported audit signature algorithm")
            _, _, Ed25519PublicKey = _crypto()
            embedded_raw = base64.b64decode(signature["public_key"], validate=True)
            embedded_key = Ed25519PublicKey.from_public_bytes(embedded_raw)
            signer_fingerprint = _sha256(embedded_raw)
            if signature.get("public_key_fingerprint") != signer_fingerprint:
                raise ValueError("audit signer fingerprint does not match")
            verification_key = embedded_key
            trust_mode = "embedded-key"
            if trusted_public_key_path is not None:
                verification_key = _load_public_key(trusted_public_key_path)
                if _public_raw(verification_key) != embedded_raw:
                    raise ValueError("audit signature does not use the trusted key")
                trust_mode = "pinned-key"
            try:
                verification_key.verify(
                    base64.b64decode(signature["value"], validate=True), canonical
                )
            except InvalidSignature as error:
                raise ValueError("audit bundle signature is invalid") from error
        elif trusted_public_key_path is not None:
            raise ValueError("a trusted key was supplied for an unsigned bundle")
        return {
            "valid": True,
            "schema": BUNDLE_SCHEMA,
            "run_count": len(runs),
            "digest": proof["digest"],
            "signature_verified": signature is not None,
            "trust_mode": trust_mode,
            "signer_fingerprint": signer_fingerprint,
        }
    except (KeyError, TypeError, ValueError) as error:
        raise ValueError(f"invalid audit bundle: {error}") from error


def read_audit_bundle(path: str | Path) -> dict[str, Any]:
    """Load a JSON audit bundle."""

    bundle_path = Path(path)
    if bundle_path.stat().st_size > MAX_BUNDLE_BYTES:
        raise ValueError("audit bundle exceeds the 64 MiB verification limit")
    value = json.loads(bundle_path.read_text(encoding="utf-8"))
    if not isinstance(value, dict):
        raise TypeError("audit bundle must be a JSON object")
    return value
