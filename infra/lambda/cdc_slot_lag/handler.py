"""Slot-lag publisher Lambda (Phase 2, gate C7; the alarm side of war story P1).

EventBridge invokes this every minute; it reads pg_replication_slots on the
RDS instance (credentials from the RDS-managed Secrets Manager secret) and
publishes per-slot CloudWatch metrics:

    Harbormaster/CDC  ReplicationSlotLagBytes  {SlotName}
    Harbormaster/CDC  SlotActive               {SlotName}

The CloudWatch alarm in modules/cdc_monitoring fires on sustained lag; the
Lambda deliberately does NOT evaluate thresholds itself (the alarm is the
single place the threshold lives, and missing data is alarm-visible if this
Lambda dies).

Packaging: `make cdc-lambda-package` copies this file plus the shared
cdc/monitor/slot_lag.py into build/ and vendors pg8000 (pure-Python driver;
no compiled layer needed). Terraform zips build/ via the archive provider.
"""

from __future__ import annotations

import json
import os
import ssl

METRIC_NAMESPACE = "Harbormaster/CDC"

try:  # packaged flat in the Lambda zip
    from slot_lag import SLOT_LAG_SQL, rows_to_slot_lags
except ImportError:  # unit tests import from the repo
    from cdc.monitor.slot_lag import SLOT_LAG_SQL, rows_to_slot_lags


def _pg_credentials(boto3_session) -> dict:
    secret_arn = os.environ["PG_SECRET_ARN"]
    sm = boto3_session.client("secretsmanager")
    return json.loads(sm.get_secret_value(SecretId=secret_arn)["SecretString"])


def _fetch_rows() -> list:
    import boto3
    import pg8000.native

    creds = _pg_credentials(boto3.Session())
    # RDS enforces TLS; the RDS CA is not in the Lambda trust store and a
    # 1-minute metrics probe does not need hostname pinning, so verification
    # is disabled here (the connection still encrypts).
    ctx = ssl.create_default_context()
    ctx.check_hostname = False
    ctx.verify_mode = ssl.CERT_NONE
    conn = pg8000.native.Connection(
        user=creds["username"],
        password=creds["password"],
        host=os.environ["PG_HOST"],
        port=int(os.environ.get("PG_PORT", "5432")),
        database=os.environ.get("PG_DB", "harbormaster"),
        ssl_context=ctx,
        timeout=10,
    )
    try:
        return conn.run(SLOT_LAG_SQL)
    finally:
        conn.close()


def _publish(slots) -> None:
    import boto3

    cw = boto3.client("cloudwatch")
    metric_data = []
    for s in slots:
        dims = [{"Name": "SlotName", "Value": s.slot_name}]
        metric_data.append(
            {
                "MetricName": "ReplicationSlotLagBytes",
                "Dimensions": dims,
                "Value": float(s.lag_bytes),
                "Unit": "Bytes",
            }
        )
        metric_data.append(
            {
                "MetricName": "SlotActive",
                "Dimensions": dims,
                "Value": 1.0 if s.active else 0.0,
                "Unit": "Count",
            }
        )
    if metric_data:
        cw.put_metric_data(Namespace=METRIC_NAMESPACE, MetricData=metric_data)


def handler(event, context):
    slots = rows_to_slot_lags(_fetch_rows())
    _publish(slots)
    return {
        "slots": [
            {"slot_name": s.slot_name, "active": s.active, "lag_bytes": s.lag_bytes}
            for s in slots
        ]
    }
