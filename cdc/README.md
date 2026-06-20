# cdc

Change-data-capture configuration for Harbormaster.

**Lands in:** Phase 3 (Lakehouse and CDC).

**Will contain:** the Debezium connector configuration that captures changes from the operational RDS Postgres (logical replication, `wal_level=logical`, replica identity, incremental snapshot) and streams them through Kinesis into the S3/Iceberg lakehouse. War story P3 (snapshot locking the source on first enable) anticipates the cold-start cost this configuration has to manage.

This is also where the planned Multigres cover-note update is grounded (see `docs/HONESTY.md`): today Harbormaster uses managed Postgres plus Debezium, and it does NOT implement a sharded query router or a consensus layer. That boundary is stated, not blurred.

Empty for now. Phase 0 provisions only foundations and FinOps guardrails.
