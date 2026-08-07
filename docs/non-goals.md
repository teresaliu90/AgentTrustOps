# v0.1 non-goals

The following are deliberately outside the first release:

- building another general-purpose agent or graph orchestration framework;
- replacing Temporal, LangGraph, Langfuse, Promptfoo, or a model gateway;
- executing real refunds, payments, emails, file deletion, or database writes;
- accepting model-provided roles or tenant IDs as authenticated identity;
- automatic compensation for an external side effect with an uncertain outcome (explicit provider
  reconciliation is supported; compensation is not);
- multi-agent coordination, an MCP marketplace, or broad framework coverage;
- Kubernetes, high availability, regional failover, or production SLO claims;
- claiming that a SQLite event table is immutable or cryptographically verified;
- a large web console before the SDK and release gate are independently useful.

Potential adapters belong after the core contracts are stable and tested.
