"""Geometry regressions for the Harbormaster-maintained prism kernel."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta

import pytest

from app.components.space_time_prism import Prism, haversine_m, speed_bounds_for
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
