from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from PIL import Image


def _write_test_config_dir(config_dir: Path, *, tile_size: int = 8) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)

    (config_dir / "tiling.yaml").write_text(
        "\n".join(
            [
                "tiling:",
                "  crs: EPSG:4326",
                "  global:",
                "    min_zoom: 0",
                "    max_zoom: 1",
                "  event:",
                "    min_zoom: 2",
                "    max_zoom: 2",
                f"  tile_size: {int(tile_size)}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _assert_solid_color(img: Image.Image, *, rgba: tuple[int, int, int, int]) -> None:
    pixels = np.asarray(img)
    assert pixels.ndim == 3
    assert pixels.shape[2] == 4
    assert (pixels == np.asarray(rgba, dtype=np.uint8)).all()


def test_humidity_tile_generator_normalizes_percent_grid(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.humidity_tiles import HumidityTileGenerator

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    level = np.array([850.0], dtype=np.float32)

    # RH values are percent 0-100 but do not provide units.
    values = np.full((1, 1, lat.size, lon.size), 50.0, dtype=np.float32)
    ds = xr.Dataset(
        {"r": xr.DataArray(values, dims=["time", "level", "lat", "lon"])},
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )

    generator = HumidityTileGenerator.from_dataset(ds, layer="ecmwf/humidity")
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T00:00:00Z",
        level="850",
        opacity=1.0,
        min_zoom=0,
        max_zoom=0,
        tile_size=4,
        formats=("png",),
    )
    assert result.time == "20260101T000000Z"
    assert result.level == "850"

    tile_path = (
        tmp_path
        / "ecmwf"
        / "humidity"
        / result.time
        / result.level
        / "0"
        / "0"
        / "0.png"
    )
    img = Image.open(tile_path)
    try:
        assert img.size == (4, 4)
        # 50% -> 0.5 -> alpha = round(0.5 * 255) = 128
        _assert_solid_color(img, rgba=(255, 255, 255, 128))
    finally:
        img.close()
