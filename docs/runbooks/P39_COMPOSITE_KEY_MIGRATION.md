# P39 composite-key migration

This runbook contracts the registry identity from a global business key to
`(tenant_id, business_key)`. The Postgres migration and the derived-store
rebuild are one maintenance window. Completing only the Postgres step makes
existing watchlist and sanctions state disappear from serving because the
reader no longer uses legacy MMSI-only DynamoDB or Redis keys.

## Safety boundary

The local regression tests may run autonomously. Every command against a live
database, Kafka Connect worker, DynamoDB table, Redis service, ECS service, or
AWS resource is human-run in a scheduled window. The `$75/mo` cap and nightly
teardown guard remain in force.

## Preconditions

1. Stop registry writes.
2. Drain and stop the Debezium connector.
3. Stop the CDC consumer after it commits its last completed batch.
4. Record the source-row count and `GROUP BY tenant_id` census for `vessels`,
   `watchlist`, and `sanctions_flags`, plus the count of CDC-owned DynamoDB
   items. If `tenant_id` does not exist, record that fact. If it exists under a
   legacy primary key, classify every non-sentinel tenant before continuing.
   The migration prints the same census and refuses that case until the human
   sets `HM_P39_APPROVE_EXISTING_TENANTS=1` in the reviewed window.
5. Use the forced fresh-snapshot procedure below. Do not substitute a topic
   replay unless a separate review proves that retention contains the complete
   current state, including deletes, and supplies a fresh consumer group.
6. Use a reviewed migration role with `SUPERUSER` or `BYPASSRLS` whenever any of
   the three source tables already has RLS enabled. The migration performs an
   all-tenant census before and after the key change; an RLS-filtered session
   cannot prove row preservation. The script checks this condition and refuses
   to proceed if the role cannot bypass RLS.

The human stops the connector and verifies the target state before running the
Postgres migration:

```text
export CONNECT_URL='<reviewed Connect REST URL>'
export CONNECTOR='harbormaster-postgres'
curl --fail-with-body --silent --show-error --request PUT \
  "$CONNECT_URL/connectors/$CONNECTOR/stop"
for i in $(seq 1 60); do
  CONNECTOR_STATE=$(curl --fail-with-body --silent --show-error \
    "$CONNECT_URL/connectors/$CONNECTOR/status" | jq -r '.connector.state')
  [ "$CONNECTOR_STATE" = 'STOPPED' ] && break
  sleep 1
done
[ "$CONNECTOR_STATE" = 'STOPPED' ]
```

## Postgres contract

The human exports the reviewed DSN and runs:

```text
export HM_P39_CONNECTOR_STOPPED=1
export HM_PG_DSN='<reviewed Postgres DSN>'
# Set only after classifying a pre-existing tenant_id census:
# export HM_P39_APPROVE_EXISTING_TENANTS=1
.venv/bin/python scripts/migrate_p39.py
```

The script runs the three-table migration in one transaction. It creates
tables when absent, adds and sentinel-backfills `tenant_id`, replaces legacy
primary keys, then creates the tenant-qualified sanctions index and replication
DDL. The transaction first acquires the same PostgreSQL advisory lock used by
the Registry and HITL runtime schema bootstraps, then checks that the
`harbormaster_cdc` replication slot is inactive. This serializes migration and
runtime bootstrap DDL, but it does not replace the write and connector stops in
the preconditions. If any source table already has RLS enabled, the transaction
also requires an all-tenant view through `SUPERUSER` or `BYPASSRLS` before it
computes the census. It verifies row-count preservation, null elimination,
exact composite keys, forced RLS, and the tenant policies before commit. A
failure rolls the transaction back.

Do not restart serving yet.

## Required derived-store rebuild

