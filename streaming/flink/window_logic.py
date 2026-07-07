"""Pure, pyflink-free window logic for the Managed Flink feature job (gate G5).

These are the feature/transform helpers the Flink job runs per vessel: compute a
window's features against the previous fix, apply the P_phys cheap-gate, shape the
DynamoDB feature item, and build the /v1/score-ais request body. They import NO
pyflink, so they unit-test without a Flink runtime or AWS.

This block is the same byte-identical duplicate that job.py used to inline (job.py
now imports these names from here instead). It is still a deliberate duplicate of
the tested source of truth in streaming.features.features and
streaming.flink.transforms; the copy exists because FeatureProcess.process_element's
stateful KeyedProcessFunction runs in a separate Python UDF worker subprocess
(Beam's process-mode harness) that does not inherit the driver's sys.path, and
cloudpickle only serializes a referenced function/class BY VALUE when it is defined
in __main__. Keeping these in a sibling module job.py imports from lets them be
imported and tested directly (pyflink absent) while job.py re-inlines them into
__main__ at runtime by importing them at module top; see job.py's module docstring
for the full dependency-staging war story.
"""

from __future__ import annotations

import json
import math
from dataclasses import dataclass
from datetime import datetime

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


def score_request(mmsi: int, fix: Fix, history: list[Fix] | None = None) -> dict:
    """The POST /v1/score-ais body for one gated event, matching serving's
    AisScoreIn schema: {mmsi, fix, history}. The scorer recomputes its own
    anomaly features server-side from fix + history; it has no features field
    (an earlier version of this function sent Flink's own precomputed
    WindowFeatures under "features", which the real schema never had -- every
    scorer call 422'd, a real first-live-run finding, W1 sprint window,
    2026-07-04). history is Flink's own keyed state: the vessel's recent prior
    fixes, oldest first. serving's HeuristicPlanner only routes to abnormal-gap
    detection when n_history (len(history)) is >= 3 (app/agents/
    heuristic_planner.py); sending fewer means gap anomalies are silently never
    evaluated, not just under-scored -- also a real first-live-run finding, W1
    sprint window, 2026-07-04."""
    return {
        "mmsi": mmsi,
        "fix": _fix_dict(fix),
        "history": [_fix_dict(f) for f in (history or [])],
    }
