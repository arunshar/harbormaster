"""Managed Flink (KDA) feature job (Phase 1.5, gate G5).

Pipeline: Kinesis ais-raw -> parse -> keyBy(MMSI) -> per-vessel keyed state holds
the previous fix -> window_features -> P_phys cheap-gate. Gated events are written
to the DynamoDB online feature store and POSTed to the serving scorer
(/v1/score-ais). The raw stream is teed to S3/Iceberg by the Firehose module, not
here.

The feature/transform logic below is a deliberate, byte-identical duplicate of the
pure, unit-tested functions in streaming.features.features and
streaming.flink.transforms (those files remain the tested source of truth; their
own test suites are unaffected). It is inlined here, not imported, because
FeatureProcess.process_element's stateful KeyedProcessFunction runs in a separate
Python UDF worker subprocess (Beam's process-mode harness) that does not inherit
the driver's sys.path. cloudpickle only serializes a referenced function/class BY
VALUE when it is defined in __main__ (confirmed via cloudpickle's own documented
behavior); anything imported from a real package gets pickled BY REFERENCE, and
the worker then needs that package importable on ITS OWN sys.path. Three separate
attempts to ship streaming.flink.transforms/streaming.features.features as a
runtime dependency all hit real, confirmed bugs in Managed Flink's Python
dependency staging (env.add_python_file: ModuleNotFoundError unchanged across two
full redeploys; pyFiles as two comma-separated paths: FileAlreadyExistsException,
reproduced twice, deterministic; pyFiles as one merged directory: rejected by
AWS's own UpdateApplication validation despite the zip demonstrably containing the
entry) -- real first-live-run findings, W1 sprint window, 2026-07-04. Inlining
into __main__ sidesteps the whole dependency-staging subsystem.

Config comes from Managed Flink's real Runtime Properties mechanism: AWS writes
/etc/flink/application_properties.json at container start (generated from the
Terraform module's environment_properties.property_group blocks), NOT plain OS
environment variables. Confirmed against AWS's own PyFlink example (aws-samples/
amazon-managed-service-for-apache-flink-examples), whose main.py reads this exact
path via a PropertyGroupId lookup; this repo's earlier os.environ[...] reads were
never validated against the real runtime (first-ever live KDA deploy, W1 sprint
window, 2026-07-04) and would have failed identically to the missing-JAR error
this same window caught.

A true 1-minute event-time tumbling window can replace the per-fix keyed process
below; per-fix processing against keyed prev-state is the equivalent realization
used for the demo and keeps the operator to standard, portable PyFlink APIs.
"""

from __future__ import annotations

import json
import math
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from datetime import datetime
from decimal import Decimal

from pyflink.common import Types
from pyflink.common.serialization import SimpleStringSchema
from pyflink.datastream import StreamExecutionEnvironment
from pyflink.datastream.connectors.kinesis import FlinkKinesisConsumer
from pyflink.datastream.functions import KeyedProcessFunction, RuntimeContext
from pyflink.datastream.state import ValueStateDescriptor

APPLICATION_PROPERTIES_FILE_PATH = "/etc/flink/application_properties.json"
FLINK_JOB_PROPERTY_GROUP = "FlinkJob"

# --- inlined from streaming/features/features.py (kept byte-identical; see the
# module docstring above for why this is a duplicate, not an import) ---

EARTH_RADIUS_M = 6_371_000.0
KNOTS_TO_MPS = 0.514_444

# Pinned to the serving config (Settings.vessel_v_max_kts). 25 kts = 12.8611 m/s.
VESSEL_V_MAX_KTS = 25.0
VESSEL_V_MAX_MPS = VESSEL_V_MAX_KTS * KNOTS_TO_MPS

_EPS = 1e-6


@dataclass(frozen=True)
class Fix:
    """One AIS position report (the Flink job's input element)."""

    lat: float
    lon: float
    t: datetime
    sog: float | None = None  # knots
    cog: float | None = None  # deg
    heading: float | None = None  # deg


@dataclass(frozen=True)
class WindowFeatures:
    """Features emitted for one vessel's 1-minute window."""

    sog: float | None
    cog: float | None
    heading: float | None
    gap_since_last_s: float
    distance_m: float
    v_required_mps: float
    p_physical: float


def haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    """Great-circle distance in meters."""

    phi1, phi2 = math.radians(a_lat), math.radians(b_lat)
    dphi = phi2 - phi1
    dlam = math.radians(b_lon - a_lon)
    s = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(s)))


def gap_since_last_s(t_prev: datetime, t_now: datetime) -> float:
    """Seconds since the previous fix (>= 0)."""

    return max(0.0, (t_now - t_prev).total_seconds())


def v_required_mps(distance_m: float, dt_s: float) -> float:
    """Minimum speed (m/s) needed to cover distance_m in dt_s."""

    return distance_m / max(dt_s, _EPS)


