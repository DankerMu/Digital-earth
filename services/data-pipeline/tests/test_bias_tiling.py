from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from PIL import Image


def _write_bias_test_config_dir(config_dir: Path, *, tile_size: int = 8) -> None:
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

    (config_dir / "bias_legend.json").write_text(
        "\n".join(
            [
                "{",
                '  "title": "Bias",',
                '  "unit": "°C",',
                '  "type": "gradient",',
                '  "stops": [',
                '    { "value": -5, "color": "#3B82F6", "label": "-5" },',
                '    { "value": 0, "color": "#FFFFFF", "label": "0" },',
                '    { "value": 5, "color": "#EF4444", "label": "5" }',
                "  ]",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (config_dir / "bias_relative_error_legend.json").write_text(
        "\n".join(
            [
                "{",
                '  "title": "Relative Error",',
                '  "unit": "%",',
                '  "type": "gradient",',
                '  "stops": [',
                '    { "value": -100, "color": "#3B82F6", "label": "-100" },',
                '    { "value": 0, "color": "#FFFFFF", "label": "0" },',
                '    { "value": 100, "color": "#EF4444", "label": "100" }',
                "  ]",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_forecast_cube_dataset(*, value: float) -> xr.Dataset:
    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")

    temp = np.full((1, lat.size, lon.size), float(value), dtype=np.float32)
    return xr.Dataset(
        {
            "temp": xr.DataArray(
                temp, dims=("time", "lat", "lon"), attrs={"units": "°C"}
            )
        },
        coords={"time": time, "lat": lat, "lon": lon},
    )


def _make_observation_dataset(*, value: float) -> xr.Dataset:
    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    tmp = np.full((lat.size, lon.size), float(value), dtype=np.float32)
    # Intentionally omit time dim to exercise time alignment code path.
    return xr.Dataset(
        {"TMP": xr.DataArray(tmp, dims=("lat", "lon"), attrs={"units": "°C"})},
        coords={"lat": lat, "lon": lon},
    )


def _read_rgb(path: Path) -> tuple[int, int, int]:
    with Image.open(path) as img:
        rgba = img.convert("RGBA")
        r, g, b, a = rgba.getpixel((0, 0))
        assert a == 255
        return int(r), int(g), int(b)


def test_bias_tiles_generate_and_legend_contains_zero(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube
    from tiling.bias_tiles import BiasTileGenerator
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import get_temperature_legend

    config_dir = tmp_path / "config"
    _write_bias_test_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    forecast_cube = DataCube.from_dataset(_make_forecast_cube_dataset(value=2.0))
    observation = _make_observation_dataset(value=0.0)

    out_dir = tmp_path / "tiles"
    result = BiasTileGenerator(forecast_cube, observation).generate(
        out_dir,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        min_zoom=0,
        max_zoom=0,
        tile_size=8,
        formats=("png",),
    )

    legend_path = out_dir / "bias" / "temp" / "legend.json"
    assert legend_path.is_file()
    legend = json.loads(legend_path.read_text(encoding="utf-8"))
    assert any(
        isinstance(stop, dict) and float(stop.get("value")) == 0.0
        for stop in legend.get("colorStops", [])
    )

    tile_path = (
        out_dir / "bias" / "temp" / result.time / result.level / "0" / "0" / "0.png"
    )
    assert tile_path.is_file()
    r, _, b = _read_rgb(tile_path)
    assert r > b


def test_bias_tiles_negative_values_look_blueish(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube
    from tiling.bias_tiles import BiasTileGenerator
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import get_temperature_legend

    config_dir = tmp_path / "config"
    _write_bias_test_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    forecast_cube = DataCube.from_dataset(_make_forecast_cube_dataset(value=0.0))
    observation = _make_observation_dataset(value=2.0)

    out_dir = tmp_path / "tiles"
    result = BiasTileGenerator(forecast_cube, observation).generate(
        out_dir,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        min_zoom=0,
        max_zoom=0,
        tile_size=8,
        formats=("png",),
    )

    tile_path = (
        out_dir / "bias" / "temp" / result.time / result.level / "0" / "0" / "0.png"
    )
    r, _, b = _read_rgb(tile_path)
    assert b > r


def test_bias_tiles_require_zero_stop_in_legend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube
    from tiling.bias_tiles import BiasTileGenerator, BiasTilingError
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import get_temperature_legend

    config_dir = tmp_path / "config"
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
                "  tile_size: 8",
                "",
            ]
        ),
        encoding="utf-8",
    )
    (config_dir / "bias_legend.json").write_text(
        "\n".join(
            [
                "{",
                '  "title": "Bias",',
                '  "unit": "°C",',
                '  "type": "gradient",',
                '  "stops": [',
                '    { "value": -5, "color": "#3B82F6" },',
                '    { "value": 5, "color": "#EF4444" }',
                "  ]",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    forecast_cube = DataCube.from_dataset(_make_forecast_cube_dataset(value=1.0))
    observation = _make_observation_dataset(value=1.0)

    with pytest.raises(BiasTilingError, match="include a stop at value=0"):
        BiasTileGenerator(forecast_cube, observation).generate(
            tmp_path / "tiles",
            valid_time="2026-01-01T00:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            tile_size=8,
            formats=("png",),
        )


def test_bias_tiles_relative_error_uses_percent_legend_by_default(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube
    from tiling.bias_tiles import BiasTileGenerator
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import get_temperature_legend

    config_dir = tmp_path / "config"
    _write_bias_test_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    forecast_cube = DataCube.from_dataset(_make_forecast_cube_dataset(value=2.0))
    observation = _make_observation_dataset(value=1.0)

    out_dir = tmp_path / "tiles"
    result = BiasTileGenerator(forecast_cube, observation, mode="relative_error").generate(
        out_dir,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        min_zoom=0,
        max_zoom=0,
        tile_size=8,
        formats=("png",),
    )

    legend_path = out_dir / "bias" / "temp" / "legend.json"
    legend = json.loads(legend_path.read_text(encoding="utf-8"))
    assert legend.get("unit") == "%"

    tile_path = (
        out_dir / "bias" / "temp" / result.time / result.level / "0" / "0" / "0.png"
    )
    assert tile_path.is_file()