1. Remove or quarantine every old and partially rebuilt DynamoDB item for the
   CDC-owned `vessel_meta`, `watchlist`, and `sanctions:*` feature names,
   including both numeric-only and tenant-qualified entity IDs. Snapshot rows
   apply at guard LSN 0, so they cannot replace a tenant-qualified item that
   already has a positive `last_applied_lsn`. Preserve Flink-owned `window`
   items in the shared table. Clear legacy and tenant-qualified
   `hm:online:*` Redis entries. Do not add a legacy-key fallback to the reader.
2. Back up the stopped connector config, then force Debezium 2.7 to append a
   complete snapshot by changing `snapshot.mode` to `always`. The human runs:

```text
export P39_CONNECTOR_CONFIG='/tmp/p39-connector-config.json'
curl --fail-with-body --silent --show-error \
  "$CONNECT_URL/connectors/$CONNECTOR/config" > "$P39_CONNECTOR_CONFIG"
jq -e '.["snapshot.mode"] == "initial"' "$P39_CONNECTOR_CONFIG"
jq '.["snapshot.mode"] = "always"' "$P39_CONNECTOR_CONFIG" | \
  curl --fail-with-body --silent --show-error --request PUT \
    --header 'Content-Type: application/json' --data-binary @- \
    "$CONNECT_URL/connectors/$CONNECTOR/config"
curl --fail-with-body --silent --show-error --request PUT \
  "$CONNECT_URL/connectors/$CONNECTOR/resume"
for i in $(seq 1 60); do
  CONNECTOR_STATUS=$(curl --fail-with-body --silent --show-error \
    "$CONNECT_URL/connectors/$CONNECTOR/status")
  echo "$CONNECTOR_STATUS" | jq -e \
    '(.connector.state == "RUNNING") and ((.tasks | length) > 0) and \
     ([.tasks[].state] | all(. == "RUNNING"))' && break
  sleep 1
done
echo "$CONNECTOR_STATUS" | jq -e \
  '(.connector.state == "RUNNING") and ((.tasks | length) > 0) and \
   ([.tasks[].state] | all(. == "RUNNING"))'
```

3. Start the CDC consumer at its existing committed offsets. Wait for the
   connector log to show a new `Snapshot completed` after the configuration
   update, then wait for the consumer to apply the snapshot and flush the audit
   sink. Merely reaching connector `RUNNING` is not snapshot evidence.
4. Verify every expected source row is present under
   `entity_id=<tenant_id>:<mmsi>`. Verify no numeric-only entity key remains for
   the three CDC-owned feature-name families. Verify row counts by feature
   family match the source census.
5. Verify Redis contains no pre-migration `hm:online:*` entry.
6. Restore the original connector config. This returns `snapshot.mode` to
   `initial` and prevents another full snapshot on the next ordinary restart:

```text
curl --fail-with-body --silent --show-error --request PUT \
  --header 'Content-Type: application/json' \
  --data-binary "@$P39_CONNECTOR_CONFIG" \
  "$CONNECT_URL/connectors/$CONNECTOR/config"
curl --fail-with-body --silent --show-error --request PUT \
  "$CONNECT_URL/connectors/$CONNECTOR/resume"
```

Repeat the bounded RUNNING status check after restoring the config.

7. Start a restricted serving canary. For one shared MMSI in two test tenants,
   verify two DynamoDB partitions, two cache keys, and tenant-specific serving
   results. Then restore the full serving plane and resume writes.

The exact live DynamoDB cleanup, Redis cleanup, worker-log, consumer, and
service commands depend on the scheduled environment. Generate and review
those commands with the human at the terminal during that window. This branch
does not execute them.

## Rollback

Before the Postgres migration, roll back by restarting the unchanged services.
After the key contract commits, do not restart the old application because its
single-column conflict targets are incompatible. Keep writes stopped and use a
forward fix, then complete the derived-store rebuild.

## Local verification record

The migration, runtime bootstraps, same-MMSI tenant isolation, local production
image, and local kind CDC path were verified on 2026-07-13. See
`docs/drills/P39_test_suite.md` and `docs/drills/P39_local_cdc_smoke.md`. That
evidence does not claim a live AWS migration or derived-store rebuild.
