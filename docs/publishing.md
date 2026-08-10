# Publishing and supply chain

## GitHub Release

Pushing an annotated `v*` tag runs `release-artifacts.yml`. It builds the wheel and source archive,
installs the wheel in a clean environment, generates a CycloneDX JSON SBOM, writes SHA-256
checksums, creates GitHub artifact attestations, and attaches all files to a GitHub Release. A rerun
updates the same release assets instead of creating a conflicting release.

Verify a downloaded wheel against `SHA256SUMS` before installation. GitHub's artifact attestation
verification can additionally bind an artifact digest to this repository and workflow.

## Container

The same tag workflow publishes these OCI tags:

```text
ghcr.io/teresaliu90/agenttrustops:v0.3.0
ghcr.io/teresaliu90/agenttrustops:latest
```

BuildKit emits SBOM and max-mode provenance attestations. A tag workflow must succeed before either
tag is described as available.

## PyPI Trusted Publishing

`publish-pypi.yml` is deliberately manual and uses OpenID Connect Trusted Publishing—there is no
long-lived PyPI API token in repository secrets. To activate it:

1. Reserve or own the `agenttrustops` PyPI project.
2. Add this repository, workflow filename, and `pypi` environment as a PyPI Trusted Publisher.
3. Protect the GitHub `pypi` environment with a maintainer approval rule.
4. Dispatch the workflow with the exact source version only after the matching GitHub Release and
   CI checks pass.
5. Verify the public PyPI project page and install in a clean environment before documenting PyPI
   availability.

Until those external steps succeed, users should install a verified GitHub Release wheel or build
from a pinned commit. A workflow file is distribution readiness, not proof that a registry package
exists.
