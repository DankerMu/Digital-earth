from __future__ import annotations

import json
from pathlib import Path
import re
import sys
from types import ModuleType, SimpleNamespace

import numpy as np
import pytest
import xarray as xr
from PIL import Image


def test_temperature_rgba_endpoints_and_nodata() -> None:
    from tiling.cldas_tiles import temperature_rgba

    values = np.array([[-20.0, 0.0, 40.0, np.nan]], dtype=np.float32)
    rgba = temperature_rgba(values)
    assert rgba.shape == (1, 4, 4)

    blue = tuple(rgba[0, 0])
    white = tuple(rgba[0, 1])
    red = tuple(rgba[0, 2])
    nodata = tuple(rgba[0, 3])

    assert blue == (0x3B, 0x82, 0xF6, 255)
    assert white == (255, 255, 255, 255)
    assert red == (0xEF, 0x44, 0x44, 255)
    assert nodata[3] == 0


def _make_global_tmp_dataset(
    *, value: float, lat_descending: bool = False
) -> xr.Dataset:
    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float64)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float64)
    if lat_descending:
        lat = lat[::-1]
    tmp = np.full((1, lat.size, lon.size), value, dtype=np.float32)
    ds = xr.Dataset(
        {"TMP": xr.DataArray(tmp, dims=["time", "lat", "lon"])},
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": lat,
            "lon": lon,
        },
    )
    ds.attrs["time"] = "2026-01-01T00:00:00Z"
    return ds


def test_cldas_tile_generator_writes_png_and_legend(tmp_path: Path) -> None:
    from tiling.cldas_tiles import CLDASTileGenerator

    ds = _make_global_tmp_dataset(value=0.0)
    generator = CLDASTileGenerator(ds, variable="TMP", layer="cldas/tmp")
    result = generator.generate(tmp_path, min_zoom=0, max_zoom=0, tile_size=8)

    assert result.layer == "cldas/tmp"
    assert result.variable == "TMP"
    assert result.time == "20260101T000000Z"
    assert result.tiles_written == 1

    legend_path = tmp_path / "cldas" / "tmp" / "legend.json"
    assert legend_path.is_file()
    legend = json.loads(legend_path.read_text(encoding="utf-8"))
    assert legend["unit"] == "°C"
    assert legend["min"] == -20
    assert legend["max"] == 40
    assert len(legend["colorStops"]) == 3
    assert legend["colorStops"][0]["color"] == "#3B82F6"
    assert re.fullmatch(r"[a-f0-9]{64}", legend["version"]) is not None

    tile_path = tmp_path / "cldas" / "tmp" / "20260101T000000Z" / "0" / "0" / "0.png"
    assert tile_path.is_file()

    img = Image.open(tile_path)
    try:
        assert img.mode == "RGBA"
        pixels = np.asarray(img)
        assert pixels.shape == (8, 8, 4)
        assert (pixels[..., :3] == 255).all()
        assert (pixels[..., 3] == 255).all()
    finally:
        img.close()


def test_cldas_tile_generator_handles_descending_lat(tmp_path: Path) -> None:
    from tiling.cldas_tiles import CLDASTileGenerator

    ds = _make_global_tmp_dataset(value=-20.0, lat_descending=True)
    generator = CLDASTileGenerator(ds, variable="TMP", layer="cldas/tmp")
    result = generator.generate(tmp_path, min_zoom=0, max_zoom=0, tile_size=4)
    assert result.tiles_written == 1

    tile_path = tmp_path / "cldas" / "tmp" / "20260101T000000Z" / "0" / "0" / "0.png"
    img = Image.open(tile_path)
    try:
        pixels = np.asarray(img)
        assert (pixels[..., 0] == 0x3B).all()
        assert (pixels[..., 1] == 0x82).all()
        assert (pixels[..., 2] == 0xF6).all()
        assert (pixels[..., 3] == 255).all()
    finally:
        img.close()


