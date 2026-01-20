from __future__ import annotations

import pytest

from terrain.tile_pyramid import (
    GeoRect,
    TileID,
    available_ranges,
    iter_tile_pyramid,
    iter_tiles_in_ranges,
    num_tiles_x,
    num_tiles_y,
    tile_bounds_deg,
    tile_range_for_rectangle,
)


def test_num_tiles_xy() -> None:
    assert num_tiles_x(0) == 2
    assert num_tiles_y(0) == 1
    assert num_tiles_x(1) == 4
    assert num_tiles_y(1) == 2

    with pytest.raises(ValueError):
        num_tiles_x(-1)
    with pytest.raises(ValueError):
        num_tiles_y(-1)


def test_tile_bounds_deg_examples() -> None:
    assert tile_bounds_deg(TileID(z=0, x=0, y=0)) == GeoRect(
        west=-180.0, south=-90.0, east=0.0, north=90.0
    )
    assert tile_bounds_deg(TileID(z=0, x=1, y=0)) == GeoRect(
        west=0.0, south=-90.0, east=180.0, north=90.0
    )
    assert tile_bounds_deg(TileID(z=1, x=3, y=1)) == GeoRect(
        west=90.0, south=0.0, east=180.0, north=90.0
    )


def test_tile_range_for_rectangle_exclusive_end() -> None:
    rect = GeoRect(west=0.0, south=0.0, east=90.0, north=90.0)
    assert tile_range_for_rectangle(rect, 1) == (2, 2, 1, 1)


def test_iter_tile_pyramid_counts() -> None:
    rect = GeoRect(west=116.0, south=39.0, east=117.0, north=40.0)
    tiles = list(iter_tile_pyramid(rect, min_zoom=0, max_zoom=2))
    assert tiles[0] == TileID(z=0, x=1, y=0)
    assert TileID(z=1, x=3, y=1) in tiles
    assert TileID(z=2, x=6, y=2) in tiles


def test_available_ranges_structure() -> None:
    rect = GeoRect(west=0.0, south=0.0, east=90.0, north=90.0)
    avail = available_ranges(rect, min_zoom=0, max_zoom=1)
    assert len(avail) == 2
    assert avail[0] == [{"startX": 1, "startY": 0, "endX": 1, "endY": 0}]
    assert avail[1] == [{"startX": 2, "startY": 1, "endX": 2, "endY": 1}]

    avail_min1 = available_ranges(rect, min_zoom=1, max_zoom=1)
    assert avail_min1 == [[], [{"startX": 2, "startY": 1, "endX": 2, "endY": 1}]]


def test_tile_pyramid_validation_errors() -> None:
    with pytest.raises(ValueError, match="west out of range"):
        GeoRect(west=-181.0, south=0.0, east=0.0, north=1.0)
    with pytest.raises(ValueError, match="Expected west < east"):
        GeoRect(west=1.0, south=0.0, east=1.0, north=1.0)
    with pytest.raises(ValueError, match="Invalid zoom"):
        TileID(z=-1, x=0, y=0)
    with pytest.raises(ValueError, match="x out of range"):
        TileID(z=0, x=2, y=0)
    with pytest.raises(ValueError, match="y out of range"):
        TileID(z=0, x=0, y=1)
    with pytest.raises(ValueError, match="Zoom levels must be"):
        list(
            iter_tile_pyramid(
                GeoRect(west=0, south=0, east=1, north=1), min_zoom=-1, max_zoom=0
            )
        )
    with pytest.raises(ValueError, match="Expected min_zoom"):
        list(
            iter_tile_pyramid(
                GeoRect(west=0, south=0, east=1, north=1), min_zoom=2, max_zoom=1
            )
        )


def test_iter_tiles_in_ranges() -> None:
    tiles = list(iter_tiles_in_ranges([(1, 2, 3, 4)], z=5))
    assert tiles == [
        TileID(z=5, x=1, y=3),
        TileID(z=5, x=1, y=4),
        TileID(z=5, x=2, y=3),
        TileID(z=5, x=2, y=4),
    ]
