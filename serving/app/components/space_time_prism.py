"""Hägerstrand space-time prism kernel.

Derived from GeoTrace-Agent. Harbormaster maintains a local fork for verified
serving fixes; supplied ellipses are centered on their own foci rather than the
Prism's anchor pair and use the local projection defined by those foci.

Given two anchors A = (lat_A, lon_A, t_A) and B = (lat_B, lon_B, t_B)
with t_A < t_B, and a maximum speed v_max, the set of points reachable
from A by t and able to reach B by t_B is, at each interior time t,
a geo-ellipse with foci A and B and semi-major axis

    a(t) = 0.5 * v_max * (t_B - t_A).

The full prism is the union of these ellipses across t in [t_A, t_B].
This module computes prisms, ellipses, MOBRs, and their intersections.

Math is done in a local equirectangular projection centered on the active
ellipse's foci so that distances are Euclidean to first order. The base ellipse
uses the prism anchor pair; a supplied ellipse uses its own foci. Longitude
deltas follow the shortest wrapped path, and geometry crossing the
antimeridian is cut into normalized polygon components. For continental-scale
or near-polar anchors, switch to a projection designed for that domain.
"""

from __future__ import annotations

import math
from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Any

import numpy as np
from shapely.affinity import rotate, translate
from shapely.geometry import LineString, MultiPolygon, Polygon
from shapely.geometry.base import BaseGeometry
from shapely.geometry.polygon import orient as orient_polygon
from shapely.ops import split

from app.models import AnchorPair, GeoEllipse, SpeedBounds

EARTH_RADIUS_M = 6_371_000.0
KNOTS_TO_MPS = 0.514_444
KMH_TO_MPS = 1 / 3.6

Polygonal = Polygon | MultiPolygon


def speed_bounds_for(
    domain: str, *, vessel_v_max_kts: float, vehicle_v_max_kmh: float
) -> SpeedBounds:
    if domain == "vessel":
        return SpeedBounds(v_max_mps=vessel_v_max_kts * KNOTS_TO_MPS, domain="vessel")
    if domain == "vehicle":
        return SpeedBounds(v_max_mps=vehicle_v_max_kmh * KMH_TO_MPS, domain="vehicle")
    if domain == "pedestrian":
        return SpeedBounds(v_max_mps=2.0, domain="pedestrian")
    if domain == "uav":
        return SpeedBounds(v_max_mps=30.0, domain="uav")
    raise ValueError(f"unknown domain: {domain}")


@dataclass(frozen=True)
class _LocalProjection:
    """Equirectangular projection around a reference latitude."""

    lat_ref_rad: float
    lon_ref_rad: float

    def to_xy(self, lat_deg: float, lon_deg: float) -> tuple[float, float]:
        lat = math.radians(lat_deg)
        lon = math.radians(lon_deg)
        lon_delta = _wrapped_radians(lon - self.lon_ref_rad)
        x = lon_delta * math.cos(self.lat_ref_rad) * EARTH_RADIUS_M
        y = (lat - self.lat_ref_rad) * EARTH_RADIUS_M
        return x, y

    def to_lonlat(self, x: float, y: float) -> tuple[float, float]:
        lat = math.degrees(self.lat_ref_rad + y / EARTH_RADIUS_M)
        lon = math.degrees(self.lon_ref_rad + x / (EARTH_RADIUS_M * math.cos(self.lat_ref_rad)))
        return lon, lat


def _wrapped_radians(angle: float) -> float:
    """Normalize an angle to the half-open interval [-pi, pi)."""

    return (angle + math.pi) % (2 * math.pi) - math.pi


def _midpoint_longitude_rad(a_lon_deg: float, b_lon_deg: float) -> float:
    """Longitude halfway along the shortest wrapped path from A to B."""

    a_lon_rad = math.radians(a_lon_deg)
    b_lon_rad = math.radians(b_lon_deg)
    return a_lon_rad + 0.5 * _wrapped_radians(b_lon_rad - a_lon_rad)


def _shifted_polygon(polygon: Polygon, x_offset: float) -> Polygon:
    """Shift one component and clamp seam roundoff to exact longitude limits."""

    def shift_ring(coords) -> list[tuple[float, float]]:  # type: ignore[no-untyped-def]
        shifted: list[tuple[float, float]] = []
        for x, y in coords:
            longitude = x + x_offset
            if math.isclose(longitude, -180.0, abs_tol=1e-10):
                longitude = -180.0
            elif math.isclose(longitude, 180.0, abs_tol=1e-10):
                longitude = 180.0
            if not -180.0 <= longitude <= 180.0:
                raise ValueError("normalized polygon longitude is outside [-180, 180]")
            shifted.append((longitude, y))
        return shifted

    shell = shift_ring(polygon.exterior.coords)
    holes = [shift_ring(ring.coords) for ring in polygon.interiors]
    return orient_polygon(Polygon(shell, holes), sign=1.0)


