# Architecture Decision Records

Records of significant, honestly-scoped design decisions for the Harbormaster platform. Each ADR states what was decided, why, the consequences, and the alternatives considered. Every claim is grounded in the real code and infrastructure; capabilities the platform does not have are labeled as such.

| ADR | Title | Status |
| --- | --- | --- |
| [0001](0001-streaming-per-event-realization.md) | Streaming plane is a per-event keyed realization, not an event-time windowed pipeline | Accepted |
| [0002](0002-cdc-staleness-budget.md) | CDC is replication with an explicit staleness budget and an idempotent LSN guard | Accepted |
| [0003](0003-single-region-dr-rpo-rto.md) | Single-region, single-AZ RDS is a deliberate cost posture under a $75/month cap | Accepted |
| [0004](0004-no-consensus-no-sharded-query-router.md) | No consensus protocol and no sharded query router; coordination is delegated to managed services | Accepted |