def test_cldas_tile_generator_render_tile_and_input_validation() -> None:
    from tiling.cldas_tiles import CLDASTileGenerator, CldasTilingError

    ds = _make_global_tmp_dataset(value=40.0)
    generator = CLDASTileGenerator(ds, variable="TMP", layer="cldas/tmp")

    image = generator.render_tile(zoom=0, x=0, y=0, tile_size=4)
    assert image.mode == "RGBA"
    assert image.size == (4, 4)

    with np.testing.assert_raises(CldasTilingError):
        CLDASTileGenerator(ds, variable="RHU", layer="cldas/tmp").render_tile(
            zoom=0, x=0, y=0, tile_size=4
        )

    with np.testing.assert_raises(ValueError):
        generator.render_tile(zoom=0, x=0, y=0, tile_size=0)


def test_cldas_tile_generator_time_key_fallback(tmp_path: Path) -> None:
    from tiling.cldas_tiles import CLDASTileGenerator

    ds = _make_global_tmp_dataset(value=0.0)
    ds.attrs["time"] = "not-a-time"
    generator = CLDASTileGenerator(ds, variable="TMP", layer="cldas/tmp")
    result = generator.generate(tmp_path, min_zoom=0, max_zoom=0, tile_size=1)
    assert result.time == "notatime"


def test_cldas_tile_generator_rejects_layer_path_traversal() -> None:
    from tiling.cldas_tiles import CLDASTileGenerator

    ds = _make_global_tmp_dataset(value=0.0)
    with pytest.raises(ValueError, match="layer"):
        CLDASTileGenerator(ds, variable="TMP", layer="../evil")


def test_cldas_tile_generator_rejects_time_key_path_traversal(tmp_path: Path) -> None:
    from tiling.cldas_tiles import CLDASTileGenerator

    ds = _make_global_tmp_dataset(value=0.0)
    generator = CLDASTileGenerator(ds, variable="TMP", layer="cldas/tmp")
    with pytest.raises(ValueError, match="time_key"):
        generator.generate(
            tmp_path, min_zoom=0, max_zoom=0, tile_size=1, time_key="../evil"
        )


def test_cldas_tile_generator_rejects_symlink_escape(tmp_path: Path) -> None:
    from tiling.cldas_tiles import CLDASTileGenerator

    ds = _make_global_tmp_dataset(value=0.0)
    generator = CLDASTileGenerator(ds, variable="TMP", layer="cldas/tmp")

    outside = tmp_path.parent / f"{tmp_path.name}-outside"
    outside.mkdir()

    try:
        (tmp_path / "cldas").symlink_to(outside, target_is_directory=True)
    except OSError:
        pytest.skip("Symlinks are not supported in this environment")

    with pytest.raises(ValueError, match="escapes output_dir"):
        generator.generate(tmp_path, min_zoom=0, max_zoom=0, tile_size=1)


def test_internal_axis_and_lon_normalization_helpers() -> None:
    from tiling.cldas_tiles import _ensure_ascending_axis, _normalize_longitudes

    coord = np.array([0.0, -1.0, 1.0], dtype=np.float64)
    values = np.array([[0.0, 1.0, 2.0]], dtype=np.float32)
    sorted_coord, sorted_values = _ensure_ascending_axis(coord, values, axis=1)
    assert sorted_coord.tolist() == [-1.0, 0.0, 1.0]
    assert sorted_values.tolist() == [[1.0, 0.0, 2.0]]

    lon = np.array([0.0, 90.0, 270.0], dtype=np.float64)
    grid = np.array([[10.0, 20.0, 30.0]], dtype=np.float32)
    normalized_lon, normalized_grid = _normalize_longitudes(lon, grid)
    assert normalized_lon.tolist() == [-90.0, 0.0, 90.0]
    assert normalized_grid.tolist() == [[30.0, 10.0, 20.0]]


