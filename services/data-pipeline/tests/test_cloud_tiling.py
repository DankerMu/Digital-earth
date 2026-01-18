from __future__ import annotations

from pathlib import Path
from types import SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from PIL import Image


def test_tcc_rgba_normalizes_percent_and_respects_opacity() -> None:
    from tiling.cloud_tiles import tcc_rgba

    values = np.array([[0.0, 50.0, 100.0, np.nan]], dtype=np.float32)
    rgba = tcc_rgba(values, opacity=0.5)

    assert rgba.shape == (1, 4, 4)
    assert tuple(rgba[0, 0]) == (0, 0, 0, 0)
    assert tuple(rgba[0, 1]) == (128, 128, 128, 64)
    assert tuple(rgba[0, 2]) == (255, 255, 255, 128)
    assert rgba[0, 3, 3] == 0


def test_normalize_tcc_fraction_handles_fraction_and_clamps() -> None:
    from tiling.cloud_tiles import normalize_tcc_fraction

    fraction = np.array([[0.0, 0.5, 1.0]], dtype=np.float32)
    out = normalize_tcc_fraction(fraction)
    np.testing.assert_allclose(out, fraction, rtol=0, atol=1e-6)

    percent_out_of_range = np.array([[-10.0, 150.0]], dtype=np.float32)
    out2 = normalize_tcc_fraction(percent_out_of_range)
    np.testing.assert_allclose(out2, np.array([[0.0, 1.0]], dtype=np.float32))


def _make_global_tcc_dataset(
    *,
    value: float,
    time_iso: str = "2026-01-01T00:00:00Z",
    lat_descending: bool = False,
    lon_0360: bool = False,
    include_time_attr: bool = True,
) -> xr.Dataset:
    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float64)
    if lat_descending:
        lat = lat[::-1]

    if lon_0360:
        lon = np.array([0.0, 90.0, 270.0], dtype=np.float64)
    else:
        lon = np.array([-180.0, 0.0, 180.0], dtype=np.float64)

    tcc = np.full((1, lat.size, lon.size), value, dtype=np.float32)
    ds = xr.Dataset(
        {"tcc": xr.DataArray(tcc, dims=["time", "lat", "lon"])},
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": lat,
            "lon": lon,
        },
    )
    if include_time_attr:
        ds.attrs["time"] = time_iso
    return ds


def test_cloud_tile_generator_writes_png_and_legend(tmp_path: Path) -> None:
    from tiling.cloud_tiles import CloudTileGenerator

    ds = _make_global_tcc_dataset(value=100.0, include_time_attr=True)
    generator = CloudTileGenerator(ds, variable="tcc", layer="ecmwf/tcc", opacity=0.5)
    result = generator.generate(tmp_path, min_zoom=0, max_zoom=0, tile_size=8)

    assert result.layer == "ecmwf/tcc"
    assert result.variable == "tcc"
    assert result.time == "20260101T000000Z"
    assert result.tiles_written == 1

    legend_path = tmp_path / "ecmwf" / "tcc" / "legend.json"
    assert legend_path.is_file()

    tile_path = tmp_path / "ecmwf" / "tcc" / "20260101T000000Z" / "0" / "0" / "0.png"
    assert tile_path.is_file()

    img = Image.open(tile_path)
    try:
        assert img.mode == "RGBA"
        pixels = np.asarray(img)
        assert pixels.shape == (8, 8, 4)
        assert (pixels[..., :3] == 255).all()
        assert (pixels[..., 3] == 128).all()
    finally:
        img.close()


def test_cloud_tile_generator_time_key_from_coordinate(tmp_path: Path) -> None:
    from tiling.cloud_tiles import CloudTileGenerator

    ds = _make_global_tcc_dataset(value=0.0, include_time_attr=False)
    ds = ds.assign_coords(time=np.array(["2026-01-01T01:02:03"], dtype="datetime64[s]"))

    generator = CloudTileGenerator(ds, variable="tcc", layer="ecmwf/tcc")
    result = generator.generate(tmp_path, min_zoom=0, max_zoom=0, tile_size=1)
    assert result.time == "20260101T010203Z"


def test_cloud_tile_generator_extract_grid_normalizes_lat_and_lon() -> None:
    from tiling.cloud_tiles import CloudTileGenerator

    ds = _make_global_tcc_dataset(
        value=100.0, lat_descending=True, lon_0360=True, include_time_attr=True
    )
    generator = CloudTileGenerator(ds, variable="tcc", layer="ecmwf/tcc")
    lat, lon, grid = generator._extract_grid()

    assert lat.tolist() == [-90.0, 0.0, 90.0]
    assert lon.tolist() == [-90.0, 0.0, 90.0]
    assert grid.shape == (3, 3)


