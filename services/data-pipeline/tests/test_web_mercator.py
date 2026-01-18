from __future__ import annotations

import pytest


def test_clamp_lat_clamps_to_web_mercator_limit() -> None:
    from tiling.web_mercator import WEB_MERCATOR_MAX_LAT, clamp_lat

    assert clamp_lat(0.0) == pytest.approx(0.0)
    assert clamp_lat(100.0) == pytest.approx(WEB_MERCATOR_MAX_LAT)
    assert clamp_lat(-100.0) == pytest.approx(-WEB_MERCATOR_MAX_LAT)


def test_lon_to_tile_x_clamps_to_valid_range() -> None:
    from tiling.web_mercator import lon_to_tile_x

    assert lon_to_tile_x(-180.0, 1) == 0
    assert lon_to_tile_x(0.0, 1) == 1
    assert lon_to_tile_x(180.0, 1) == 1
    assert lon_to_tile_x(9999.0, 1) == 1
    assert lon_to_tile_x(-9999.0, 1) == 0


def test_lat_to_tile_y_clamps_to_valid_range() -> None:
    from tiling.web_mercator import WEB_MERCATOR_MAX_LAT, lat_to_tile_y

    assert lat_to_tile_y(0.0, 1) == 1
    assert lat_to_tile_y(WEB_MERCATOR_MAX_LAT, 1) == 0
    assert lat_to_tile_y(-WEB_MERCATOR_MAX_LAT, 1) == 1
    assert lat_to_tile_y(100.0, 1) == 0
    assert lat_to_tile_y(-100.0, 1) == 1


def test_tile_bounds_are_consistent() -> None:
    from tiling.web_mercator import WEB_MERCATOR_MAX_LAT, tile_bounds

    bounds = tile_bounds(1, x=0, y=0)

    assert bounds.west == pytest.approx(-180.0, abs=1e-6)
    assert bounds.east == pytest.approx(0.0, abs=1e-6)
    assert bounds.north == pytest.approx(WEB_MERCATOR_MAX_LAT, abs=1e-6)
    assert bounds.south == pytest.approx(0.0, abs=1e-6)
    assert bounds.west < bounds.east
    assert bounds.south < bounds.north
