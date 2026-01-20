from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest

from terrain.dem_downloader import DemGrid, DemMosaic
from terrain.poc_pipeline import build_layer_json, generate_tileset, write_layer_json
from terrain.tile_pyramid import GeoRect


@pytest.mark.integration
def test_generate_tileset_writes_expected_files(tmp_path: Path) -> None:
    rect = GeoRect(west=116.0, south=39.0, east=117.0, north=40.0)
    dem = DemMosaic(
        tiles={
            (39, 116): DemGrid(
                west=116.0,
                south=39.0,
                east=117.0,
                north=40.0,
                heights_m=np.array(
                    [
                        [0.0, 10.0, 20.0],
                        [30.0, 40.0, 50.0],
                        [60.0, 70.0, 80.0],
                    ],
                    dtype=np.float32,
                ),
            )
        }
    )

    out_dir = tmp_path / "tileset"
    stats = generate_tileset(
        dem=dem,
        rect=rect,
        out_dir=out_dir,
        min_zoom=0,
        max_zoom=1,
        grid_size=8,
        gzip_payload=False,
    )
    assert stats.tile_count == 2
    assert stats.total_bytes > 0

    # z=0 tile covering (0..180E,-90..90) is x=1,y=0
    assert (out_dir / "0" / "1" / "0.terrain").exists()
    assert (out_dir / "1" / "3" / "1.terrain").exists()

    layer = build_layer_json(
        rect=rect,
        min_zoom=0,
        max_zoom=1,
        dataset="glo30",
        gzip_payload=False,
    )
    write_layer_json(out_dir / "layer.json", layer=layer)
    assert (out_dir / "layer.json").exists()
