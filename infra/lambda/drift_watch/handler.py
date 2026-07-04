"""Harbormaster Phase 4 gate 4.6: drift-watch Lambda.

Thin glue only, per this repo's established real-infra boundary: the real
drift-detection logic lives in mlops/drift.py's check_input_drift, vendored
into this Lambda's package (see `make drift-lambda-package`) rather than
duplicated here. This file's own logic is limited to reading the two
parquet snapshots from S3, calling check_input_drift, and publishing an SNS
alert when any feature is flagged; the pure decision path (summarize_drift)
is unit-tested directly, the S3/SNS/boto3 plumbing around it is not.

NOT applied during the 24-hour completion sprint (2026-07-04): authored,
unit-tested, and `terraform validate`/plan-checksum-verified only, per
docs/phases/PHASE_4.md gate 4.6.

Environment variables:
  LAKE_BUCKET             S3 bucket holding the reference/current snapshots.
  REFERENCE_SNAPSHOT_KEY  S3 key of the reference (most recent accepted
                          gate 3.3 training-set export) parquet snapshot.
  CURRENT_SNAPSHOT_KEY    S3 key of the current-window parquet snapshot.
  SNS_TOPIC_ARN           Existing Phase 0 finops SNS topic (no new topic).
"""

from __future__ import annotations

import io
import logging
import os

try:
    import boto3
except ImportError:  # pragma: no cover - always present in the Lambda runtime
    boto3 = None

try:
    import pandas as pd
except ImportError:  # pragma: no cover - vendored by make drift-lambda-package
    pd = None

from mlops.drift import DriftResult, check_input_drift

logger = logging.getLogger()
logger.setLevel(logging.INFO)


def summarize_drift(results: list[DriftResult]) -> tuple[bool, str]:
    """Pure: given check_input_drift's output, decide whether to alert and
    build the message body."""
    drifted = [r for r in results if r.drifted]
    if not drifted:
        return False, "no input drift detected"
    lines = [f"{r.feature}: psi={r.psi:.4f} ks_pvalue={r.ks_pvalue:.2e}" for r in drifted]
    return True, "Harbormaster Phase 4 input-drift alert:\n" + "\n".join(lines)


def _read_parquet_from_s3(s3_client, bucket: str, key: str):
    obj = s3_client.get_object(Bucket=bucket, Key=key)
    return pd.read_parquet(io.BytesIO(obj["Body"].read()))


def handler(event, context):
    bucket = os.environ["LAKE_BUCKET"]
    reference_key = os.environ["REFERENCE_SNAPSHOT_KEY"]
    current_key = os.environ["CURRENT_SNAPSHOT_KEY"]
    topic_arn = os.environ.get("SNS_TOPIC_ARN")

    s3 = boto3.client("s3")
    reference = _read_parquet_from_s3(s3, bucket, reference_key)
    current = _read_parquet_from_s3(s3, bucket, current_key)

    results = check_input_drift(reference, current)
    should_alert, message = summarize_drift(results)
    logger.info(message)

    if should_alert and topic_arn:
        sns = boto3.client("sns")
        sns.publish(
            TopicArn=topic_arn, Subject="Harbormaster: input drift detected", Message=message
        )

    return {
        "drifted_features": [r.feature for r in results if r.drifted],
        "alerted": should_alert and bool(topic_arn),
    }
