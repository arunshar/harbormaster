# ADR 0002: CDC is replication with an explicit staleness budget and an idempotent LSN guard

**Status:** Accepted

**Date:** 2026-07-06

## Context

The Phase 2 pipeline replicates Postgres operational state into the online stores and an Iceberg audit table: logical decoding (pgoutput) to Debezium on Kafka Connect to the LSN-guarded applier in `cdc/consumer/applier.py`. This is asynchronous replication, not a synchronous read path, so downstream stores are always some amount of time behind the primary. That lag is a budget to state plainly, not a guarantee of zero staleness. The applier delivers exactly-once honestly: at-least-once Kafka transport plus an idempotent sink. It applies a batch in delivery order, flushes every sink, and only then calls `commit()`; if any sink raises, offsets stay uncommitted and the redelivered batch reconverges.

## Decision

Treat CDC as replication under an explicit staleness budget. The freshness contract is: online stores reflect a committed Postgres change within the end-to-end replication lag (WAL decode + Debezium + Kafka + applier flush), monitored by `pg_replication_slots` lag alerting. Idempotency is enforced by a per-`(table, pk)` monotonic LSN guard: an event whose LSN does not exceed the stored LSN no-ops, so duplicates and stale replays are dropped, deletes leave a canonical marker with no lower-LSN resurrection, and snapshot reads apply at a floor LSN of 0.

## Consequences

Positive: replay-safe, restart-safe, delete-safe convergence; slot-lag alerting makes the budget observable; the audit table is transport truth and the state store is state truth, which is exactly the replay demo (invariant 5). Negative and documented, not hidden: staleness is nonzero and grows with lag or a stalled slot; state writes are durable per event while audit rows buffer until batch flush, so a crash mid-batch can re-record an already-applied event as `applied=False` after redelivery. Exact cross-store atomicity would need an outbox, which is out of scope; invariant 5 holds absent mid-batch crashes.

## Alternatives considered

**Synchronous dual-write from the app.** Rejected: couples the write path to every downstream store, loses replay-safety, and has no ordered log to reconverge against after a partial failure.

**At-least-once with no idempotent sink.** Rejected: redelivery would double-apply and stale replays would resurrect deleted rows. The monotonic LSN guard is what makes at-least-once transport safe.
