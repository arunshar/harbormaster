# P39 local CDC verification (2026-07-12 to 2026-07-13)

```text
make cdc-up && make cdc-smoke && make cdc-down
connector registered (HTTP 201; connector=RUNNING; tasks=RUNNING)
inserted watchlist row for mmsi=368908758
Redis invalidation: hm:online:00000000-0000-0000-0000-000000000000:368908758
CDC audit flushed: rows=1
CDC batch applied: applied=1 content_errors=0 events=1 guard_rejected=0 tombstones=0
[PASS] insert-to-online latency: 4.18s (target <= 5s)
kind delete cluster: completed
```

The consumer initially observed expected Kafka topic-creation races for the
three Debezium topics; the connector and consumer converged and the smoke
completed within the existing five-second target.

## Post-review rerun

A fresh-stack rerun after the migration-order fixes exposed two adjacent local
startup conditions before a warm-topic pass:

```text
attempt 1: connector config PUT succeeded; the immediate status poll returned HTTP 404
later read-only check: connector=RUNNING; tasks=RUNNING
attempt 2: event applied under the tenant-qualified key in 5.06s [SLOW, target <= 5s]
attempt 3: event applied under the tenant-qualified key in 0.55s [PASS, target <= 5s]
make cdc-down: kind cluster deleted
```

The HTTP 404 exposed a registration-status race in the connector poller. It is
fixed and regression-tested in
`docs/drills/CDC_connector_status_poll_race_2026-07-12.md`. The 5.06-second
attempt followed fresh topic-creation warnings. The warm-topic rerun is the P39
smoke; both earlier outcomes are retained here rather than discarded.

## Final fresh-stack verification (2026-07-13)

`make cdc-up` created a fresh kind stack. The first `make cdc-smoke` registered
the connector with HTTP 201 and reported both connector and tasks `RUNNING`, then
stopped before consumer startup because the local `.venv` did not contain the
`confluent_kafka` optional dependency:

```text
ModuleNotFoundError: No module named 'confluent_kafka'
```

That was a local environment setup failure, not a connector or P39 behavior
failure. After installing the declared CDC extra with
`.venv/bin/pip install -e ".[cdc]"`, the smoke reran on the same fresh stack:

```text
connector registered (HTTP 200; connector=RUNNING; tasks=RUNNING)
Redis invalidation: hm:online:00000000-0000-0000-0000-000000000000:368927221
CDC audit flushed: rows=1
CDC batch applied: applied=1 content_errors=0 events=1 guard_rejected=0 tombstones=0
[PASS] insert-to-online latency: 4.28s (target <= 5s)
```

With `make serve-run-cdc` and `make cdc-consumer` running locally, the complete
Phase 2 e2e suite then passed:

```text
tests/e2e/test_phase2.py: 5 passed in 36.41s
```

The five criteria covered flag-to-scored latency, duplicate-free full replay,
Debezium restart recovery, delete propagation, and replication-slot lag alerting.
`make cdc-down` deleted the `hm-cdc` kind cluster; the API and consumer processes
were stopped and no cluster remained.

Artifacts: `/tmp/harbormaster-p39-final-cdc-up.log`,
`/tmp/harbormaster-p39-final-cdc-smoke.log` (the missing-extra setup failure),
`/tmp/harbormaster-p39-final-cdc-smoke-rerun.log`,
`/tmp/harbormaster-p39-final-cdc-e2e.log`,
`/tmp/harbormaster-p39-final-cdc-e2e-junit.xml`,
`/tmp/harbormaster-p39-final-serve-run-cdc.log`,
`/tmp/harbormaster-p39-final-cdc-consumer.log`, and
`/tmp/harbormaster-p39-final-cdc-down.log`.

This was a local kind run. No AWS connector, database, DynamoDB, Redis, or service
was changed.
