# cdc

The Phase 2 change-data-capture pipeline: Postgres (`wal_level=logical`, pgoutput)
-> Debezium on Kafka Connect -> an idempotent, LSN-guarded consumer -> the online
stores (Feast/DynamoDB + Redis invalidation) + an Iceberg `cdc_audit` table.

Execution plan, gates, and invariants: `docs/phases/PHASE_2.md`. Layout:

- `schema/` - DDL for `vessels` / `watchlist` / `sanctions_flags`, replica
  identity, and the `harbormaster_cdc` publication (system of record: Postgres).
- `connector/` - Debezium Postgres connector config generator + validator
  (pgoutput, explicit publication, heartbeats on).
- `consumer/` - envelope parser, the LSN-guarded applier (at-least-once
  transport + idempotent sink), and the Kafka consumer service.
- `sinks/` - DynamoDB online store (conditional-write guard), Redis
  invalidation, Iceberg `cdc_audit` appender.
- `monitor/` - `pg_replication_slots` lag reader + alert evaluator (feeds the
  slot-lag Lambda and drill P1).
- `fixtures/` - recorded Debezium envelopes + `expectations.json` checksums.

Honesty boundary (see `docs/HONESTY.md`): Harbormaster consumes managed Postgres
plus Debezium. It does NOT implement a sharded query router or a consensus
layer; that is Vitess / Multigres territory, and the boundary is stated, not
blurred.
