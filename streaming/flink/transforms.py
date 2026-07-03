"""Pure, runtime-free transforms for the Flink feature job (gate G5).

The Flink keyed-window operator (job.py) reduces each vessel's 1-minute window to
a representative fix, computes features via streaming.features.window_features,
then uses these helpers to gate, shape the DynamoDB feature item, and build the
/v1/score-ais request. Kept pure so they unit-test without a Flink runtime or AWS.
"""

from __future__ import annotations

import json
from datetime import datetime

from features.features import Fix, WindowFeatures

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


def window_representative(fixes: list[Fix]) -> Fix:
    """The 1-min tumbling window reduces to the vessel's latest fix in the window."""
    if not fixes:
        raise ValueError("empty window")
    return max(fixes, key=lambda f: f.t)


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


def score_request(mmsi: int, feats: WindowFeatures, fix: Fix) -> dict:
    """The POST /v1/score-ais body for one gated event."""
    return {
        "mmsi": mmsi,
        "lat": fix.lat,
        "lon": fix.lon,
        "t": fix.t.isoformat().replace("+00:00", "Z"),
        "sog": fix.sog,
        "cog": fix.cog,
        "heading": fix.heading,
        "features": {
            "gap_since_last_s": feats.gap_since_last_s,
            "distance_m": feats.distance_m,
            "v_required_mps": feats.v_required_mps,
            "p_physical": feats.p_physical,
        },
    }