def _orient_polygonal(geometry: BaseGeometry) -> Polygonal:
    """Retain positive-area components and apply RFC 7946 winding.

    Shapely Boolean operations may return boundary-only Point or LineString
    intersections, or a GeometryCollection that mixes those with polygons.
    The prism API intentionally exposes only reachable regions with area, so
    non-polygonal components are discarded and boundary-only contact is empty.
    """

    if isinstance(geometry, Polygon):
        return orient_polygon(geometry, sign=1.0)
    if isinstance(geometry, MultiPolygon):
        parts = list(geometry.geoms)
    else:
        parts = []
        for part in getattr(geometry, "geoms", ()):
            if isinstance(part, Polygon):
                parts.append(part)
            elif isinstance(part, MultiPolygon):
                parts.extend(part.geoms)
    oriented = [
        orient_polygon(part, sign=1.0) for part in parts if not part.is_empty and part.area > 0
    ]
    if not oriented:
        return Polygon()
    if len(oriented) == 1:
        return oriented[0]
    return MultiPolygon(oriented)


def _normalize_polygon_longitudes(polygon: Polygon) -> Polygonal:
    """Cut a continuous polygon at every antimeridian seam and normalize it.

    Projection output stays continuous around its local reference and can use
    longitudes outside [-180, 180]. GeoJSON should not draw the closing edge
    across the planet, so each crossed 180 + 360k seam becomes a component
    boundary before the components are shifted into the canonical range.
    """

    min_x, min_y, max_x, max_y = polygon.bounds
    if max_x - min_x >= 360.0:
        raise ValueError("polygon spans 360 degrees or more")

    pieces = [polygon]
    first_k = math.floor((min_x - 180.0) / 360.0) + 1
    last_k = math.ceil((max_x - 180.0) / 360.0) - 1
    for k in range(first_k, last_k + 1):
        seam_x = 180.0 + 360.0 * k
        cutter = LineString([(seam_x, min_y - 1.0), (seam_x, max_y + 1.0)])
        next_pieces: list[Polygon] = []
        for piece in pieces:
            if piece.bounds[0] < seam_x < piece.bounds[2]:
                next_pieces.extend(
                    part
                    for part in split(piece, cutter).geoms
                    if isinstance(part, Polygon) and not part.is_empty
                )
            else:
                next_pieces.append(piece)
        pieces = next_pieces

    normalized: list[Polygon] = []
    for piece in pieces:
        center_x = piece.representative_point().x
        turns = math.floor((center_x + 180.0) / 360.0)
        normalized.append(_shifted_polygon(piece, -360.0 * turns))
    normalized.sort(key=lambda part: part.bounds)
    if len(normalized) == 1:
        return normalized[0]
    return MultiPolygon(normalized)


def _projection_for(pair: AnchorPair) -> _LocalProjection:
    return _LocalProjection(
        lat_ref_rad=math.radians(0.5 * (pair.a.lat + pair.b.lat)),
        lon_ref_rad=_midpoint_longitude_rad(pair.a.lon, pair.b.lon),
    )


def _ellipse_center_xy(proj: _LocalProjection, ellipse: GeoEllipse) -> tuple[float, float]:
    ax, ay = proj.to_xy(ellipse.a_lat, ellipse.a_lon)
    bx, by = proj.to_xy(ellipse.b_lat, ellipse.b_lon)
    return 0.5 * (ax + bx), 0.5 * (ay + by)


def _projection_for_ellipse(ellipse: GeoEllipse) -> _LocalProjection:
    return _LocalProjection(
        lat_ref_rad=math.radians(0.5 * (ellipse.a_lat + ellipse.b_lat)),
        lon_ref_rad=_midpoint_longitude_rad(ellipse.a_lon, ellipse.b_lon),
    )


def haversine_m(a_lat: float, a_lon: float, b_lat: float, b_lon: float) -> float:
    phi1, phi2 = math.radians(a_lat), math.radians(b_lat)
    dphi = phi2 - phi1
    dlam = math.radians(b_lon - a_lon)
    s = math.sin(dphi / 2) ** 2 + math.cos(phi1) * math.cos(phi2) * math.sin(dlam / 2) ** 2
    return 2 * EARTH_RADIUS_M * math.asin(min(1.0, math.sqrt(s)))


