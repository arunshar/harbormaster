"""Managed Flink (KDA) feature job (Phase 1.5, gate G5).

Pipeline: Kinesis ais-raw -> parse -> keyBy(MMSI) -> per-vessel keyed state holds
the previous fix -> window_features -> P_phys cheap-gate. Gated events are written
to the DynamoDB online feature store and POSTed to the serving scorer
(/v1/score-ais). The raw stream is teed to S3/Iceberg by the Firehose module, not
here.

The per-record logic reuses the pure, unit-tested helpers in streaming.features
and streaming.flink.transforms; this module is the Flink wiring, verified by the
gate-1.5 deploy smoke on the KDA runtime (there is no local Flink to test it).
Records flow as JSON strings so no custom-type serialization is needed; state is a
JSON string too. Config comes from the KDA app's runtime properties / env.

A true 1-minute event-time tumbling window can replace the per-fix keyed process
below; per-fix processing against keyed prev-state is the equivalent realization
used for the demo and keeps the operator to standard, portable PyFlink APIs.
"""

from __future__ import annotations

import json
import os
import urllib.error
import urllib.request

from pyflink.common import Types
from pyflink.common.serialization import SimpleStringSchema
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kinesis import FlinkKinesisConsumer
from pyflink.datastream.functions import KeyedProcessFunction, RuntimeContext, SinkFunction
from pyflink.datastream.state import ValueStateDescriptor

from features.features import Fix, WindowFeatures, window_features
from flink.transforms import feature_item, parse_ais_json, passes_gate, score_request


def _fix_to_json(f: Fix) -> str:
    return json.dumps(
        {"lat": f.lat, "lon": f.lon, "t": f.t.isoformat(), "sog": f.sog, "cog": f.cog,
         "heading": f.heading}
    )


def _fix_from_json(s: str) -> Fix:
    from datetime import datetime

    d = json.loads(s)
    return Fix(
        lat=d["lat"], lon=d["lon"], t=datetime.fromisoformat(d["t"]),
        sog=d["sog"], cog=d["cog"], heading=d["heading"],
    )


class FeatureProcess(KeyedProcessFunction):
    """Per-MMSI: compute window features against the previous fix, gate, and emit a
    JSON envelope {mmsi, item, request} only for events that clear the cheap-gate."""

    def open(self, ctx: RuntimeContext):
        self._prev = ctx.get_state(ValueStateDescriptor("prev_fix", Types.STRING()))

    def process_element(self, raw: str, ctx: KeyedProcessFunction.Context):
        try:
            mmsi, fix = parse_ais_json(raw)
        except ValueError:
            return  # drop malformed records (a dead-letter sink can capture these)

        prev_json = self._prev.value()
        prev = _fix_from_json(prev_json) if prev_json else None
        feats: WindowFeatures = window_features(fix, prev)
        self._prev.update(_fix_to_json(fix))

        if not passes_gate(feats):
            return
        yield json.dumps(
            {
                "mmsi": mmsi,
                "item": feature_item(mmsi, feats, fix.t),
                "request": score_request(mmsi, feats, fix),
            }
        )


class FeatureSink(SinkFunction):
    """Write the feature item to DynamoDB and POST the scorer. Clients are built
    lazily per task so the operator serializes cleanly to the Flink cluster."""

    def __init__(self, table: str, region: str, scorer_url: str):
        self._table, self._region, self._url = table, region, scorer_url
        self._ddb = None

    def _dynamo(self):
        if self._ddb is None:
            import boto3

            self._ddb = boto3.resource("dynamodb", region_name=self._region).Table(self._table)
        return self._ddb

    def invoke(self, value: str, context):
        env = json.loads(value)
        self._dynamo().put_item(Item=env["item"])
        body = json.dumps(env["request"]).encode()
        req = urllib.request.Request(
            f"{self._url.rstrip('/')}/v1/score-ais",
            data=body,
            headers={"Content-Type": "application/json"},
            method="POST",
        )
        try:
            urllib.request.urlopen(req, timeout=5).read()
        except urllib.error.URLError:
            pass  # scoring is best-effort from the stream; HITL still catches it later


def main() -> None:
    region = os.environ.get("AWS_REGION", "us-east-1")
    stream = os.environ["KINESIS_STREAM_NAME"]
    table = os.environ["FEAST_ONLINE_TABLE"]
    scorer_url = os.environ["SERVING_ENDPOINT"]  # API Gateway invoke URL or Cloud Map DNS

    env = StreamExecutionEnvironment.get_execution_environment()
    consumer = FlinkKinesisConsumer(
        stream,
        SimpleStringSchema(),
        {"aws.region": region, "flink.stream.initpos": "LATEST"},
    )
    (
        env.add_source(consumer)
        .key_by(lambda raw: json.loads(raw)["mmsi"], key_type=Types.LONG())
        .process(FeatureProcess(), output_type=Types.STRING())
        .add_sink(FeatureSink(table, region, scorer_url))
    )
    env.execute("harbormaster-feature-job")


if __name__ == "__main__":
    main()
