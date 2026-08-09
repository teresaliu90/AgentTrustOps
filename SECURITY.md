# Security policy

Please do not open a public issue for a vulnerability that could enable unauthorized execution,
approval bypass, cross-tenant access, duplicate side effects, or secret disclosure. Use GitHub's
private vulnerability reporting feature when it is enabled for this repository.

Include the affected version, a minimal reproduction using fictional data, impact, and any known
mitigation. Do not test against systems or accounts you do not own or have explicit permission to
use.

## Supported versions

| Version | Security fixes |
|---|---|
| 0.2.x | Yes |
| 0.1.x | Critical fixes only until 2026-11-08 |

Maintainers will acknowledge a complete private report when repository notifications permit and
will coordinate disclosure after a fix is available. No fixed response-time SLA is claimed.

See `docs/threat-model.md` and `docs/production-boundaries.md` for explicit trust boundaries.
