# CDC connector status-poll race (2026-07-12 to 2026-07-13)

Scope: local tests and the local kind CDC stack only. No AWS command or
mutation was run.

## Reproduction

On a fresh worker, Kafka Connect accepted the connector config PUT, then the
immediate `GET /connectors/harbormaster-postgres/status` returned HTTP 404. A
later read-only check showed the connector and task both RUNNING. The config
was persisted; the bounded readiness poll treated the visibility delay as a
terminal error.

The deterministic regression failed before the fix:

```text
.venv/bin/python -m pytest -q cdc/tests/test_connector_registration.py \
  -k transient_status_404
FAILED test_registration_retries_transient_status_404_after_put
urllib.error.HTTPError: HTTP Error 404: Not Found
1 failed, 16 deselected in 0.05s
```

## Fix

`register_and_wait` now retries a transient status 404 and connection-level
`URLError` within its existing deadline. Each status request timeout and retry
sleep is capped to the time remaining. Other HTTP failures still raise
immediately. The connector and at least one task must still reach RUNNING.

Focused regression after the fix:

```text
.venv/bin/python -m pytest -q cdc/tests/test_connector_registration.py \
  -k transient_status_404
1 passed, 27 deselected in 0.03s
```

## Fresh-stack verification

```text
make cdc-up
make cdc-smoke
connector registered (HTTP 201; connector=RUNNING; tasks=RUNNING)
[SLOW] insert-to-online latency: 5.29s (target <= 5s)

make cdc-smoke
connector registered (HTTP 200; connector=RUNNING; tasks=RUNNING)
[PASS] insert-to-online latency: 0.54s (target <= 5s)

make serve-run-cdc
make cdc-consumer
make cdc-e2e
5 passed in 34.62s

make cdc-down
Deleted nodes: ["hm-cdc-control-plane"]
```

All five Phase 2 e2e criteria passed: flag-to-scored latency, replay
idempotence, Debezium restart continuity, delete propagation, and stalled-slot
lag alerting. The first smoke is retained because it missed the latency target
while the fresh Kafka topics were created; the second run used those initialized
topics and passed. Both registration attempts observed the connector and its task
as RUNNING, which is the behavior this change protects.

Artifacts: `/tmp/harbormaster-cdc-status-final-up.log`,
`/tmp/harbormaster-cdc-status-final-smoke.log` (5.29-second miss),
`/tmp/harbormaster-cdc-status-final-smoke-rerun.log` (0.54-second pass),
`/tmp/harbormaster-cdc-status-final-api.log`,
`/tmp/harbormaster-cdc-status-final-consumer.log`,
`/tmp/harbormaster-cdc-status-final-e2e.log`,
`/tmp/harbormaster-cdc-status-final-e2e-junit.xml`, and
`/tmp/harbormaster-cdc-status-final-down.log`.

## Repository gates

```text
.venv/bin/python -m pytest -q cdc/tests/test_connector_registration.py
28 passed in 0.14s

.venv/bin/python -m pytest -q cdc/tests/test_connector_registration.py \
  --cov=cdc.connector.registration --cov-branch
28 passed in 0.36s
registration.py line-and-branch coverage: 97.87%

Coverage artifact: `/tmp/harbormaster-cdc-status-coverage.xml`.

make serve-test
952 passed, 20 skipped, 16 warnings in 7.14s

.venv/bin/python -m pytest -q --cov --cov-report=xml:... --junitxml=...
952 passed, 20 skipped, 16 warnings in 12.38s
Repository line-and-branch coverage: 82.54%
```

The full-suite artifacts are
`/tmp/harbormaster-cdc-status-final-source-junit.xml` and
`/tmp/harbormaster-cdc-status-final-source-coverage.xml`. Ruff check, Ruff
format check, Bandit, the replay checksum, the production image build, runtime
imports, health check, and scoring smoke all exited with status 0.
