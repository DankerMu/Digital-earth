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

    (config_dir / "precip_amount_legend.json").write_text(
        "\n".join(
            [
                "{",
                '  "title": "降水强度",',
                '  "unit": "mm/h",',
                '  "type": "gradient",',
                '  "stops": [',
                '    { "value": 0, "color": "#0000FF", "label": "0" },',
                '    { "value": 1, "color": "#FF0000", "label": "1" }',
                "  ]",
                "}",
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


def test_precip_amount_tile_generator_writes_png_webp_and_legend(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.precip_amount_tiles import (
        PrecipAmountTileGenerator,
        get_precip_amount_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_precip_amount_legend.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(
        ["2026-01-01T00:00:00", "2026-01-01T03:00:00"], dtype="datetime64[s]"
    )

    amount = np.zeros((time.size, lat.size, lon.size), dtype=np.float32)
    amount[1, :, :] = 3.0  # 3mm over 3h => 1 mm/h (legend max -> opaque red)

    ds = xr.Dataset(
        {"precipitation_amount": xr.DataArray(amount, dims=["time", "lat", "lon"])},
        coords={"time": time, "lat": lat, "lon": lon},
    )

    generator = PrecipAmountTileGenerator.from_dataset(ds, layer="ecmwf/precip_amount")
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T03:00:00Z",
        level="sfc",
        min_zoom=0,
        max_zoom=0,
        tile_size=8,
        formats=("png", "webp"),
    )
    assert result.layer == "ecmwf/precip_amount"
    assert result.variable == "precipitation_amount"
    assert result.time == "20260101T030000Z"
    assert result.level == "sfc"
    assert result.tiles_written == 2

    legend_path = tmp_path / "ecmwf" / "precip_amount" / "legend.json"
    assert legend_path.is_file()

    png_path = (
        tmp_path
        / "ecmwf"
        / "precip_amount"
        / result.time
        / result.level
        / "0"
        / "0"
        / "0.png"
    )
    webp_path = (
        tmp_path
        / "ecmwf"
        / "precip_amount"
        / result.time
        / result.level
        / "0"
        / "0"
        / "0.webp"
    )
    assert png_path.is_file()
    assert webp_path.is_file()

    img = Image.open(png_path)
    try:
        assert img.mode == "RGBA"
        assert img.size == (8, 8)
        _assert_solid_color(img, rgba=(255, 0, 0, 255))
    finally:
        img.close()

    img = Image.open(webp_path)
    try:
        assert img.size == (8, 8)
        _assert_solid_color(img.convert("RGBA"), rgba=(255, 0, 0, 255))
    finally:
        img.close()


def test_precip_amount_tile_generator_t0_is_transparent(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.precip_amount_tiles import (
        PrecipAmountTileGenerator,
        get_precip_amount_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_precip_amount_legend.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(
        ["2026-01-01T00:00:00", "2026-01-01T03:00:00"], dtype="datetime64[s]"
    )

    # Even if upstream provides a non-zero initial value, t=0 should not render.
    amount = np.zeros((time.size, lat.size, lon.size), dtype=np.float32)
    amount[0, :, :] = 99.0
    amount[1, :, :] = 3.0

    ds = xr.Dataset(
        {"precipitation_amount": xr.DataArray(amount, dims=["time", "lat", "lon"])},
        coords={"time": time, "lat": lat, "lon": lon},
    )

    generator = PrecipAmountTileGenerator.from_dataset(ds, layer="ecmwf/precip_amount")
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        min_zoom=0,
        max_zoom=0,
        tile_size=4,
        formats=("png",),
    )
    tile_path = (
        tmp_path
        / "ecmwf"
        / "precip_amount"
        / result.time
        / result.level
        / "0"
        / "0"
        / "0.png"
    )
    img = Image.open(tile_path)
    try:
        assert img.mode == "RGBA"
        _assert_solid_color(img, rgba=(0, 0, 0, 0))
    finally:
        img.close()


def test_precip_amount_tiling_is_consistent_between_3h_and_6h_steps(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.precip_amount_tiles import (
        PrecipAmountTileGenerator,
        get_precip_amount_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    # Use a wide legend range so that incorrect amount-based rendering (30 vs 60)
    # would produce different colors, while correct intensity rendering (10 vs 10)
    # produces identical tiles.
    (config_dir / "precip_amount_legend.json").write_text(
        "\n".join(
            [
                "{",
                '  "title": "降水强度",',
                '  "unit": "mm/h",',
                '  "type": "gradient",',
                '  "stops": [',
                '    { "value": 0, "color": "#0000FF", "label": "0" },',
                '    { "value": 100, "color": "#FF0000", "label": "100" }',
                "  ]",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_precip_amount_legend.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    # 0h -> 3h -> 9h (3h then 6h)
    time = np.array(
        ["2026-01-01T00:00:00", "2026-01-01T03:00:00", "2026-01-01T09:00:00"],
        dtype="datetime64[s]",
    )

    amount = np.zeros((time.size, lat.size, lon.size), dtype=np.float32)
    amount[1, :, :] = 30.0  # 10 mm/h over 3h
    amount[2, :, :] = 60.0  # 10 mm/h over 6h

    ds = xr.Dataset(
        {"precipitation_amount": xr.DataArray(amount, dims=["time", "lat", "lon"])},
        coords={"time": time, "lat": lat, "lon": lon},
    )

    generator = PrecipAmountTileGenerator.from_dataset(ds, layer="ecmwf/precip_amount")
    img_3h = generator.render_tile(
        zoom=0,
        x=0,
        y=0,
        valid_time="2026-01-01T03:00:00Z",
        level="sfc",
        tile_size=4,
    )
    img_6h = generator.render_tile(
        zoom=0,
        x=0,
        y=0,
        valid_time="2026-01-01T09:00:00Z",
        level="sfc",
        tile_size=4,
    )

    assert (np.asarray(img_3h) == np.asarray(img_6h)).all()
    _assert_solid_color(img_3h, rgba=(26, 0, 230, 26))


def test_precip_legend_loader_reports_errors(tmp_path: Path) -> None:
    from tiling.precip_amount_tiles import (
        PrecipAmountTilingError,
        get_precip_amount_legend,
        load_precip_amount_legend,
    )

    config_dir = tmp_path / "cfg"
    config_dir.mkdir(parents=True, exist_ok=True)

    with pytest.raises(FileNotFoundError, match="Precip legend file not found"):
        load_precip_amount_legend(config_dir=config_dir)
    with pytest.raises(FileNotFoundError, match="Precip legend file not found"):
        get_precip_amount_legend(config_dir=config_dir)

    (config_dir / "precip_amount_legend.json").write_text("not-json", encoding="utf-8")
    with pytest.raises(PrecipAmountTilingError, match="not valid JSON"):
        load_precip_amount_legend(config_dir=config_dir)

    (config_dir / "precip_amount_legend.json").write_text("[]", encoding="utf-8")
    with pytest.raises(PrecipAmountTilingError, match="must be an object"):
        load_precip_amount_legend(config_dir=config_dir)


def test_precip_amount_tile_generator_rejects_bad_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datetime import datetime, timezone

    from datacube.core import DataCube

    from tiling.config import get_tiling_config
    from tiling.precip_amount_tiles import (
        PrecipAmountTileGenerator,
        PrecipAmountTilingError,
        _interval_hours,
        _parse_time,
        _save_tile_image,
        get_precip_amount_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=2)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_precip_amount_legend.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    amount = np.zeros((time.size, lat.size, lon.size), dtype=np.float32)
    ds = xr.Dataset(
        {"precipitation_amount": xr.DataArray(amount, dims=["time", "lat", "lon"])},
        coords={"time": time, "lat": lat, "lon": lon},
    )

    cube = DataCube.from_dataset(ds)

    with pytest.raises(ValueError, match="layer"):
        PrecipAmountTileGenerator(cube, layer="../evil")
    with pytest.raises(ValueError, match="variable must not be empty"):
        PrecipAmountTileGenerator(cube, variable="")

    generator = PrecipAmountTileGenerator(cube, layer="ecmwf/precip_amount")

    with pytest.raises(ValueError, match="valid_time must not be empty"):
        generator.generate(
            tmp_path,
            valid_time="",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            formats=("png",),
        )

    with pytest.raises(PrecipAmountTilingError, match="valid_time not found"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T01:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            formats=("png",),
        )

    with pytest.raises(ValueError, match="level must be 'sfc'"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="850",
            min_zoom=0,
            max_zoom=0,
            formats=("png",),
        )

    with pytest.raises(ValueError, match="At least one tile format"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            formats=(),
        )
    with pytest.raises(ValueError, match="Unsupported tile format"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
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

    with pytest.raises(
        PrecipAmountTilingError, match="time coordinate must be strictly"
    ):
        _interval_hours(
            np.array(
                ["2026-01-01T00:00:00", "2026-01-01T00:00:00"], dtype="datetime64[s]"
            ),
            1,
        )


def test_precip_amount_tile_generator_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.precip_amount_tiles import (
        PrecipAmountTileGenerator,
        get_precip_amount_legend,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=2)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_precip_amount_legend.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(
        ["2026-01-01T00:00:00", "2026-01-01T03:00:00"], dtype="datetime64[s]"
    )
    amount = np.zeros((time.size, lat.size, lon.size), dtype=np.float32)
    amount[1, :, :] = 3.0
    ds = xr.Dataset(
        {"precipitation_amount": xr.DataArray(amount, dims=["time", "lat", "lon"])},
        coords={"time": time, "lat": lat, "lon": lon},
    )
    generator = PrecipAmountTileGenerator.from_dataset(ds, layer="ecmwf/precip_amount")

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()

    try:
        (tmp_path / "ecmwf").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not supported in this environment")

    with pytest.raises(ValueError, match="escapes output_dir"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T03:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            tile_size=2,
            formats=("png",),
        )


def test_precip_amount_helpers_validate_keys() -> None:
    from tiling.precip_amount_tiles import (
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