def p_physical(v_req_mps: float, v_max_mps: float = VESSEL_V_MAX_MPS) -> float:
    """Kinematic plausibility in (0, 1]: min(1, v_max / max(v_required, eps)).

    1.0 when the move is reachable at v_max; < 1 when it requires more than v_max.
    """

    return min(1.0, v_max_mps / max(v_req_mps, _EPS))


def window_features(
    curr: Fix,
    prev: Fix | None,
    *,
    v_max_mps: float = VESSEL_V_MAX_MPS,
) -> WindowFeatures:
    """Compute the window's features from the current fix and the previous one.

    With no previous fix (vessel's first window) the inter-fix features are zero
    and p_physical is 1.0 (nothing to contradict).
    """

    if prev is None:
        return WindowFeatures(
            sog=curr.sog,
            cog=curr.cog,
            heading=curr.heading,
            gap_since_last_s=0.0,
            distance_m=0.0,
            v_required_mps=0.0,
            p_physical=1.0,
        )
    dt_s = gap_since_last_s(prev.t, curr.t)
    dist = haversine_m(prev.lat, prev.lon, curr.lat, curr.lon)
    v_req = v_required_mps(dist, dt_s)
    return WindowFeatures(
        sog=curr.sog,
        cog=curr.cog,
        heading=curr.heading,
        gap_since_last_s=dt_s,
        distance_m=dist,
        v_required_mps=v_req,
        p_physical=p_physical(v_req, v_max_mps),
    )


# --- inlined from streaming/flink/transforms.py (kept byte-identical; see the
# module docstring above for why this is a duplicate, not an import) ---

# The P_phys cheap-gate: at or above this the event is scored; below it the event
# is dropped / low-priority and never reaches the serving scorer (plan's 0.3).
P_PHYS_GATE = 0.3


def parse_ais_json(raw: str | bytes) -> tuple[int, Fix]:
    """Parse one ais-raw Kinesis record into (mmsi, Fix). Raises ValueError on a
    malformed record so the job can route it to a dead-letter path."""
    try:
        d = json.loads(raw)
        return int(d["mmsi"]), Fix(
            lat=float(d["lat"]),
            lon=float(d["lon"]),
            t=datetime.fromisoformat(str(d["t"]).replace("Z", "+00:00")),
            sog=None if d.get("sog") is None else float(d["sog"]),
            cog=None if d.get("cog") is None else float(d["cog"]),
            heading=None if d.get("heading") is None else float(d["heading"]),
        )
    except (KeyError, ValueError, TypeError) as exc:
        raise ValueError(f"malformed ais record: {exc}") from exc


def passes_gate(feats: WindowFeatures, threshold: float = P_PHYS_GATE) -> bool:
    """True if the window's p_physical clears the cheap-gate (send to the scorer)."""
    return feats.p_physical >= threshold


def feature_item(mmsi: int, feats: WindowFeatures, ts: datetime, ttl_days: int = 7) -> dict:
    """A DynamoDB item for the Feast online table (entity_id + feature_name keyed)."""
    return {
        "entity_id": str(mmsi),
        "feature_name": "window",
        "t": ts.isoformat().replace("+00:00", "Z"),
        "gap_since_last_s": feats.gap_since_last_s,
        "distance_m": feats.distance_m,
        "v_required_mps": feats.v_required_mps,
        "p_physical": feats.p_physical,
        "sog": feats.sog,
        "cog": feats.cog,
        "heading": feats.heading,
        "ttl": int(ts.timestamp()) + ttl_days * 86400,
    }


def _fix_dict(f: Fix) -> dict:
    return {
        "lat": f.lat,
        "lon": f.lon,
        "t": f.t.isoformat().replace("+00:00", "Z"),
        "sog": f.sog,
        "cog": f.cog,
        "heading": f.heading,
    }


def score_request(mmsi: int, fix: Fix, prev: Fix | None = None) -> dict:
    """The POST /v1/score-ais body for one gated event, matching serving's
    AisScoreIn schema: {mmsi, fix, history}. The scorer recomputes its own
    anomaly features server-side from fix + history; it has no features field
    (an earlier version of this function sent Flink's own precomputed
    WindowFeatures under "features", which the real schema never had -- every
    scorer call 422'd, a real first-live-run finding, W1 sprint window,
    2026-07-04). prev, when available, is Flink's own keyed state (the vessel's
    last fix), passed as one-entry history so the scorer sees the same two
    points Flink used for its own cheap gate."""
    return {
        "mmsi": mmsi,
        "fix": _fix_dict(fix),
        "history": [_fix_dict(prev)] if prev is not None else [],
    }


# --- Flink wiring ---


def _read_application_properties() -> list[dict]:
    with open(APPLICATION_PROPERTIES_FILE_PATH) as f:
        return json.load(f)


def _property_group(properties: list[dict], group_id: str) -> dict:
    for group in properties:
        if group["PropertyGroupId"] == group_id:
            return group["PropertyMap"]
    raise KeyError(f"no PropertyGroupId={group_id!r} in {APPLICATION_PROPERTIES_FILE_PATH}")


