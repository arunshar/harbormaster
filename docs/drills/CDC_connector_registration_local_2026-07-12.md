# CDC connector registration: local root-cause and regression run

Date: 2026-07-12 PDT

Scope: local kind cluster only. No AWS command was run. The corrected ECS Exec
command has not been retried against AWS.

## Baseline

```
make serve-install
make serve-test
```

Result: 677 passed, 14 skipped, 16 warnings in 7.48 seconds.

## Reproduction

The initial requested sequence brought up the stack and registered the
connector, but static inspection showed that the local harness bypassed the
reported provider path:

- `deploy/k8s/cdc/30-connect.yaml` had no `config.providers` setting.
- `scripts/cdc_smoke.py` and `scripts/cdc_record_fixture.py` passed the literal
  local password instead of the config-provider placeholder.
- The initial `make cdc-e2e` run had 2 failed and 3 passed because the required
  serving process was not listening on `localhost:8000`. This was separate from
  connector registration.

Replaying the W3 runbook's nested unquoted heredoc locally produced:

```
transported_password_length=0
placeholder_survived=False
```

The remote Bash expanded `${dir:/dev/shm/secrets:password}` before curl sent the
request. Kafka Connect never received the placeholder.

Kafka 3.7 source confirms that `AbstractHerder.validateConnectorConfig`
transforms connector properties before `Connector.validate()`. The runtime path
uses the same transformer, and the PUT endpoint has no force option that bypasses
validation.

Primary-source references:

- [Kafka 3.7 AbstractHerder](https://github.com/apache/kafka/blob/3.7.0/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/AbstractHerder.java#L484-L567)
- [Kafka 3.7 ConfigTransformer](https://github.com/apache/kafka/blob/3.7.0/clients/src/main/java/org/apache/kafka/common/config/ConfigTransformer.java#L93-L159)
- [Kafka 3.7 ConnectorsResource](https://github.com/apache/kafka/blob/3.7.0/connect/runtime/src/main/java/org/apache/kafka/connect/runtime/rest/resources/ConnectorsResource.java#L221-L242)
- [Kafka 3.7 ClusterConfigState](https://github.com/apache/kafka/blob/3.7.0/connect/runtime/src/main/java/org/apache/kafka/connect/storage/ClusterConfigState.java#L141-L154)

## Fix

- `cdc.connector.registration` base64-encodes the flat connector config and
  emits the ECS Exec command without a shell-visible `${...}` sequence.
- The local kind deployment now writes the local throwaway password to
  `/dev/shm/secrets/password`, enables `DirectoryConfigProvider`, and starts the
  stock Debezium entrypoint.
- The smoke and fixture scripts now send the default `${dir:...}` reference and
  require both connector and task state to reach `RUNNING`.

## Fresh-stack regression

```
make cdc-up
make cdc-smoke
make serve-run-cdc
make cdc-consumer
make cdc-e2e
make cdc-down
```

Worker evidence:

```
config.providers=dir
config.providers.dir.class=org.apache.kafka.common.config.provider.DirectoryConfigProvider
600 11 kafka:kafka
```

First connector registration on the fresh stack:

```
connector registered (HTTP 201; connector=RUNNING; tasks=RUNNING)
```

The first smoke latency sample was 5.62 seconds and missed the existing 5-second
target. A single warmed rerun registered idempotently with HTTP 200 and measured
0.44 seconds, passing the target. Both results are retained here to avoid hiding
the cold sample.

With the required serving and consumer processes running, Phase 2 e2e completed:

```
test_a_flag_to_scored_watchlisted_within_target PASSED
test_b_full_topic_replay_produces_no_duplicate_online_state PASSED
test_c_debezium_restart_loses_no_change PASSED
test_d_delete_removes_vessel_from_online_watchlist PASSED
test_e_slot_lag_alert_fires_for_a_stalled_consumer PASSED

5 passed, 23 warnings in 36.00 seconds
```

VERDICT: PASS locally. Connector registration and task startup are proven on the
same Debezium 2.7 / Kafka Connect 3.7 image family. AWS remains unverified until
the corrected command is run by Arun in a scheduled human-run window.

## Post-fix repository gates

```
make serve-test
make serve-lint
make validate
```

Result: 693 passed, 14 skipped, 16 warnings in 6.82 seconds; lint passed;
Terraform validation passed. Focused line and branch coverage across
`cdc.connector.config` and `cdc.connector.registration` was 100% (97 statements,
28 branches, zero misses).
