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


def test_tcc_tile_generator_normalizes_percent_grid_globally(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Ensure percent-vs-fraction is inferred from the whole grid (not per-tile)."""

    from tiling.config import get_tiling_config
    from tiling.tcc_tiles import TccTileGenerator

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")

    # Values are "percent" 0-100 but do not provide units; the NE corner has 80
    # so the whole grid is inferred as 0-100, while the NW tile stays at 0.5%.
    values = np.full((1, lat.size, lon.size), 0.5, dtype=np.float32)
    values[:, :, -1] = 80.0
    ds = xr.Dataset(
        {"tcc": xr.DataArray(values, dims=["time", "lat", "lon"])},
        coords={"time": time, "lat": lat, "lon": lon},
    )

    generator = TccTileGenerator.from_dataset(ds, layer="ecmwf/tcc")
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        min_zoom=1,
        max_zoom=1,
        tile_size=4,
        formats=("png",),
    )
    assert result.time == "20260101T000000Z"
    assert result.level == "sfc"

    tile_path = (
        tmp_path / "ecmwf" / "tcc" / result.time / result.level / "1" / "0" / "0.png"
    )
    img = Image.open(tile_path)
    try:
        assert img.size == (4, 4)
        # 0.5% -> 0.005 -> alpha = round(0.005 * 255) = 1
        _assert_solid_color(img, rgba=(255, 255, 255, 1))
    finally:
        img.close()


def test_tcc_tile_generator_prefers_time_coord_over_attrs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.tcc_tiles import TccTileGenerator

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=2)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(
        ["2026-01-01T00:00:00", "2026-01-01T03:00:00"], dtype="datetime64[s]"
    )
    values = np.full((time.size, lat.size, lon.size), 0.5, dtype=np.float32)
    ds = xr.Dataset(
        {
            "tcc": xr.DataArray(
                values, dims=["time", "lat", "lon"], attrs={"units": "1"}
            )
        },
        coords={"time": time, "lat": lat, "lon": lon},
    )
    ds.attrs["time"] = "2026-01-01T00:00:00Z"

    generator = TccTileGenerator.from_dataset(ds, layer="ecmwf/tcc")
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T03:00:00Z",
        level="sfc",
        min_zoom=0,
        max_zoom=0,
        tile_size=2,
        formats=("png",),
        opacity=0.5,
    )
    assert result.time == "20260101T030000Z"

    tile_path = (
        tmp_path / "ecmwf" / "tcc" / result.time / result.level / "0" / "0" / "0.png"
    )
    img = Image.open(tile_path)
    try:
        # fraction=0.5, opacity=0.5 -> alpha = round(0.25 * 255) = 64
        _assert_solid_color(img, rgba=(255, 255, 255, 64))
    finally:
        img.close()


def test_tcc_tile_generator_respects_units_and_writes_webp(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.tcc_tiles import TccTileGenerator

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")

    # Explicit percent units with low values should still be treated as 0-100.
    values = np.full((1, lat.size, lon.size), 0.5, dtype=np.float32)
    ds = xr.Dataset(
        {
            "tcc": xr.DataArray(
                values, dims=["time", "lat", "lon"], attrs={"units": "%"}
            )
        },
        coords={"time": time, "lat": lat, "lon": lon},
    )

    generator = TccTileGenerator.from_dataset(ds, layer="ecmwf/tcc")
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T00:00:00Z",
        level="sfc",
        min_zoom=0,
        max_zoom=0,
        tile_size=4,
        formats=("png", "webp"),
    )
    assert result.tiles_written == 2

    png_path = (
        tmp_path / "ecmwf" / "tcc" / result.time / result.level / "0" / "0" / "0.png"
    )
    webp_path = (
        tmp_path / "ecmwf" / "tcc" / result.time / result.level / "0" / "0" / "0.webp"
    )
    assert png_path.is_file()
    assert webp_path.is_file()

    img = Image.open(png_path)
    try:
        _assert_solid_color(img, rgba=(255, 255, 255, 1))
    finally:
        img.close()

    img = Image.open(webp_path)
    try:
        _assert_solid_color(img.convert("RGBA"), rgba=(255, 255, 255, 1))
    finally:
        img.close()


def test_tcc_tile_generator_rejects_symlink_escape(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.tcc_tiles import TccTileGenerator

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=2)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    values = np.zeros((1, lat.size, lon.size), dtype=np.float32)
    ds = xr.Dataset(
        {
            "tcc": xr.DataArray(
                values, dims=["time", "lat", "lon"], attrs={"units": "1"}
            )
        },
        coords={"time": time, "lat": lat, "lon": lon},
    )

    generator = TccTileGenerator.from_dataset(ds, layer="ecmwf/tcc")

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
            tile_size=2,
            formats=("png",),
        )


def test_tcc_helpers_validate_keys_and_time_parsing() -> None:
    from datetime import datetime, timezone

    from tiling.tcc_tiles import (
        TccTilingError,
        _parse_time,
        _resolve_time_index,
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

    assert _parse_time(np.datetime64("2026-01-01T00:00:00")).tzinfo == timezone.utc
    assert _parse_time(datetime(2026, 1, 1, 0, 0, 0)).tzinfo == timezone.utc
    assert _parse_time("20260101T000000Z").tzinfo == timezone.utc

    with pytest.raises(ValueError, match="valid_time must not be empty"):
        _parse_time("")

    ds = xr.Dataset(
        coords={"lat": [0.0], "lon": [0.0]}, attrs={"time": "2026-01-01T00:00:00Z"}
    )
    idx, key = _resolve_time_index(ds, valid_time="ignored")
    assert idx == 0
    assert key == "20260101T000000Z"

    with pytest.raises(
        TccTilingError, match="Dataset missing required coordinate: time"
    ):
        _resolve_time_index(xr.Dataset(), valid_time="2026-01-01T00:00:00Z")


def test_tcc_rgba_and_format_helpers(tmp_path: Path) -> None:
    from tiling.tcc_tiles import _save_tile_image, _validate_tile_formats, tcc_rgba

    with pytest.raises(ValueError, match="opacity must be between 0 and 1"):
        tcc_rgba(np.zeros((1, 1), dtype=np.float32), opacity=-0.1)

    with pytest.raises(ValueError, match="At least one tile format"):
        _validate_tile_formats(())
    with pytest.raises(ValueError, match="Unsupported tile format"):
        _validate_tile_formats(("tiff",))

    assert _validate_tile_formats(("png", "", "png")) == ("png",)

    img = Image.new("RGBA", (1, 1), (255, 255, 255, 255))
    with pytest.raises(ValueError, match="Unsupported tile file extension"):
        _save_tile_image(img, tmp_path / "tile.tiff")


def test_tcc_tile_generator_defaults_and_render_tile(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube

    from tiling.config import get_tiling_config
    from tiling.tcc_tiles import TccTileGenerator, TccTilingError

    config_dir = tmp_path / "config"
    # Make the default zoom range just a single tile.
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
                "    min_zoom: 1",
                "    max_zoom: 1",
                "  tile_size: 2",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    values = np.full((1, lat.size, lon.size), 0.5, dtype=np.float32)
    ds = xr.Dataset(
        {
            "tcc": xr.DataArray(
                values, dims=["time", "lat", "lon"], attrs={"units": "1"}
            )
        },
        coords={"time": time, "lat": lat, "lon": lon},
    )

    cube = DataCube.from_dataset(ds)
    with pytest.raises(ValueError, match="variable must not be empty"):
        TccTileGenerator(cube, variable="")

    generator = TccTileGenerator(cube, layer="ecmwf/tcc")
    assert generator.variable == "tcc"
    assert generator.layer == "ecmwf/tcc"

    result = generator.generate(
        tmp_path, valid_time="2026-01-01T00:00:00Z", level="sfc", formats=("png", "")
    )
    assert result.tiles_written == 1

    with pytest.raises(ValueError, match="tile_size must be > 0"):
        generator.render_tile(
            zoom=0,
            x=0,
            y=0,
            valid_time="2026-01-01T00:00:00Z",
            level="sfc",
            tile_size=0,
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

    with pytest.raises(TccTilingError, match="valid_time not found"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T01:00:00Z",
            level="sfc",
            min_zoom=0,
            max_zoom=0,
            formats=("png",),
        )
