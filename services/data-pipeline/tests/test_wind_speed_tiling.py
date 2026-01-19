from __future__ import annotations

import json
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
                "    max_zoom: 0",
                "  event:",
                "    min_zoom: 2",
                "    max_zoom: 2",
                f"  tile_size: {int(tile_size)}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (config_dir / "wind_speed_legend.json").write_text(
        "\n".join(
            [
                "{",
                '  "title": "风速",',
                '  "unit": "m/s",',
                '  "type": "gradient",',
                '  "stops": [',
                '    { "value": 0, "color": "#ECFEFF", "label": "0" },',
                '    { "value": 50, "color": "#4C1D95", "label": "50" }',
                "  ]",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_surface_dataset(*, value: float) -> xr.Dataset:
    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    data = np.full((1, lat.size, lon.size), value, dtype=np.float32)
    return xr.Dataset(
        {
            "wind_speed": xr.DataArray(
                data, dims=["time", "lat", "lon"], attrs={"units": "m/s"}
            )
        },
        coords={"time": time, "lat": lat, "lon": lon},
    )


def test_wind_speed_tile_generator_applies_opacity_and_writes_legend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiles.wind_speed_tiles import WindSpeedTileGenerator
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import get_temperature_legend

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    ds = _make_surface_dataset(value=10.0)
    generator = WindSpeedTileGenerator.from_dataset(ds, opacity=0.5)
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        min_zoom=0,
        max_zoom=0,
        tile_size=8,
        formats=("png",),
    )
    assert result.layer == "ecmwf/wind_speed"
    assert result.variable == "wind_speed"
    assert result.level == "sfc"
    assert result.opacity == pytest.approx(0.5)
    assert result.tiles_written == 1

    tile_path = (
        tmp_path
        / "ecmwf"
        / "wind_speed"
        / result.time
        / result.level
        / "0"
        / "0"
        / "0.png"
    )
    img = Image.open(tile_path)
    try:
        pixels = np.asarray(img)
        assert pixels.shape == (8, 8, 4)
        alpha = pixels[..., 3]
        expected_alpha = int(np.rint(255.0 * 0.5))
        assert alpha.min() == expected_alpha
        assert alpha.max() == expected_alpha
        assert pixels[..., :3].sum() > 0
    finally:
        img.close()

    legend_path = tmp_path / "ecmwf" / "wind_speed" / "legend.json"
    assert legend_path.is_file()
    legend = json.loads(legend_path.read_text(encoding="utf-8"))
    assert legend["unit"] == "m/s"
    assert legend["min"] == 0
    assert legend["max"] == 50

    level_legend_path = tmp_path / "ecmwf" / "wind_speed" / "sfc" / "legend.json"
    assert level_legend_path.is_file()
    level_legend = json.loads(level_legend_path.read_text(encoding="utf-8"))
    assert level_legend["version"] == legend["version"]


def test_wind_speed_tile_generator_rejects_invalid_opacity() -> None:
    from tiles.wind_speed_tiles import WindSpeedTileGenerator

    ds = _make_surface_dataset(value=10.0)
    with pytest.raises(ValueError, match="opacity must be between 0 and 1"):
        WindSpeedTileGenerator.from_dataset(ds, opacity=1.5)
