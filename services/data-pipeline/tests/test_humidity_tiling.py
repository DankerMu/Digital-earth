from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from PIL import Image


def _write_test_config_dir(
    config_dir: Path, *, tile_size: int = 8, crs: str = "EPSG:4326"
) -> None:
    config_dir.mkdir(parents=True, exist_ok=True)

    (config_dir / "tiling.yaml").write_text(
        "\n".join(
            [
                "tiling:",
                f"  crs: {crs}",
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


def test_humidity_tile_generator_renders_tiles_for_surface_alias(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.humidity_tiles import HumidityTileGenerator

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=2)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    level = xr.DataArray(
        np.array([0.0], dtype=np.float32),
        dims=["level"],
        attrs={"long_name": "surface", "units": "1"},
    )

    values = np.full((1, 1, lat.size, lon.size), 0.5, dtype=np.float32)
    ds = xr.Dataset(
        {"r": xr.DataArray(values, dims=["time", "level", "lat", "lon"])},
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )

    generator = HumidityTileGenerator.from_dataset(ds, layer="ecmwf/humidity")
    result = generator.generate(
        tmp_path,
        valid_time="2026-01-01T00:00:00Z",
        level="surface",
        opacity=0.5,
        min_zoom=0,
        max_zoom=0,
        tile_size=2,
        formats=("webp",),
    )
    assert result.level == "sfc"
    assert result.formats == ("webp",)

    tile_path = (
        tmp_path
        / "ecmwf"
        / "humidity"
        / result.time
        / result.level
        / "0"
        / "0"
        / "0.webp"
    )
    img = Image.open(tile_path)
    try:
        assert img.size == (2, 2)
        _assert_solid_color(img.convert("RGBA"), rgba=(255, 255, 255, 64))
    finally:
        img.close()


def test_humidity_tile_generator_render_tile_smoke(
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

    values = np.full((1, 1, lat.size, lon.size), 50.0, dtype=np.float32)
    ds = xr.Dataset(
        {"r": xr.DataArray(values, dims=["time", "level", "lat", "lon"])},
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )

    generator = HumidityTileGenerator.from_dataset(ds, layer="ecmwf/humidity")
    img = generator.render_tile(
        zoom=0,
        x=0,
        y=0,
        valid_time="2026-01-01T00:00:00Z",
        level="850",
        tile_size=4,
    )
    assert img.size == (4, 4)
    _assert_solid_color(img, rgba=(255, 255, 255, 128))


def test_humidity_tile_generator_rejects_symlink_escape(
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
    values = np.full((1, 1, lat.size, lon.size), 50.0, dtype=np.float32)
    ds = xr.Dataset(
        {"r": xr.DataArray(values, dims=["time", "level", "lat", "lon"])},
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )
    generator = HumidityTileGenerator.from_dataset(ds, layer="ecmwf/humidity")

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
            level="850",
            opacity=1.0,
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )


def test_humidity_tile_generator_rejects_bad_inputs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube

    from tiling.config import get_tiling_config
    from tiling.humidity_tiles import (
        HumidityTileGenerator,
        HumidityTilingError,
        _parse_time,
        _save_tile_image,
    )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    level = np.array([850.0], dtype=np.float32)
    values = np.full((1, 1, lat.size, lon.size), 50.0, dtype=np.float32)
    ds = xr.Dataset(
        {"r": xr.DataArray(values, dims=["time", "level", "lat", "lon"])},
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )
    cube = DataCube.from_dataset(ds)

    with pytest.raises(ValueError, match="unsafe characters"):
        HumidityTileGenerator(cube, layer="../evil")
    with pytest.raises(ValueError, match="layer must not be empty"):
        HumidityTileGenerator(cube, layer="")
    with pytest.raises(ValueError, match="variable must not be empty"):
        HumidityTileGenerator(cube, variable="")

    generator = HumidityTileGenerator(cube, layer="ecmwf/humidity")
    assert generator.layer == "ecmwf/humidity"
    assert generator.variable == "r"

    with pytest.raises(ValueError, match="valid_time must not be empty"):
        generator.generate(
            tmp_path,
            valid_time="",
            level="850",
            opacity=1.0,
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )

    with pytest.raises(HumidityTilingError, match="valid_time not found"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T01:00:00Z",
            level="850",
            opacity=1.0,
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )

    with pytest.raises(HumidityTilingError, match="level not found"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="700",
            opacity=1.0,
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )

    with pytest.raises(ValueError, match="level must not be empty"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="",
            opacity=1.0,
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )

    with pytest.raises(ValueError, match="numeric pressure level"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="not-a-level",
            opacity=1.0,
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )

    with pytest.raises(ValueError, match="At least one tile format"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="850",
            opacity=1.0,
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=(),
        )
    with pytest.raises(ValueError, match="Unsupported tile format"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="850",
            opacity=1.0,
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("tiff",),
        )

    with pytest.raises(ValueError, match="opacity must be between 0 and 1"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="850",
            opacity=2.0,
            min_zoom=0,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )

    with pytest.raises(ValueError, match="tile_size must be > 0"):
        generator.render_tile(
            zoom=0,
            x=0,
            y=0,
            valid_time="2026-01-01T00:00:00Z",
            level="850",
            tile_size=0,
        )

    assert _parse_time(np.datetime64("2026-01-01T00:00:00")).tzinfo == timezone.utc
    assert _parse_time(datetime(2026, 1, 1, 0, 0, 0)).tzinfo == timezone.utc
    assert _parse_time("20260101T000000Z").tzinfo == timezone.utc
    with pytest.raises(ValueError, match="ISO8601"):
        _parse_time("not-a-time")

    img = Image.new("RGBA", (1, 1), (0, 0, 0, 0))
    with pytest.raises(ValueError, match="Unsupported tile file extension"):
        _save_tile_image(img, tmp_path / "tile.tiff")


def test_humidity_tile_generator_rejects_bad_config_and_zoom_range(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.config import get_tiling_config
    from tiling.humidity_tiles import HumidityTileGenerator

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    level = np.array([850.0], dtype=np.float32)
    values = np.full((1, 1, lat.size, lon.size), 50.0, dtype=np.float32)
    ds = xr.Dataset(
        {"r": xr.DataArray(values, dims=["time", "level", "lat", "lon"])},
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )

    config_dir = tmp_path / "config3857"
    _write_test_config_dir(config_dir, tile_size=4, crs="EPSG:3857")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    generator = HumidityTileGenerator.from_dataset(ds, layer="ecmwf/humidity")
    with pytest.raises(ValueError, match="Unsupported tiling CRS"):
        generator.render_tile(
            zoom=0,
            x=0,
            y=0,
            valid_time="2026-01-01T00:00:00Z",
            level="850",
            tile_size=4,
        )

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=4)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    generator = HumidityTileGenerator.from_dataset(ds, layer="ecmwf/humidity")
    with pytest.raises(ValueError, match="fall entirely within configured"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="850",
            opacity=1.0,
            min_zoom=0,
            max_zoom=2,
            tile_size=4,
            formats=("png",),
        )

    with pytest.raises(ValueError, match="Invalid zoom range"):
        generator.generate(
            tmp_path,
            valid_time="2026-01-01T00:00:00Z",
            level="850",
            opacity=1.0,
            min_zoom=1,
            max_zoom=0,
            tile_size=4,
            formats=("png",),
        )


def test_humidity_tile_generator_reports_dataset_shape_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube

    from tiling.config import get_tiling_config
    from tiling.humidity_tiles import HumidityTileGenerator, HumidityTilingError

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=2)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    level = np.array([850.0], dtype=np.float32)

    ds = xr.Dataset(
        {
            "other": xr.DataArray(
                np.zeros((1, 1, 3, 3), dtype=np.float32),
                dims=["time", "level", "lat", "lon"],
            )
        },
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )
    generator = HumidityTileGenerator(DataCube(dataset=ds), layer="ecmwf/humidity")
    with pytest.raises(HumidityTilingError, match="Variable"):
        generator.render_tile(
            zoom=0,
            x=0,
            y=0,
            valid_time="2026-01-01T00:00:00Z",
            level="850",
            tile_size=2,
        )

    ds = xr.Dataset(
        {
            "r": xr.DataArray(
                np.zeros((1, 3, 3), dtype=np.float32), dims=["time", "lat", "lon"]
            )
        },
        coords={
            "time": time,
            "level": level,
            "lat": lat,
            "lon": lon,
        },
    )
    generator = HumidityTileGenerator(DataCube(dataset=ds), layer="ecmwf/humidity")
    with pytest.raises(HumidityTilingError, match="required dim: level"):
        generator.render_tile(
            zoom=0,
            x=0,
            y=0,
            valid_time="2026-01-01T00:00:00Z",
            level="850",
            tile_size=2,
        )

    ds = xr.Dataset(
        {
            "r": xr.DataArray(
                np.zeros((1, 1, 3, 3), dtype=np.float32),
                dims=["time", "level", "lat", "lon"],
            )
        },
        coords={
            "time": time,
            "level": level,
            "lat": lat,
            "lon": lon,
            "member": np.array([0], dtype=np.int32),
        },
    )
    ds["r"] = (
        ds["r"]
        .expand_dims(member=ds["member"].values)
        .transpose("time", "level", "lat", "lon", "member")
    )
    generator = HumidityTileGenerator(DataCube(dataset=ds), layer="ecmwf/humidity")
    with pytest.raises(HumidityTilingError, match="Expected data dims"):
        generator._extract_grid(time_index=0, level_index=0)

    with pytest.raises(HumidityTilingError, match="time_index is out of range"):
        generator._extract_grid(time_index=99, level_index=0)
    with pytest.raises(HumidityTilingError, match="level_index is out of range"):
        generator._extract_grid(time_index=0, level_index=99)
