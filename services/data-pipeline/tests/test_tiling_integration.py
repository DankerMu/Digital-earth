from __future__ import annotations

from pathlib import Path

import numpy as np
import xarray as xr
from PIL import Image


def test_tile_generator_consumes_tiling_yaml(tmp_path: Path, monkeypatch) -> None:
    from tiling.cldas_tiles import CLDASTileGenerator
    from tiling.config import get_tiling_config

    config_path = tmp_path / "tiling.yaml"
    config_path.write_text(
        "\n".join(
            [
                "tiling:",
                "  crs: EPSG:4326",
                "  global:",
                "    min_zoom: 0",
                "    max_zoom: 0",
                "  event:",
                "    min_zoom: 2",
                "    max_zoom: 2",
                "  tile_size: 8",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DIGITAL_EARTH_TILING_CONFIG", str(config_path))
    get_tiling_config.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float64)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float64)
    tmp = np.zeros((1, lat.size, lon.size), dtype=np.float32)
    ds = xr.Dataset(
        {"TMP": xr.DataArray(tmp, dims=["time", "lat", "lon"])},
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": lat,
            "lon": lon,
        },
    )
    ds.attrs["time"] = "2026-01-01T00:00:00Z"

    generator = CLDASTileGenerator(ds, variable="TMP", layer="cldas/tmp")
    try:
        result = generator.generate(tmp_path)
    finally:
        ds.close()

    assert result.min_zoom == 0
    assert result.max_zoom == 0
    assert result.tiles_written == 1

    tile_path = tmp_path / "cldas" / "tmp" / result.time / "0" / "0" / "0.png"
    img = Image.open(tile_path)
    try:
        assert img.size == (8, 8)
    finally:
        img.close()