@dataclass(frozen=True)
class Prism:
    """A Hägerstrand space-time prism between two anchors.

    `feasible` is False when the anchors are unreachable under v_max,
    in which case `geo_ellipse_at_midpoint` returns a degenerate ellipse.
    """

    pair: AnchorPair
    v_max_mps: float
    duration_s: float
    feasible: bool
    base_ellipse: GeoEllipse
    proj: _LocalProjection

    @classmethod
    def compute(cls, pair: AnchorPair, bounds: SpeedBounds) -> Prism:
        proj = _projection_for(pair)
        ax, ay = proj.to_xy(pair.a.lat, pair.a.lon)
        bx, by = proj.to_xy(pair.b.lat, pair.b.lon)
        d_ab = math.hypot(bx - ax, by - ay)
        duration_s = (pair.b.t - pair.a.t).total_seconds()
        if duration_s <= 0:
            raise ValueError("anchor B must be strictly after anchor A in time")
        L = bounds.v_max_mps * duration_s
        feasible = d_ab - 1e-6 <= L
        # semi-major / semi-minor for the boundary ellipse (the prism's largest cross-section)
        if feasible:
            a_sm = 0.5 * L
            b_sm = 0.5 * math.sqrt(max(0.0, L * L - d_ab * d_ab))
        else:
            a_sm = 0.5 * d_ab
            b_sm = 0.0
        rotation = math.atan2(by - ay, bx - ax)
        return cls(
            pair=pair,
            v_max_mps=bounds.v_max_mps,
            duration_s=duration_s,
            feasible=feasible,
            base_ellipse=GeoEllipse(
                a_lat=pair.a.lat,
                a_lon=pair.a.lon,
                b_lat=pair.b.lat,
                b_lon=pair.b.lon,
                semi_major_m=a_sm,
                semi_minor_m=b_sm,
                rotation_rad=rotation,
            ),
            proj=proj,
        )

    def to_payload(self) -> dict[str, Any]:
        """Flat, JSON-stable serialization for the Temporal activity boundary.

        A Prism holds two live pydantic models (the anchor pair and the base
        ellipse) and a projection dataclass, none of which survive a generic
        dict dump in a form that round-trips through Temporal's data converter.
        This packs the prism into plain JSON so a PRISM activity can hand it to a
        downstream TGARD activity across the boundary; `from_payload` is the exact
        inverse. The round trip is lossless: every field is restored verbatim,
        nothing is recomputed, so the reconstructed prism is identical to the one
        the reasoner produced.
        """

        return {
            "pair": self.pair.model_dump(mode="json"),
            "v_max_mps": self.v_max_mps,
            "duration_s": self.duration_s,
            "feasible": self.feasible,
            "base_ellipse": self.base_ellipse.model_dump(mode="json"),
            "proj": {
                "lat_ref_rad": self.proj.lat_ref_rad,
                "lon_ref_rad": self.proj.lon_ref_rad,
            },
        }

    @classmethod
    def from_payload(cls, data: dict[str, Any]) -> Prism:
        """Rebuild a Prism from `to_payload` output (the inverse round trip)."""

        return cls(
            pair=AnchorPair.model_validate(data["pair"]),
            v_max_mps=data["v_max_mps"],
            duration_s=data["duration_s"],
            feasible=data["feasible"],
            base_ellipse=GeoEllipse.model_validate(data["base_ellipse"]),
            proj=_LocalProjection(
                lat_ref_rad=data["proj"]["lat_ref_rad"],
                lon_ref_rad=data["proj"]["lon_ref_rad"],
            ),
        )

    def ellipse_at(self, t: datetime) -> GeoEllipse:
        """Geo-ellipse that contains all (x, y) reachable by time t.

        For an interior time t in (t_A, t_B), the constraint is

            d(p, A) / v_max <= (t - t_A)
            d(p, B) / v_max <= (t_B - t)

        The intersection of the two disks is an algebraic lens that we
        approximate with the inscribed ellipse for fast geometric
        operations. For exact lens geometry use `lens_at`.
        """

        if not (self.pair.a.t <= t <= self.pair.b.t):
            raise ValueError("t is outside prism time interval")
        r_a = self.v_max_mps * (t - self.pair.a.t).total_seconds()
        r_b = self.v_max_mps * (self.pair.b.t - t).total_seconds()
        d_ab = haversine_m(self.pair.a.lat, self.pair.a.lon, self.pair.b.lat, self.pair.b.lon)
        # Inscribed ellipse: foci at A and B, sum-of-distances <= r_a + r_b
        L = max(r_a + r_b, d_ab)
        a_sm = 0.5 * L
        b_sm = 0.5 * math.sqrt(max(0.0, L * L - d_ab * d_ab))
        return GeoEllipse(
            a_lat=self.pair.a.lat,
            a_lon=self.pair.a.lon,
            b_lat=self.pair.b.lat,
            b_lon=self.pair.b.lon,
            semi_major_m=a_sm,
            semi_minor_m=b_sm,
            rotation_rad=self.base_ellipse.rotation_rad,
        )

    def mobr(self, ellipse: GeoEllipse | None = None) -> Polygonal:
        """Minimum Orthogonal Bounding Rectangle in normalized lon/lat.

        A rectangle crossing the antimeridian is returned as a MultiPolygon so
        GeoJSON consumers do not draw a world-spanning edge.
        """

        e = ellipse or self.base_ellipse
        proj = _projection_for_ellipse(e)
        # rectangle in local xy aligned with ellipse axes and centered on its foci
        cx, cy = _ellipse_center_xy(proj, e)
        a, b, theta = e.semi_major_m, e.semi_minor_m, e.rotation_rad
        local = Polygon([(-a, -b), (a, -b), (a, b), (-a, b)])
        local = rotate(local, math.degrees(theta), origin=(0, 0))
        local = translate(local, cx, cy)
        coords = [proj.to_lonlat(x, y) for x, y in local.exterior.coords]
        return _normalize_polygon_longitudes(Polygon(coords))

    def ellipse_polygon(self, ellipse: GeoEllipse | None = None, n: int = 64) -> Polygonal:
        """Approximate an ellipse as normalized Polygon or MultiPolygon geometry."""

        e = ellipse or self.base_ellipse
        proj = _projection_for_ellipse(e)
        cx, cy = _ellipse_center_xy(proj, e)
        a, b, theta = e.semi_major_m, e.semi_minor_m, e.rotation_rad
        ts = np.linspace(0, 2 * math.pi, n, endpoint=False)
        xs = cx + a * np.cos(ts) * math.cos(theta) - b * np.sin(ts) * math.sin(theta)
        ys = cy + a * np.cos(ts) * math.sin(theta) + b * np.sin(ts) * math.cos(theta)
        coords = [proj.to_lonlat(float(x), float(y)) for x, y in zip(xs, ys, strict=True)]
        return _normalize_polygon_longitudes(Polygon(coords))

    @staticmethod
    def merge_dynamic(ellipses: Iterable[GeoEllipse], pair: AnchorPair) -> Polygonal:
        """Dynamic Region Merge: maximal-union of overlapping ellipses.

        Mirrors STAGD-DRM: indexes ellipses by R*-tree and unions
        connected components. We do the trivial all-pairs union here;
        callers needing scale should swap in the rtree.index lookup.
        """

        proj = _projection_for(pair)
        polys: list[Polygonal] = []
        for e in ellipses:
            p = Prism(
                pair=pair,
                v_max_mps=0.0,
                duration_s=0.0,
                feasible=True,
                base_ellipse=e,
                proj=proj,
            )
            polys.append(p.ellipse_polygon())
        if not polys:
            return Polygon()
        merged = polys[0]
        for poly in polys[1:]:
            merged = merged.union(poly)
        return _orient_polygonal(merged)


def intersect(a: Prism, b: Prism, *, n_slices: int = 16) -> Polygonal:
    """Time-slice intersection of two prisms.

    Returns the union of per-slice ellipse intersections within the
    overlapping time window. Only positive-area polygonal overlap is retained;
    boundary-only point or line contact returns an empty Polygon. Empty also
    means the time windows do not overlap.
    """

    t0 = max(a.pair.a.t, b.pair.a.t)
    t1 = min(a.pair.b.t, b.pair.b.t)
    if t0 >= t1:
        return Polygon()
    slices = np.linspace(0.0, 1.0, n_slices)
    accum = Polygon()
    for s in slices:
        t = t0 + (t1 - t0) * float(s)
        ea = a.ellipse_at(t)
        eb = b.ellipse_at(t)
        pa = a.ellipse_polygon(ea)
        pb = b.ellipse_polygon(eb)
        inter = pa.intersection(pb)
        if not inter.is_empty:
            accum = accum.union(inter)
    return _orient_polygonal(accum)
