"""Geometry regressions for the Harbormaster-maintained prism kernel."""

from __future__ import annotations

import math
from datetime import UTC, datetime, timedelta

import pytest
from shapely.geometry import MultiPolygon, Polygon

from app.components.space_time_prism import Prism, haversine_m, intersect, speed_bounds_for
from app.models import Anchor, AnchorPair, GeoEllipse, SpeedBounds

T0 = datetime(2024, 6, 1, tzinfo=UTC)


def _prism() -> Prism:
    pair = AnchorPair(
        a=Anchor(lat=0.0, lon=0.0, t=T0),
        b=Anchor(lat=0.0, lon=0.02, t=T0 + timedelta(minutes=10)),
    )
    return Prism.compute(pair, SpeedBounds(v_max_mps=10.0))


def _ellipse(center_lon: float, center_lat: float = 1.0) -> GeoEllipse:
    return GeoEllipse(
        a_lat=center_lat - 0.01,
        a_lon=center_lon - 0.01,
        b_lat=center_lat + 0.01,
        b_lon=center_lon + 0.01,
        semi_major_m=1_500.0,
        semi_minor_m=500.0,
        rotation_rad=0.0,
    )


def _antimeridian_prism(start_lon: float = 179.9, end_lon: float = -179.9) -> Prism:
    pair = AnchorPair(
        a=Anchor(lat=0.0, lon=start_lon, t=T0),
        b=Anchor(lat=0.0, lon=end_lon, t=T0 + timedelta(hours=2)),
    )
    return Prism.compute(pair, SpeedBounds(v_max_mps=20.0))


def _longitudes(geometry: Polygon | MultiPolygon) -> list[float]:
    parts = geometry.geoms if isinstance(geometry, MultiPolygon) else (geometry,)
    return [
        x for part in parts for ring in (part.exterior, *part.interiors) for x, _ in ring.coords
    ]


def _assert_rfc7946_winding(geometry: Polygon | MultiPolygon) -> None:
    parts = geometry.geoms if isinstance(geometry, MultiPolygon) else (geometry,)
    assert all(part.exterior.is_ccw for part in parts)
    assert all(not ring.is_ccw for part in parts for ring in part.interiors)


def test_speed_bounds_cover_supported_domains_and_reject_unknown():
    vessel = speed_bounds_for("vessel", vessel_v_max_kts=25.0, vehicle_v_max_kmh=130.0)
    vehicle = speed_bounds_for("vehicle", vessel_v_max_kts=25.0, vehicle_v_max_kmh=130.0)
    pedestrian = speed_bounds_for("pedestrian", vessel_v_max_kts=25.0, vehicle_v_max_kmh=130.0)
    uav = speed_bounds_for("uav", vessel_v_max_kts=25.0, vehicle_v_max_kmh=130.0)

    assert vessel.v_max_mps == pytest.approx(12.8611)
    assert vehicle.v_max_mps == pytest.approx(130.0 / 3.6)
    assert pedestrian.v_max_mps == 2.0
    assert uav.v_max_mps == 30.0
    with pytest.raises(ValueError, match="unknown domain"):
        speed_bounds_for("rail", vessel_v_max_kts=25.0, vehicle_v_max_kmh=130.0)


@pytest.mark.parametrize("method", ["mobr", "ellipse_polygon"])
def test_supplied_ellipse_is_centered_on_its_own_foci(method):
    prism = _prism()
    ellipse = _ellipse(center_lon=2.0)

    polygon = getattr(prism, method)(ellipse)

    assert polygon.centroid.x == pytest.approx(2.0, abs=1e-9)
    assert polygon.centroid.y == pytest.approx(1.0, abs=1e-9)


def test_dynamic_merge_preserves_each_ellipse_location():
    merged = Prism.merge_dynamic([_ellipse(1.0), _ellipse(3.0)], _prism().pair)

    assert merged.geom_type == "MultiPolygon"
    assert len(merged.geoms) == 2
    assert merged.bounds[0] > 0.9
    assert merged.bounds[2] > 2.9


def test_dynamic_merge_accepts_an_empty_input():
    merged = Prism.merge_dynamic([], _prism().pair)

    assert merged.is_empty


@pytest.mark.parametrize("method", ["mobr", "ellipse_polygon"])
def test_supplied_ellipse_keeps_meter_scale_at_different_latitude(method):
    ellipse = _ellipse(center_lon=2.0, center_lat=60.0)

    polygon = getattr(_prism(), method)(ellipse)

    east_radius_m = haversine_m(
        polygon.centroid.y,
        polygon.centroid.x,
        polygon.centroid.y,
        polygon.bounds[2],
    )
    north_radius_m = haversine_m(
        polygon.centroid.y,
        polygon.centroid.x,
        polygon.bounds[3],
        polygon.centroid.x,
    )
    assert east_radius_m == pytest.approx(ellipse.semi_major_m, rel=1e-4)
    assert north_radius_m == pytest.approx(ellipse.semi_minor_m, rel=1e-4)