def test_cloud_tile_generator_render_tile_and_input_validation() -> None:
    from tiling.cloud_tiles import CloudTileGenerator, CloudTilingError

    ds = _make_global_tcc_dataset(value=100.0)
    generator = CloudTileGenerator(ds, variable="tcc", layer="ecmwf/tcc")

    image = generator.render_tile(zoom=0, x=0, y=0, tile_size=4)
    assert image.mode == "RGBA"
    assert image.size == (4, 4)

    with pytest.raises(CloudTilingError, match="Variable"):
        CloudTileGenerator(ds, variable="missing", layer="ecmwf/tcc").render_tile(
            zoom=0, x=0, y=0, tile_size=4
        )

    with pytest.raises(ValueError, match="tile_size"):
        generator.render_tile(zoom=0, x=0, y=0, tile_size=0)

    with pytest.raises(ValueError, match="opacity"):
        CloudTileGenerator(ds, variable="tcc", layer="ecmwf/tcc", opacity=2.0)


def test_cloud_tile_generator_rejects_layer_path_traversal() -> None:
    from tiling.cloud_tiles import CloudTileGenerator

    ds = _make_global_tcc_dataset(value=0.0)
    with pytest.raises(ValueError, match="layer"):
        CloudTileGenerator(ds, variable="tcc", layer="../evil")


def test_cloud_tile_generator_rejects_time_key_path_traversal(tmp_path: Path) -> None:
    from tiling.cloud_tiles import CloudTileGenerator

    ds = _make_global_tcc_dataset(value=0.0)
    generator = CloudTileGenerator(ds, variable="tcc", layer="ecmwf/tcc")
    with pytest.raises(ValueError, match="time_key"):
        generator.generate(
            tmp_path, min_zoom=0, max_zoom=0, tile_size=1, time_key="../evil"
        )


def test_cloud_upload_layer_to_s3_builds_expected_config(
    tmp_path: Path, monkeypatch
) -> None:
    from pydantic import SecretStr

    from tiling.cloud_tiles import CloudTileGenerator

    ds = _make_global_tcc_dataset(value=0.0)
    generator = CloudTileGenerator(ds, variable="tcc", layer="ecmwf/tcc")
    layer_dir = tmp_path / "ecmwf" / "tcc"
    layer_dir.mkdir(parents=True, exist_ok=True)

    captured: dict[str, object] = {}

    def fake_upload_directory_to_s3(local_dir: Path, *, config: object) -> int:
        captured["local_dir"] = local_dir
        captured["config"] = config
        return 7

    import tiling.cloud_tiles as cloud_tiles_module

    monkeypatch.setattr(
        cloud_tiles_module, "upload_directory_to_s3", fake_upload_directory_to_s3
    )

    settings = SimpleNamespace(
        storage=SimpleNamespace(
            tiles_bucket="tiles-bucket",
            access_key_id=SecretStr("a"),
            secret_access_key=SecretStr("b"),
        )
    )

    uploaded = generator.upload_layer_to_s3(
        tmp_path, settings=settings, cache_control=None, prefix="prefix"
    )
    assert uploaded == 7
    assert captured["local_dir"] == layer_dir
    cfg = captured["config"]
    assert getattr(cfg, "bucket") == "tiles-bucket"
    assert getattr(cfg, "prefix") == "prefix"
    assert getattr(cfg, "access_key_id") == "a"
    assert getattr(cfg, "secret_access_key") == "b"


def test_cloud_tiles_internal_helpers_and_edge_cases(tmp_path: Path) -> None:
    from tiling.cloud_tiles import (
        CloudTilingError,
        _ensure_ascending_axis,
        _ensure_relative_to_base,
        _normalize_time_key,
        _validate_layer,
        _validate_time_key,
        normalize_tcc_fraction,
        tcc_rgba,
    )

    with pytest.raises(ValueError, match="layer must not be empty"):
        _validate_layer("")

    with pytest.raises(ValueError, match="time_key must not be empty"):
        _validate_time_key("")

    with pytest.raises(ValueError, match="escapes output_dir"):
        _ensure_relative_to_base(
            base_dir=tmp_path, path=tmp_path.parent.resolve(), label="layer"
        )

    assert _normalize_time_key("not-a-time") == "notatime"

    with pytest.raises(CloudTilingError, match="Only 1D coordinates"):
        _ensure_ascending_axis(
            np.zeros((1, 1), dtype=np.float64),
            np.zeros((1, 1), dtype=np.float32),
            axis=0,
        )

    with pytest.raises(CloudTilingError, match="must not be empty"):
        _ensure_ascending_axis(
            np.zeros((0,), dtype=np.float64),
            np.zeros((0,), dtype=np.float32),
            axis=0,
        )

    coord = np.array([0.0, -1.0, 1.0], dtype=np.float64)
    values = np.array([[0.0, 1.0, 2.0]], dtype=np.float32)
    sorted_coord, sorted_values = _ensure_ascending_axis(coord, values, axis=1)
    assert sorted_coord.tolist() == [-1.0, 0.0, 1.0]
    assert sorted_values.tolist() == [[1.0, 0.0, 2.0]]

    all_nan = normalize_tcc_fraction(np.array([[np.nan]], dtype=np.float32))
    assert np.isnan(all_nan).all()

    with pytest.raises(ValueError, match="opacity"):
        tcc_rgba(np.array([[0.0]], dtype=np.float32), opacity=-0.1)