def test_cldas_tile_generator_from_netcdf(tmp_path: Path) -> None:
    from tiling.cldas_tiles import CLDASTileGenerator

    path = tmp_path / "CHINA_WEST_0P05_HOR-TMP-2026010100.nc"
    ds = xr.Dataset(
        {"TMP": xr.DataArray(np.zeros((2, 3), dtype=np.float32), dims=["lat", "lon"])},
        coords={
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")

    generator = CLDASTileGenerator.from_netcdf(path, engine="h5netcdf")
    try:
        assert generator.layer == "cldas/tmp"
        assert generator.variable == "TMP"
    finally:
        generator._ds.close()


def test_upload_layer_to_s3_builds_expected_config(tmp_path: Path, monkeypatch) -> None:
    from pydantic import SecretStr

    from tiling.cldas_tiles import CLDASTileGenerator

    ds = _make_global_tmp_dataset(value=0.0)
    generator = CLDASTileGenerator(ds, variable="TMP", layer="cldas/tmp")
    layer_dir = tmp_path / "cldas" / "tmp"
    layer_dir.mkdir(parents=True, exist_ok=True)

    captured: dict[str, object] = {}

    def fake_upload_directory_to_s3(local_dir: Path, *, config: object) -> int:
        captured["local_dir"] = local_dir
        captured["config"] = config
        return 123

    import tiling.cldas_tiles as cldas_tiles_module

    monkeypatch.setattr(
        cldas_tiles_module, "upload_directory_to_s3", fake_upload_directory_to_s3
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
    assert uploaded == 123
    assert captured["local_dir"] == layer_dir
    cfg = captured["config"]
    assert getattr(cfg, "bucket") == "tiles-bucket"
    assert getattr(cfg, "prefix") == "prefix"
    assert getattr(cfg, "access_key_id") == "a"
    assert getattr(cfg, "secret_access_key") == "b"


def test_tile_storage_helpers(tmp_path: Path) -> None:
    import pytest

    from tiling.storage import (
        S3UploadConfig,
        TileStorageError,
        build_s3_key,
        guess_content_type,
        upload_directory_to_s3,
    )

    assert (
        build_s3_key("cldas/tmp", Path("20260101T000000Z/0/0/0.png"))
        == "cldas/tmp/20260101T000000Z/0/0/0.png"
    )
    assert build_s3_key("", Path("legend.json")) == "legend.json"
    assert guess_content_type(Path("a.png")) == "image/png"
    assert guess_content_type(Path("a.webp")) == "image/webp"
    assert guess_content_type(Path("a.json")) == "application/json"

    with pytest.raises(TileStorageError, match="Tile directory not found"):
        upload_directory_to_s3(
            Path("does-not-exist"), config=S3UploadConfig(bucket="b", prefix="p")
        )

    with pytest.raises(TileStorageError, match="boto3 is required"):
        upload_directory_to_s3(tmp_path, config=S3UploadConfig(bucket="b", prefix="p"))


def test_upload_directory_to_s3_calls_boto3(tmp_path: Path, monkeypatch) -> None:
    from tiling.storage import S3UploadConfig, upload_directory_to_s3

    (tmp_path / "legend.json").write_text("{}", encoding="utf-8")
    (tmp_path / "0.png").write_bytes(b"\x89PNG\r\n\x1a\n")

    uploads: list[dict[str, object]] = []

    class FakeClient:
        def upload_file(
            self, filename: str, bucket: str, key: str, *, ExtraArgs: dict
        ) -> None:
            uploads.append(
                {
                    "filename": Path(filename).name,
                    "bucket": bucket,
                    "key": key,
                    "extra": dict(ExtraArgs),
                }
            )

    fake_boto3 = ModuleType("boto3")
    fake_boto3.client = lambda *args, **kwargs: FakeClient()  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)

    count = upload_directory_to_s3(
        tmp_path,
        config=S3UploadConfig(
            bucket="bucket", prefix="prefix", cache_control="no-cache"
        ),
    )
    assert count == 2
    assert {item["key"] for item in uploads} == {"prefix/0.png", "prefix/legend.json"}
    assert all(item["bucket"] == "bucket" for item in uploads)
