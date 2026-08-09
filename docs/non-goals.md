# v0.2 non-goals

AgentTrustOps has a narrow enforcement responsibility. It does not aim to:

- build a general-purpose agent, graph, or durable workflow engine;
- replace LangGraph, Temporal, OPA, Promptfoo, AgentOps, a model gateway, or a SIEM;
- treat model/user-provided roles, tenant IDs, or evidence as authenticated facts;
- promise distributed exactly-once delivery without provider-native idempotency;
- automatically compensate an uncertain or irreversible side effect;
- claim that a database administrator cannot rewrite a SQLite or PostgreSQL history;
- ship a real payment connector, identity provider, fraud engine, or compliance certification;
- claim high availability, regional failover, external production adoption, or SLOs without
  measured evidence;
- build a large web console before the API and operator contracts have external design validation.

The roadmap favors identity/policy/export adapters and real adoption evidence over broad framework
wrappers that do not strengthen the side-effect boundary.
