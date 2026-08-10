# Portable audit evidence

Database event chains and portable evidence solve different problems. AgentTrustOps verifies the
source chain first, redacts it, then optionally signs the canonical export with Ed25519. An auditor
can verify that export later without database, network, model, or AgentTrustOps service access.

## Trust model

| Check | What it proves | What it does not prove |
|---|---|---|
| Source `chain_verified` | Events matched the ledger's count/head-anchored SHA-256 chain at export time | A database administrator never rewrote and rehashed the source before export |
| Bundle SHA-256 digest | The current payload matches the digest stored beside it | Who created the digest |
| Embedded-key signature | Payload and embedded signing key are self-consistent | The embedded key belongs to a trusted organization |
| Pinned-key signature | Payload was signed by the separately distributed trusted public key | WORM retention or correctness of the underlying business decision |

For an external audit, distribute the public key through an independently controlled channel and
always verify with `--public-key`. Treat `embedded-key` verification as integrity, not identity.

## Export and verify

```bash
pip install 'agenttrustops[audit]'
agenttrust audit-keygen \
  --private-key audit-private.pem \
  --public-key audit-public.pem

agenttrust audit-export \
  --ledger actions.db \
  --tenant acme \
  --signing-key audit-private.pem \
  --output acme-evidence.json

agenttrust audit-verify acme-evidence.json --public-key audit-public.pem
```

`audit-keygen` refuses to overwrite either key and creates the private key without group/other read
permissions. `audit-export` also refuses to overwrite the output. Keep the private key in a KMS or
secret-management boundary for production; the filesystem key path is a portable reference
implementation.

Set `AGENTTRUSTOPS_POSTGRES_DSN` instead of `--ledger` to export from PostgreSQL. Tenant-scoped
exports should be preferred. The maximum export is currently 1,000 most-recent runs per invocation;
schedule bounded exports and retain checkpoints in the external archive.

## Privacy boundary

Portable bundles always use the redacted audit view. They exclude raw arguments, evidence,
metadata, results, actor identifiers, roles, idempotency keys, approval notes, operators, and auth
sources. Stable SHA-256 digests and operational metadata can still be linkable; apply retention and
access rules appropriate to the data classification.

Redaction changes event payloads, so the recipient cannot recompute the original database event
hashes. Instead, the export records the source-chain verdict and the signature protects the entire
redacted artifact after export. Systems that require independently verifiable raw chains should
export encrypted source events to organization-controlled append-only storage.

## Recommended production pattern

1. Run `agenttrust doctor` and alert on any invalid chain.
2. Export one tenant and bounded time/run window at a time.
3. Sign with a key whose public half is pinned in the auditor's trust store.
4. Verify immediately in an isolated job.
5. Store the JSON in independently administered object-lock/WORM storage.
6. Record export digest, signer fingerprint, storage object version, and retention deadline in the
   organization's evidence catalog.
