"""GapDetectorAgent. Extends STAGD + Dynamic Region Merge (DRM).

Detects abnormal trajectory gaps (signal-coverage denial, clandestine
rendezvous) over AIS data using a temporal scan for under-coverage plus a
maximal-union DRM merge over space-time prism geo-ellipses.

The agent computes the Abnormal Gap Measure (AGM):

    AGM(g) = lambda * (1 - P_phys(g)) + (1 - lambda) * P_data(g)

where P_phys is a kinematic plausibility score and P_data is the Pi-DPM
reconstruction-error tail probability for that gap. lambda is 0.6 by default.

Vendored from GeoTrace-Agent and trimmed for the Harbormaster serving slice:
the R*-tree DRM index is replaced by an O(n^2) bounding-box union (faithful for
the demo cardinality; swap rtree.index back in for scale), and the Pi-DPM scorer
uses the numpy surrogate. The real diffusion Pi-DPM is trained on MSI and
promoted into this plane later, replacing `_pi_dpm_score` behind the same call.
"""

from __future__ import annotations

import itertools
import math
from dataclasses import dataclass
from typing import Any

import numpy as np
import structlog
from shapely.geometry import mapping

from app.components.space_time_prism import Prism, speed_bounds_for
from app.config import Settings
from app.models import Anchor, AnchorPair, GeoEllipse

log = structlog.get_logger(__name__)


@dataclass(frozen=True)
class Gap:
    start: Anchor
    end: Anchor
    duration_s: float
    distance_m: float
    p_physical: float
    p_data: float
    abnormal_gap_measure: float
    coverage_polygon_geojson: dict[str, Any]


class GapDetectorAgent:
    def __init__(self, settings: Settings, lam: float = 0.6) -> None:
        self.settings = settings
        self.lam = lam

    async def detect(self, inputs: dict[str, Any]) -> list[Gap]:
        traj: list[Anchor] = [
            a if isinstance(a, Anchor) else Anchor(**a) for a in inputs.get("trajectory", [])
        ]
        coverage_threshold_s: float = float(
            inputs.get("coverage_threshold_s", self.settings.coverage_threshold_s)
        )
        domain: str = str(inputs.get("domain", "vessel"))
        if len(traj) < 2:
            return []

        # 1) raw gaps where consecutive samples are farther apart in time than threshold
        candidates: list[tuple[Anchor, Anchor]] = []
        for a, b in itertools.pairwise(traj):
            if (b.t - a.t).total_seconds() > coverage_threshold_s:
                candidates.append((a, b))
        if not candidates:
            return []

        # 2) build a prism per gap and DRM-merge prisms whose MOBR bboxes overlap
        prisms: list[Prism] = []
        bounds = speed_bounds_for(
            domain,
            vessel_v_max_kts=self.settings.vessel_v_max_kts,
            vehicle_v_max_kmh=self.settings.vehicle_v_max_kmh,
        )
        for a, b in candidates:
            try:
                prisms.append(Prism.compute(AnchorPair(a=a, b=b), bounds))
            except ValueError:
                continue
        if not prisms:
            return []

        bboxes = [p.mobr().bounds for p in prisms]  # (xmin, ymin, xmax, ymax) in lon/lat
        merged: list[set[int]] = []
        seen: set[int] = set()
        for i in range(len(prisms)):
            if i in seen:
                continue
            cluster = {i}
            for j in range(len(prisms)):
                if j != i and _bbox_overlap(bboxes[i], bboxes[j]):
                    cluster.add(j)
            seen |= cluster
            merged.append(cluster)

        gaps: list[Gap] = []
        for cluster in merged:
            members = [prisms[i] for i in cluster]
            ellipses: list[GeoEllipse] = [m.base_ellipse for m in members]
            poly = Prism.merge_dynamic(ellipses, members[0].pair)
            head = members[0]
            p_phys = self._physical_plausibility(head)
            p_data = self._pi_dpm_score(head)
            agm = self.lam * (1.0 - p_phys) + (1.0 - self.lam) * p_data
            gaps.append(
                Gap(
                    start=head.pair.a,
                    end=head.pair.b,
                    duration_s=head.duration_s,
                    distance_m=self._euclidean_anchor(head.pair),
                    p_physical=p_phys,
                    p_data=p_data,
                    abnormal_gap_measure=float(agm),
                    coverage_polygon_geojson=mapping(poly),
                )
            )
        gaps.sort(key=lambda g: g.abnormal_gap_measure, reverse=True)
        return gaps

    # --------------------------------------------------------- internals

    @staticmethod
    def _euclidean_anchor(pair: AnchorPair) -> float:
        lat_ref = 0.5 * (pair.a.lat + pair.b.lat)
        dx = math.radians(pair.b.lon - pair.a.lon) * math.cos(math.radians(lat_ref)) * 6_371_000.0
        dy = math.radians(pair.b.lat - pair.a.lat) * 6_371_000.0
        return math.hypot(dx, dy)

    def _physical_plausibility(self, prism: Prism) -> float:
        """min(1, v_max / v_required): 1.0 when the reappearance is reachable."""

        v_req = self._euclidean_anchor(prism.pair) / max(prism.duration_s, 1.0)
        return float(min(1.0, prism.v_max_mps / max(v_req, 1e-6)))

    def _pi_dpm_score(self, prism: Prism) -> float:
        """Pi-DPM reconstruction-error tail probability (numpy surrogate).

        Longer-duration, longer-distance gaps score as more anomalous, squashed
        to (0, 1). The real diffusion Pi-DPM (trained on MSI) replaces this with
        the same signature once promoted into the serving plane.
        """

        distance = self._euclidean_anchor(prism.pair)
        z = math.log1p(distance) + 0.001 * prism.duration_s
        return float(1 / (1 + np.exp(-((z - 12) / 3))))


def _bbox_overlap(a: tuple, b: tuple) -> bool:
    """Axis-aligned bbox overlap test in (xmin, ymin, xmax, ymax)."""

    return not (a[2] < b[0] or b[2] < a[0] or a[3] < b[1] or b[3] < a[1])
