# Verifiable adoption ladder

Repository polish cannot create production adoption. This ladder defines the evidence required to
raise that dimension without converting stars, downloads, maintainer demos, or synthetic CI into
customer claims.

| Score | Minimum evidence | Public claim allowed |
|---:|---|---|
| 0 | No independent use | No adoption claim |
| 1 | Public repository and maintainer-only validation | “No verified production adopters yet” |
| 2 | One independent unassisted successful demo with consented feedback | One external evaluation |
| 3 | Three independent successful evaluations and blockers recorded publicly/anonymously | Evaluated in three environments |
| 4 | One two-week design-partner pilot using a real integration boundary | One verified pilot |
| 5 | Three active pilots, two integrations, weekly governed use | Multi-pilot validation |
| 6 | One named or privately verified production deployment with 30-day continuity | First production adopter |
| 7 | Three production organizations, 100,000 cumulative governed runs, one external contribution | Early production adoption |
| 8 | Five production organizations, 1 million cumulative runs, two published case studies, two external contributors | Repeatable adoption |
| 9 | Ten production organizations across three side-effect categories, independent security review, second maintainer | Established ecosystem |
| 10 | Twenty production organizations, 10 million cumulative runs, externally maintained integrations, recurring community releases and support | Category-level ecosystem evidence |

Counts may include privately verified organizations but public wording must distinguish named from
anonymous evidence. An organization counts only once. Volume is recorded as consented aggregate
bands unless exact publication is explicitly permitted.

## The conversion funnel

The project's near-term objective is not “get more stars.” It is to remove risk from one concrete
journey:

1. **60-second proof:** install the wheel and run `agenttrust demo` without keys or a clone.
2. **20-minute challenge:** repeat, conflict, approve, resume, export, and independently verify a
   synthetic side effect.
3. **Two-hour integration:** wrap one fake adapter in the user's framework and replace identity,
   evidence, and retry-key resolvers with application-owned values.
4. **Two-week pilot:** use PostgreSQL/OIDC, one real provider sandbox, reconciliation, alerts, and
   a signed evidence export.
5. **Production review:** document provider idempotency, retention, HA, runbook ownership, threat
   model exceptions, and rollback/disable controls.

## Metrics that can change product decisions

| Stage | Primary measure | Initial target |
|---|---|---:|
| README → demo | unassisted time to completed run | under 5 minutes, 80% success |
| Demo → integration | reviewers who identify a real side effect and adapter boundary | 50% |
| Integration → pilot | integrations reaching PostgreSQL + verified identity | 3 |
| Pilot reliability | governed runs without duplicate side effect caused by AgentTrustOps | 100% |
| Unknown recovery | unknown runs reconciled within provider-specific SLO | 95% |
| Community health | merged external fixes/scenarios and active external reviewers | at least 3 per quarter |

Raw telemetry is not built into the package. Evidence comes from consented adopter reports,
case-study links, public issues/PRs, or private verification recorded only as aggregate counts.

## Evidence packet for each pilot

- version/commit, backend, framework, side-effect category, and pilot/production stage;
- approximate monthly volume band and continuity period;
- whether OIDC/workload identity and provider-native idempotency are enabled;
- one synthetic retry/conflict/unknown/reconciliation result;
- signed redacted audit-bundle verification result;
- highest-impact adoption blocker and its disposition;
- explicit visibility consent: named, anonymous aggregate, or private-only.

Use the [design-partner issue form](https://github.com/teresaliu90/AgentTrustOps/issues/new?template=design-partner.yml)
or the [unassisted feedback kit](design-partner-feedback-kit.md). `ADOPTERS.md` is the public source
of truth; no entry or logo is added without consent.