def _fix_to_json(f: Fix) -> str:
    return json.dumps(
        {"lat": f.lat, "lon": f.lon, "t": f.t.isoformat(), "sog": f.sog, "cog": f.cog,
         "heading": f.heading}
    )


def _fix_from_json(s: str) -> Fix:
    d = json.loads(s)
    return Fix(
        lat=d["lat"], lon=d["lon"], t=datetime.fromisoformat(d["t"]),
        sog=d["sog"], cog=d["cog"], heading=d["heading"],
    )


class FeatureProcess(KeyedProcessFunction):
    """Per-MMSI: compute window features against the previous fix, gate, write the
    gated feature item to DynamoDB, and POST the scorer -- all inline in
    process_element, not a separate .add_sink(). PyFlink's SinkFunction is a thin
    wrapper around a real JVM-side sink class (its __init__ takes a Java class name
    or JavaObject, per pyflink.datastream.functions.SinkFunction); a bare Python
    subclass has no such backing and fails at runtime with
    "AttributeError: '...' object has no attribute '_j_function'" the moment
    .add_sink() tries to invoke it (a real, first-live-run finding, W1 sprint
    window, 2026-07-04). KeyedProcessFunction has no such restriction (it is a
    genuine Python-side function via ProcessFunction's RPC bridge, not a
    JavaFunctionWrapper), so side effects belong here instead. DynamoDB/HTTP
    clients are built lazily per task so the operator still serializes cleanly to
    the Flink cluster."""

    def __init__(self, table: str, region: str, scorer_url: str):
        self._table, self._region, self._url = table, region, scorer_url
        self._ddb = None

    def open(self, ctx: RuntimeContext):
        self._prev = ctx.get_state(ValueStateDescriptor("prev_fix", Types.STRING()))

    def _dynamo(self):
        if self._ddb is None:
            import boto3

            self._ddb = boto3.resource("dynamodb", region_name=self._region).Table(self._table)
        return self._ddb

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

        item = feature_item(mmsi, feats, fix.t)
        request = score_request(mmsi, fix, prev)
        # feature_item()'s ttl is computed from fix.t (the AIS event time), correct
        # for real live data but not for a replayed fixture whose timestamps are
        # historical (2024): that ttl is already years in the past, so DynamoDB's
        # TTL sweeper deletes every written item almost immediately (a real
        # first-live-run finding, W1 sprint window, 2026-07-04 -- items were seen
        # briefly in a table scan, then gone). Override with a wall-clock-based
        # ttl at the write site; feature_item() itself is unchanged (still correct
        # for production use with genuinely current event times).
        item["ttl"] = int(time.time()) + 7 * 86400
        # DynamoDB's put_item rejects native Python float (TypeError: Float types
        # are not supported. Use Decimal types instead), a real first-live-run
        # finding, W1 sprint window, 2026-07-04. feature_item() stays a plain,
        # JSON-friendly pure function (its own unit test asserts a plain float);
        # the round-trip-through-JSON conversion is local to this DynamoDB write.
        self._dynamo().put_item(Item=json.loads(json.dumps(item), parse_float=Decimal))
        body = json.dumps(request).encode()
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

        yield json.dumps({"mmsi": mmsi, "item": item, "request": request})


def main() -> None:
    props = _property_group(_read_application_properties(), FLINK_JOB_PROPERTY_GROUP)
    region = props.get("aws_region", "us-east-1")
    stream = props["kinesis_stream_name"]
    table = props["feast_online_table"]
    scorer_url = props["serving_endpoint"]  # API Gateway invoke URL or Cloud Map DNS

    env = StreamExecutionEnvironment.get_execution_environment()
    # boto3 (used lazily by FeatureProcess._dynamo) is present in the driver's
    # Python environment but not the separate Python UDF worker subprocess;
    # set_python_requirements ships it there. This is a single-file mechanism,
    # distinct from the pyFiles Runtime Property (which hit real, confirmed
    # bugs shipping multiple local-package directories); a real first-live-run
    # finding, W1 sprint window, 2026-07-04.
    env.set_python_requirements(
        os.path.join(os.path.dirname(os.path.abspath(__file__)), "requirements.txt")
    )
    consumer = FlinkKinesisConsumer(
        stream,
        SimpleStringSchema(),
        {"aws.region": region, "flink.stream.initpos": "LATEST"},
    )
    (
        env.add_source(consumer)
        .key_by(lambda raw: json.loads(raw)["mmsi"], key_type=Types.LONG())
        .process(FeatureProcess(table, region, scorer_url), output_type=Types.STRING())
        # .print() (a real Java-backed sink) terminates the graph; the DynamoDB
        # write and the scorer POST already happened as side effects above, so
        # this is just evidence-of-processing in the CloudWatch task logs, not
        # the actual output path.
        .print()
    )
    env.execute("harbormaster-feature-job")


if __name__ == "__main__":
    main()