@pytest.mark.parametrize(
    ("start_lon", "end_lon", "expected_direction"),
    [(179.9, -179.9, 1.0), (-179.9, 179.9, -1.0)],
)
def test_antimeridian_focus_distance_uses_shortest_direction(
    start_lon: float, end_lon: float, expected_direction: float
):
    prism = _antimeridian_prism(start_lon, end_lon)
    ax, ay = prism.proj.to_xy(prism.pair.a.lat, prism.pair.a.lon)
    bx, by = prism.proj.to_xy(prism.pair.b.lat, prism.pair.b.lon)

    assert prism.feasible
    assert math.hypot(bx - ax, by - ay) == pytest.approx(
        haversine_m(0.0, start_lon, 0.0, end_lon), rel=1e-12
    )
    assert math.cos(prism.base_ellipse.rotation_rad) == pytest.approx(expected_direction)
    assert math.sin(prism.base_ellipse.rotation_rad) == pytest.approx(0.0, abs=1e-12)


@pytest.mark.parametrize("method", ["mobr", "ellipse_polygon"])
def test_exact_positive_and_negative_antimeridian_are_the_same_meridian(method: str):
    prism = _antimeridian_prism(180.0, -180.0)
    ax, ay = prism.proj.to_xy(prism.pair.a.lat, prism.pair.a.lon)
    bx, by = prism.proj.to_xy(prism.pair.b.lat, prism.pair.b.lon)

    assert prism.feasible
    assert math.hypot(bx - ax, by - ay) == pytest.approx(0.0, abs=1e-9)
    geometry = getattr(prism, method)()
    assert isinstance(geometry, MultiPolygon)
    _assert_rfc7946_winding(geometry)


@pytest.mark.parametrize("method", ["mobr", "ellipse_polygon"])
@pytest.mark.parametrize("start_lon,end_lon", [(179.9, -179.9), (-179.9, 179.9)])
def test_antimeridian_geometry_is_a_valid_narrow_multipolygon(
    method: str, start_lon: float, end_lon: float
):
    geometry = getattr(_antimeridian_prism(start_lon, end_lon), method)()

    assert isinstance(geometry, MultiPolygon)
    assert geometry.is_valid
    assert len(geometry.geoms) == 2
    assert all(part.bounds[2] - part.bounds[0] < 3.0 for part in geometry.geoms)
    assert all(-180.0 <= longitude <= 180.0 for longitude in _longitudes(geometry))
    _assert_rfc7946_winding(geometry)


@pytest.mark.parametrize("method", ["mobr", "ellipse_polygon"])
@pytest.mark.parametrize("center_lon", [540.0, -540.0])
def test_noncanonical_antimeridian_seams_are_cut_and_normalized(method: str, center_lon: float):
    geometry = getattr(_prism(), method)(_ellipse(center_lon=center_lon))

    assert isinstance(geometry, MultiPolygon)
    assert geometry.is_valid
    assert len(geometry.geoms) == 2
    assert all(-180.0 <= longitude <= 180.0 for longitude in _longitudes(geometry))
    _assert_rfc7946_winding(geometry)


@pytest.mark.parametrize("method", ["mobr", "ellipse_polygon"])
def test_midlatitude_geometry_remains_a_polygon(method: str):
    geometry = getattr(_prism(), method)()

    assert isinstance(geometry, Polygon)
    assert geometry.is_valid


def test_antimeridian_intersection_and_dynamic_merge_preserve_cut_topology():
    prism = _antimeridian_prism()
    ellipse = prism.base_ellipse
    overlapping = GeoEllipse(
        a_lat=ellipse.a_lat + 0.01,
        a_lon=ellipse.a_lon,
        b_lat=ellipse.b_lat + 0.01,
        b_lon=ellipse.b_lon,
        semi_major_m=ellipse.semi_major_m,
        semi_minor_m=ellipse.semi_minor_m,
        rotation_rad=ellipse.rotation_rad,
    )

    intersection = intersect(prism, prism, n_slices=3)
    merged = Prism.merge_dynamic([ellipse, overlapping], prism.pair)

    for geometry in (intersection, merged):
        assert isinstance(geometry, MultiPolygon)
        assert geometry.is_valid
        assert not geometry.is_empty
        assert all(part.bounds[2] - part.bounds[0] < 3.0 for part in geometry.geoms)
        _assert_rfc7946_winding(geometry)


def test_boundary_only_prism_contact_is_an_empty_polygonal_region():
    duration = timedelta(hours=2)
    bounds = SpeedBounds(v_max_mps=20.0)
    first_pair = AnchorPair(
        a=Anchor(lat=0.0, lon=0.0, t=T0),
        b=Anchor(lat=0.0, lon=0.0, t=T0 + duration),
    )
    first = Prism.compute(first_pair, bounds)
    radius_deg = first.ellipse_polygon().bounds[2]
    touching_lon = math.nextafter(2 * radius_deg, -math.inf)
    touching_lat = -7.929729547865502e-17
    second_pair = AnchorPair(
        a=Anchor(lat=touching_lat, lon=touching_lon, t=T0),
        b=Anchor(lat=touching_lat, lon=touching_lon, t=T0 + duration),
    )

    intersection = intersect(first, Prism.compute(second_pair, bounds), n_slices=1)

    assert isinstance(intersection, Polygon)
    assert intersection.is_empty
