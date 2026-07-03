# Phase 2 local-stack acceptance run (2026-07-03)

The stack-run-time closeout of docs/phases/PHASE_2.md: the full local plane
brought up from nothing, the envelope fixture re-recorded from the live
topics, the insert-to-online smoke, and the five-criteria e2e, all in one
session on the kind cluster. Everything below is pasted from the live run.

## Stack (kind `hm-cdc`, $0)

| pod | image |
| --- | --- |
| strimzi-cluster-operator | quay.io/strimzi/operator:1.1.0 |
| hm-dual-0 (KRaft broker) | quay.io/strimzi/kafka:1.1.0-kafka-4.3.0 |
| debezium-connect | quay.io/debezium/connect:2.7 |
| postgres | postgres:16-alpine (`-c wal_level=logical`) |
| redis | redis:7-alpine |
| dynamodb-local | amazon/dynamodb-local:2.5.2 |

Host: kind v0.32.0 / Kubernetes v1.36.1 / macOS arm64.

## Finding fixed during bring-up: Strimzi 0.45.0 vs Kubernetes 1.36

The pinned Strimzi 0.45.0 operator crash-looped on the fresh cluster: its
bundled fabric8 kubernetes-client cannot parse the /version response of
current Kubernetes (`Unrecognized field "emulationMajor"` in VersionInfo),
because kind v0.32's Kubernetes 1.36 is far outside 0.45's supported window.
Fix (commit `ea22df4`): bump to Strimzi 1.1.0 and migrate `20-kafka.yaml`
from `kafka.strimzi.io/v1beta2` to the `v1` API (1.x serves only `v1`; KRaft
and node pools are the only mode, so the feature-gate annotations went too).
Verified live: operator Available, `kafka/hm` Ready, Connect Available.

## Fixture re-record (gate 2.6 closeout, commit `d38a0fe`)

`scripts/cdc_record_fixture.py` drove the hand-authored scenario against the
live stack and captured the real Debezium output:

```
fixture re-recorded: cdc/fixtures/debezium_envelopes.jsonl
  sha256 9e316d2143df... -> 3a7340986838...
  envelope census: {'change_events': 8, 'tombstones': 1, 'skips': 2}
  apply census:    {'events': 8, 'applied': 7, 'guard_rejected': 1, 'tombstones': 1}
  final state:     19e8ea9231b4...
```

The census is IDENTICAL to the hand-authored fixture, which is the point of
the exercise: the format assumed at gate 2.3 matches reality. Documented
diffs: real LSNs (both op=r rows share the snapshot consistent-point LSN,
26921376), ZonedTimestamp strings with microseconds, full delete
before-images (REPLICA IDENTITY FULL working), no schema-wrapped lines
(the live converters run schemas.enable=false; that parse path is covered
inline in test_envelope.py now), and no schema-change message (the live
Postgres connector does not emit one; the hand-authored line is retained so
the parser stays covered for planes that do).

## Smoke: insert-to-online latency

```
[PASS] insert-to-online latency: 0.57s (target <= 5s)
```

`make cdc-smoke`: connector registered via REST (generated + validated
config), consumer joined, watchlist INSERT in Postgres visible in DynamoDB
Local in 0.57 s. Redis invalidations fired per delivered event
(`cdc_cache_invalidated` per LSN in the consumer log).

## E2E: the five acceptance criteria in one run

`make cdc-consumer` + `make serve-run-cdc` running, then `make cdc-e2e`:

```
tests/e2e/test_phase2.py::test_a_flag_to_scored_watchlisted_within_target PASSED
tests/e2e/test_phase2.py::test_b_full_topic_replay_produces_no_duplicate_online_state PASSED
tests/e2e/test_phase2.py::test_c_debezium_restart_loses_no_change PASSED
tests/e2e/test_phase2.py::test_d_delete_removes_vessel_from_online_watchlist PASSED
tests/e2e/test_phase2.py::test_e_slot_lag_alert_fires_for_a_stalled_consumer PASSED

============================== 5 passed in 33.50s ==============================
```

- (a) a watchlist flag written through the serving API reached the online
  store and changed live scoring (WATCHLIST_HIT) within the ~5 s target
- (b) a full from-earliest replay under a fresh consumer group left the
  online-state hash byte-identical (the LSN guard, live)
- (c) `kubectl rollout restart deploy/debezium-connect` mid-stream lost no
  change (slot + offsets resume)
- (d) a registry DELETE propagated to the online store and the scorer
  stopped flagging (soft-delete marker read as absent)
- (e) a deliberately stalled slot's lag crossed the drill threshold and
  `evaluate_lag_alert` fired (same predicate the CloudWatch alarm runs on)

Teardown: `make cdc-down` (the cluster is created and deleted per session).
