from __future__ import annotations

import json
from pathlib import Path
import re

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

    (config_dir / "legend.json").write_text(
        "\n".join(
            [
                "{",
                '  "title": "温度",',
                '  "unit": "°C",',
                '  "type": "gradient",',
                '  "stops": [',
                '    { "value": -20, "color": "#0000FF", "label": "-20" },',
                '    { "value": 0, "color": "#00FF00", "label": "0" },',
                '    { "value": 40, "color": "#FF0000", "label": "40" }',
                "  ]",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_surface_dataset(*, value: float, var: str = "temp") -> xr.Dataset:
    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    data = np.full((1, lat.size, lon.size), value, dtype=np.float32)
    return xr.Dataset(
        {var: xr.DataArray(data, dims=["time", "lat", "lon"], attrs={"units": "°C"})},
        coords={"time": time, "lat": lat, "lon": lon},
    )


def _assert_solid_color(img: Image.Image, *, rgba: tuple[int, int, int, int]) -> None:
    pixels = np.asarray(img)
    assert pixels.ndim == 3
    assert pixels.shape[2] == 4
    assert (pixels == np.asarray(rgba, dtype=np.uint8)).all()


def test_temperature_tile_generator_writes_png_webp_and_legend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import (
        TemperatureTileGenerator,
        get_temperature_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    ds = _make_surface_dataset(value=0.0)
    generator = TemperatureTileGenerator.from_dataset(ds, layer="ecmwf/temp")
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        min_zoom=0,
        max_zoom=0,
        tile_size=8,
        formats=("png", "webp"),
    )
    assert result.layer == "ecmwf/temp"
    assert result.variable == "temp"
    assert result.time == "20260101T000000Z"
    assert result.level == "sfc"
    assert result.tiles_written == 2

    legend_path = tmp_path / "ecmwf" / "temp" / "legend.json"
    assert legend_path.is_file()
    legend = json.loads(legend_path.read_text(encoding="utf-8"))
    assert legend["unit"] == "°C"
    assert legend["min"] == -20
    assert legend["max"] == 40
    assert len(legend["colorStops"]) == 3
    assert re.fullmatch(r"[a-f0-9]{64}", legend["version"]) is not None

    level_legend_path = tmp_path / "ecmwf" / "temp" / result.level / "legend.json"
    assert level_legend_path.is_file()
    level_legend = json.loads(level_legend_path.read_text(encoding="utf-8"))
    assert level_legend["version"] == legend["version"]

    png_path = (
        tmp_path / "ecmwf" / "temp" / result.time / result.level / "0" / "0" / "0.png"
    )
    webp_path = (
        tmp_path / "ecmwf" / "temp" / result.time / result.level / "0" / "0" / "0.webp"
    )
    assert png_path.is_file()
    assert webp_path.is_file()

    img = Image.open(png_path)
    try:
        assert img.mode == "RGBA"
        assert img.size == (8, 8)
        _assert_solid_color(img, rgba=(0, 255, 0, 255))
    finally:
        img.close()

    img = Image.open(webp_path)
    try:
        assert img.size == (8, 8)
        _assert_solid_color(img.convert("RGBA"), rgba=(0, 255, 0, 255))
    finally:
        img.close()


def test_temperature_tile_generator_accepts_grib_style_variable_names(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import (
        TemperatureTileGenerator,
        get_temperature_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    ds = _make_surface_dataset(value=0.0, var="t2m")
    generator = TemperatureTileGenerator.from_dataset(ds, layer="ecmwf/temp")
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        min_zoom=0,
        max_zoom=0,
        tile_size=8,
        formats=("png",),
    )
    assert result.variable == "t2m"

    png_path = (
        tmp_path / "ecmwf" / "temp" / result.time / result.level / "0" / "0" / "0.png"
    )
    assert png_path.is_file()


def test_temperature_tile_generator_selects_valid_time_and_pressure_level(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import (
        TemperatureTileGenerator,
        get_temperature_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(
        ["2026-01-01T00:00:00", "2026-01-01T03:00:00"], dtype="datetime64[s]"
    )
    level = np.array([850.0, 700.0], dtype=np.float32)

    values = np.full(
        (time.size, level.size, lat.size, lon.size), np.nan, dtype=np.float32
    )
    values[1, 0, :, :] = 40.0  # time=03:00, level=850 -> red stop

    ds = xr.Dataset(
        {"temp": xr.DataArray(values, dims=["time", "level", "lat", "lon"])},
        coords={
            "time": time,
            "level": xr.DataArray(level, dims=["level"], attrs={"units": "hPa"}),
            "lat": lat,
            "lon": lon,
        },
    )

    generator = TemperatureTileGenerator.from_dataset(ds, layer="ecmwf/temp")
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T03:00:00Z",
        level="850",
        min_zoom=0,
        max_zoom=0,
        tile_size=4,
        formats=("png",),
    )
    assert result.time == "20260101T030000Z"
    assert result.level == "850"

    tile_path = (
        tmp_path / "ecmwf" / "temp" / result.time / result.level / "0" / "0" / "0.png"
    )
    img = Image.open(tile_path)
    try:
        assert img.size == (4, 4)
        _assert_solid_color(img, rgba=(255, 0, 0, 255))
    finally:
        img.close()


def test_temperature_tile_generator_has_no_visible_seams(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import (
        TemperatureTileGenerator,
        get_temperature_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=32)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")

    # Build a field that is linear in lon so bilinear sampling is exact.
    # Map lon [-180, 180] -> temp [-20, 40].
    lon_grid = np.broadcast_to(lon[None, :], (lat.size, lon.size)).astype(np.float32)
    temp = (lon_grid + 180.0) / 6.0 - 20.0
    ds = xr.Dataset(
        {"temp": xr.DataArray(temp[None, ...], dims=["time", "lat", "lon"])},
        coords={"time": time, "lat": lat, "lon": lon},
    )

    generator = TemperatureTileGenerator.from_dataset(ds, layer="ecmwf/temp")
    tile_size = 32
    left = generator.render_tile(
        zoom=1,
        x=0,
        y=0,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        tile_size=tile_size,
    )
    right = generator.render_tile(
        zoom=1,
        x=1,
        y=0,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        tile_size=tile_size,
    )

    left_px = np.asarray(left)
    right_px = np.asarray(right)

    row = tile_size // 2
    g_left = left_px[row, :, 1].astype(np.int32, copy=False)
    g_right = right_px[row, :, 1].astype(np.int32, copy=False)

    delta_left = abs(int(g_left[-1]) - int(g_left[-2]))
    delta_boundary = abs(int(g_right[0]) - int(g_left[-1]))
    delta_right = abs(int(g_right[1]) - int(g_right[0]))

    assert delta_left > 0
    assert abs(delta_boundary - delta_left) <= 1
    assert abs(delta_boundary - delta_right) <= 1


def test_temperature_tile_generator_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import (
        TemperatureTileGenerator,
        get_temperature_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    ds = _make_surface_dataset(value=0.0)
    generator = TemperatureTileGenerator.from_dataset(ds, layer="ecmwf/temp")

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()

    try:
        (tmp_path / "ecmwf").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not supported in this environment")

    with pytest.raises(ValueError, match="escapes output_dir"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )


def test_temperature_legend_loader_reports_errors(tmp_path: Path) -> None:
    from tiling.temperature_tiles import (
        TemperatureTilingError,
        get_temperature_legend,
        load_temperature_legend,
    )

    config_dir = tmp_path / "cfg"
    config_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(FileNotFoundError, match="Temperature legend file not found"):
        load_temperature_legend(config_dir=config_dir)
    with pytest.raises(FileNotFoundError, match="Temperature legend file not found"):
        get_temperature_legend(config_dir=config_dir)

    (config_dir / "legend.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(TemperatureTilingError, match="not valid JSON"):
        load_temperature_legend(config_dir=config_dir)

    (config_dir / "legend.json").write_text("[]", encoding="utf-8")
    with pytest.raises(TemperatureTilingError, match="must be an object"):
        load_temperature_legend(config_dir=config_dir)


def test_temperature_tile_generator_rejects_bad_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    from datacube.core import DataCube

    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import (
        TemperatureTileGenerator,
        TemperatureTilingError,
        _parse_time,
        _save_tile_image,
        get_temperature_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    ds = _make_surface_dataset(value=0.0)
    cube = DataCube.from_dataset(ds)

    with pytest.raises(ValueError, match="layer"):
        TemperatureTileGenerator(cube, layer="../evil")
    with pytest.raises(ValueError, match="variable must not be empty"):
        TemperatureTileGenerator(cube, variable="")

    generator = TemperatureTileGenerator(cube, layer="ecmwf/temp")

    with pytest.raises(ValueError, match="valid_time must not be empty"):
        generator.generate(
            tmp_path,
            valid_time="",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )

    with pytest.raises(TemperatureTilingError, match="valid_time not found"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T01:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )

    with pytest.raises(TemperatureTilingError, match="level not found"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level=850.0,
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )

    with pytest.raises(ValueError, match="At least one tile format"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=(),
        )
    with pytest.raises(ValueError, match="Unsupported tile format"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("tiff",),
        )

    with pytest.raises(ValueError, match="tile_size must be > 0"):
        generator.render_tile(
            zoom=0,
            x=0,
            y=0,
            valid_time="2026-01-01T00:00:00Z",
            level="sfc",
            tile_size=0,
        )

    assert _parse_time(np.datetime64("2026-01-01T00:00:00")).tzinfo == timezone.utc
    assert _parse_time(datetime(2026, 1, 1, 0, 0, 0)).tzinfo == timezone.utc
    assert _parse_time("20260101T000000Z").tzinfo == timezone.utc

    img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    with pytest.raises(ValueError, match="Unsupported tile file extension"):
        _save_tile_image(img, tmp_path / "tile.tiff")


def test_temperature_tile_generator_surface_level_missing_raises(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import (
        TemperatureTileGenerator,
        TemperatureTilingError,
        get_temperature_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    level = np.array([850.0, 700.0], dtype=np.float32)
    temp = np.zeros((time.size, level.size, lat.size, lon.size), dtype=np.float32)
    ds = xr.Dataset(
        {"temp": xr.DataArray(temp, dims=["time", "level", "lat", "lon"])},
        coords={
            "time": time,
            "level": xr.DataArray(level, dims=["level"], attrs={"units": "hPa"}),
            "lat": lat,
            "lon": lon,
        },
    )
    generator = TemperatureTileGenerator.from_dataset(ds, layer="ecmwf/temp")

    with pytest.raises(TemperatureTilingError, match="surface level requested"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )


def test_temperature_tile_generator_defaults_zoom_range_and_formats(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import (
        TemperatureTileGenerator,
        get_temperature_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=2)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    ds = _make_surface_dataset(value=0.0)
    generator = TemperatureTileGenerator.from_dataset(ds, layer="ecmwf/temp")
    assert generator.variable == "temp"
    assert generator.layer == "ecmwf/temp"

    result = generator.generate(
        tmp_path,
        valid_time="20260101T000000Z",
        level="sfc",
        formats=("png", ""),
    )
    assert result.min_zoom == 0
    assert result.max_zoom == 1
    assert result.tiles_written == 5


def test_temperature_helpers_validate_keys() -> None:
    from tiling.temperature_tiles import (
        _validate_layer,
        _validate_level_key,
        _validate_time_key,
    )

    with pytest.raises(ValueError, match="layer must not be empty"):
        _validate_layer("")
    with pytest.raises(ValueError, match="unsafe"):
        _validate_layer("../evil")

    with pytest.raises(ValueError, match="time_key must not be empty"):
        _validate_time_key("")
    with pytest.raises(ValueError, match="unsafe"):
        _validate_time_key("../evil")

    with pytest.raises(ValueError, match="level_key must not be empty"):
        _validate_level_key("")
    with pytest.raises(ValueError, match="unsafe"):
        _validate_level_key("../evil")


def test_temperature_index_helpers_reject_missing_or_empty_coords() -> None:
    from tiling.temperature_tiles import (
        TemperatureTilingError,
        _resolve_level_index,
        _resolve_time_index,
    )

    ds_missing_time = xr.Dataset(
        coords={"lat": np.array([0.0]), "lon": np.array([0.0])}
    )
    with pytest.raises(
        TemperatureTilingError, match="missing required coordinate: time"
    ):
        _resolve_time_index(ds_missing_time, "2026-01-01T00:00:00Z")

    ds_empty_time = xr.Dataset(coords={"time": np.array([], dtype="datetime64[s]")})
    with pytest.raises(TemperatureTilingError, match="time coordinate is empty"):
        _resolve_time_index(ds_empty_time, "2026-01-01T00:00:00Z")

    ds_missing_level = xr.Dataset(
        coords={"time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")}
    )
    with pytest.raises(
        TemperatureTilingError, match="missing required coordinate: level"
    ):
        _resolve_level_index(ds_missing_level, "850")

    ds_empty_level = xr.Dataset(coords={"level": np.array([], dtype=np.float32)})
    with pytest.raises(TemperatureTilingError, match="level coordinate is empty"):
        _resolve_level_index(ds_empty_level, "850")