def test_cloud_tile_generator_supports_valid_time_dim_and_case_insensitive_var(
    tmp_path: Path,
) -> None:
    from tiling.cloud_tiles import CloudTileGenerator

    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float64)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float64)
    tcc = np.full((1, lat.size, lon.size), 1.0, dtype=np.float32)
    ds = xr.Dataset(
        {"TCC": xr.DataArray(tcc, dims=["valid_time", "latitude", "longitude"])},
        coords={
            "valid_time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "latitude": lat,
            "longitude": lon,
        },
    )

    generator = CloudTileGenerator(ds, variable="tcc", layer="ecmwf/tcc")
    assert generator.variable == "tcc"
    assert generator.layer == "ecmwf/tcc"
    assert generator.opacity == pytest.approx(1.0)

    result = generator.generate(tmp_path, min_zoom=0, max_zoom=0, tile_size=1)
    assert result.time == "20260101T000000Z"


def test_cloud_tile_generator_uses_default_zoom_and_tile_size_from_config(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.cloud_tiles import CloudTileGenerator
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
                "  tile_size: 4",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DIGITAL_EARTH_TILING_CONFIG", str(config_path))
    get_tiling_config.cache_clear()

    ds = _make_global_tcc_dataset(value=0.0, include_time_attr=True)
    generator = CloudTileGenerator(ds, variable="tcc", layer="ecmwf/tcc")
    result = generator.generate(tmp_path)

    assert result.min_zoom == 0
    assert result.max_zoom == 0
    assert result.tiles_written == 1

    tile_path = tmp_path / "ecmwf" / "tcc" / result.time / "0" / "0" / "0.png"
    img = Image.open(tile_path)
    try:
        assert img.size == (4, 4)
    finally:
        img.close()


def test_cloud_tile_generator_rejects_unsupported_crs(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from tiling.cloud_tiles import CloudTileGenerator
    from tiling.config import get_tiling_config

    config_path = tmp_path / "tiling.yaml"
    config_path.write_text(
        "\n".join(
            [
                "tiling:",
                "  crs: EPSG:3857",
                "  global:",
                "    min_zoom: 0",
                "    max_zoom: 0",
                "  event:",
                "    min_zoom: 2",
                "    max_zoom: 2",
                "  tile_size: 1",
                "",
            ]
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DIGITAL_EARTH_TILING_CONFIG", str(config_path))
    get_tiling_config.cache_clear()

    ds = _make_global_tcc_dataset(value=0.0, include_time_attr=True)
    generator = CloudTileGenerator(ds, variable="tcc", layer="ecmwf/tcc")
    with pytest.raises(ValueError, match="Unsupported tiling CRS"):
        generator.render_tile(zoom=0, x=0, y=0, tile_size=1)


def test_cloud_tile_generator_time_dimension_validation() -> None:
    from tiling.cloud_tiles import CloudTileGenerator, CloudTilingError

    ds_empty = xr.Dataset(
        {
            "tcc": xr.DataArray(
                np.zeros((0, 1, 1), dtype=np.float32), dims=["time", "lat", "lon"]
            )
        },
        coords={
            "time": np.array([], dtype="datetime64[s]"),
            "lat": np.array([0.0], dtype=np.float64),
            "lon": np.array([0.0], dtype=np.float64),
        },
    )
    with pytest.raises(CloudTilingError, match="dimension is empty"):
        CloudTileGenerator(ds_empty, variable="tcc", layer="ecmwf/tcc")._extract_grid()

    ds_one = _make_global_tcc_dataset(value=0.0)
    with pytest.raises(CloudTilingError, match="time_index is out of range"):
        CloudTileGenerator(
            ds_one, variable="tcc", layer="ecmwf/tcc", time_index=5
        )._extract_grid()
