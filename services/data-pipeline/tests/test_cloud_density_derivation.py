from __future__ import annotations

import sys
import json
import runpy
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import xarray as xr

from datacube.storage import open_datacube, write_datacube
from derived.cloud_density import (
    CloudDensityDerivationError,
    CloudDensityThresholds,
    derive_cloud_density_from_rh,
    derive_cloud_density_dataset,
    normalize_relative_humidity,
    resolve_rh_variable_name,
    smoothstep,
)
from volume.cli import main as volume_main
from volume.cloud_density import CloudDensityExportError, export_cloud_density_slices
from volume import cloud_density as volume_cloud_density


def test_smoothstep_matches_reference() -> None:
    x = xr.DataArray(
        np.array([-1.0, 0.0, 0.5, 1.0, 2.0], dtype=np.float32), dims=("x",)
    )
    out = smoothstep(0.0, 1.0, x)
    expected = np.array([0.0, 0.0, 0.5, 1.0, 1.0], dtype=np.float32)
    assert np.allclose(out.values, expected, atol=1e-6)


def test_smoothstep_rejects_equal_edges() -> None:
    x = xr.DataArray(np.array([0.0], dtype=np.float32), dims=("x",))
    with pytest.raises(CloudDensityDerivationError, match="edge1 != edge0"):
        smoothstep(0.5, 0.5, x)


def test_normalize_relative_humidity_converts_percent_units() -> None:
    rh = xr.DataArray(
        np.array([0.0, 50.0, 100.0], dtype=np.float32),
        dims=("x",),
        attrs={"units": "%"},
        name="r",
    )
    out = normalize_relative_humidity(rh)
    assert out.dtype == np.float32
    assert out.attrs["units"] == "1"
    assert out.attrs["standard_name"] == "relative_humidity"
    assert np.allclose(out.values, np.array([0.0, 0.5, 1.0], dtype=np.float32))


def test_normalize_relative_humidity_heuristic_detects_percent_when_units_missing() -> (
    None
):
    rh = xr.DataArray(
        np.array([0.0, 80.0, 100.0], dtype=np.float32),
        dims=("x",),
        name="r",
    )
    out = normalize_relative_humidity(rh)
    assert np.allclose(out.values, np.array([0.0, 0.8, 1.0], dtype=np.float32))


def test_normalize_relative_humidity_heuristic_keeps_fraction_when_units_missing() -> (
    None
):
    rh = xr.DataArray(
        np.array([0.0, 0.25, 0.5, 1.0], dtype=np.float32),
        dims=("x",),
        name="r",
    )
    out = normalize_relative_humidity(rh)
    assert np.allclose(out.values, rh.values)


def test_normalize_relative_humidity_all_missing_values_keeps_scale() -> None:
    rh = xr.DataArray(
        np.array([np.nan, np.nan], dtype=np.float32),
        dims=("x",),
        name="r",
    )
    out = normalize_relative_humidity(rh)
    assert np.all(np.isnan(out.values))


def test_cloud_density_thresholds_accept_fraction_or_percent() -> None:
    thresholds = CloudDensityThresholds.resolve(rh0=0.8, rh1=0.95)
    assert thresholds.rh0 == pytest.approx(0.8)
    assert thresholds.rh1 == pytest.approx(0.95)

    thresholds = CloudDensityThresholds.resolve(rh0=80.0, rh1=95.0)
    assert thresholds.rh0 == pytest.approx(0.8)
    assert thresholds.rh1 == pytest.approx(0.95)

    with pytest.raises(CloudDensityDerivationError, match="consistent units"):
        CloudDensityThresholds.resolve(rh0=0.8, rh1=95.0)

    with pytest.raises(CloudDensityDerivationError, match="Invalid RH thresholds"):
        CloudDensityThresholds.resolve(rh0=0.95, rh1=0.8)


def test_cloud_density_thresholds_load_from_shared_settings(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    base = {
        "api": {"host": "0.0.0.0", "port": 8000, "debug": True, "cors_origins": []},
        "pipeline": {
            "workers": 2,
            "batch_size": 100,
            "cloud_density_rh0": 0.7,
            "cloud_density_rh1": 0.9,
        },
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }
    (config_dir / "dev.json").write_text(json.dumps(base), encoding="utf-8")

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings

    get_settings.cache_clear()
    thresholds = CloudDensityThresholds.resolve()
    assert thresholds.rh0 == pytest.approx(0.7)
    assert thresholds.rh1 == pytest.approx(0.9)


def test_resolve_rh_variable_name_prefers_known_candidates() -> None:
    ds = xr.Dataset(
        {
            "t": xr.DataArray(np.zeros((1,), dtype=np.float32), dims=("x",)),
            "r": xr.DataArray(np.ones((1,), dtype=np.float32), dims=("x",)),
        }
    )
    assert resolve_rh_variable_name(ds) == "r"


def test_resolve_rh_variable_name_uses_standard_name_fallback() -> None:
    ds = xr.Dataset(
        {
            "foo": xr.DataArray(
                np.ones((1,), dtype=np.float32),
                dims=("x",),
                attrs={"standard_name": "relative_humidity"},
            ),
        }
    )
    assert resolve_rh_variable_name(ds) == "foo"


def test_resolve_rh_variable_name_honors_preferred_and_errors() -> None:
    ds = xr.Dataset(
        {
            "r": xr.DataArray(np.ones((1,), dtype=np.float32), dims=("x",)),
        }
    )
    assert resolve_rh_variable_name(ds, preferred="r") == "r"

    with pytest.raises(CloudDensityDerivationError, match="must not be empty"):
        resolve_rh_variable_name(ds, preferred="   ")

    with pytest.raises(CloudDensityDerivationError, match="not found"):
        resolve_rh_variable_name(ds, preferred="missing")


def test_resolve_rh_variable_name_long_name_fallback_and_missing_raises() -> None:
    ds = xr.Dataset(
        {
            "foo": xr.DataArray(
                np.ones((1,), dtype=np.float32),
                dims=("x",),
                attrs={"long_name": "Relative Humidity"},
            ),
        }
    )
    assert resolve_rh_variable_name(ds) == "foo"

    ds_missing = xr.Dataset(
        {
            "bar": xr.DataArray(np.ones((1,), dtype=np.float32), dims=("x",)),
        }
    )
    with pytest.raises(
        CloudDensityDerivationError, match="Unable to infer RH variable"
    ):
        resolve_rh_variable_name(ds_missing)


def test_derive_cloud_density_from_rh_clamps_to_unit_interval() -> None:
    rh = xr.DataArray(
        np.array([0.7, 0.8, 0.875, 0.95, 1.1], dtype=np.float32),
        dims=("x",),
        name="rh",
        attrs={"units": "1"},
    )
    thresholds = CloudDensityThresholds.resolve(rh0=0.8, rh1=0.95)
    density = derive_cloud_density_from_rh(rh, thresholds=thresholds)

    assert density.name == "cloud_density"
    assert density.dtype == np.float32
    assert density.attrs["units"] == "1"
    assert np.all(np.isfinite(density.values))
    assert np.all(density.values >= 0.0)
    assert np.all(density.values <= 1.0)
    assert density.values[0] == pytest.approx(0.0)
    assert density.values[1] == pytest.approx(0.0)
    assert density.values[2] == pytest.approx(0.5, abs=1e-6)
    assert density.values[3] == pytest.approx(1.0)
    assert density.values[4] == pytest.approx(1.0)


def test_derive_cloud_density_dataset_wraps_dataset() -> None:
    ds = xr.Dataset(
        {
            "r": xr.DataArray(
                np.array([0.0, 100.0], dtype=np.float32),
                dims=("x",),
                attrs={"units": "%"},
            )
        }
    )
    thresholds = CloudDensityThresholds.resolve(rh0=80.0, rh1=100.0)
    out = derive_cloud_density_dataset(ds, rh_variable="r", thresholds=thresholds)
    assert list(out.data_vars) == ["cloud_density"]
    assert float(out["cloud_density"].min()) >= 0.0
    assert float(out["cloud_density"].max()) <= 1.0


def _rh_datacube_dataset(*, units: str = "%") -> xr.Dataset:
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    level = np.array([850.0, 700.0], dtype=np.float32)
    lat = np.array([10.0, 20.0], dtype=np.float32)
    lon = np.array([30.0, 40.0], dtype=np.float32)
    # shape: time, level, lat, lon
    data = np.array(
        [
            [
                [[0.0, 50.0], [80.0, 100.0]],
                [[10.0, 60.0], [90.0, 100.0]],
            ]
        ],
        dtype=np.float32,
    )
    return xr.Dataset(
        {
            "r": xr.DataArray(
                data, dims=("time", "level", "lat", "lon"), attrs={"units": units}
            )
        },
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )


def test_export_cloud_density_slices_writes_per_level_files(tmp_path: Path) -> None:
    ds = _rh_datacube_dataset(units="%")
    result = export_cloud_density_slices(
        ds,
        tmp_path,
        layer="ecmwf/cloud_density",
        rh0=80.0,
        rh1=100.0,
        output_format="netcdf",
        write_manifest=True,
    )

    out_dir = tmp_path / "ecmwf" / "cloud_density" / result.time
    assert out_dir.is_dir()
    assert result.manifest is not None
    assert result.manifest.exists()
    assert len(result.levels) == 2
    assert len(result.files) == 2

    with open_datacube(result.files[0]) as slice_ds:
        assert "cloud_density" in slice_ds.data_vars
        da = slice_ds["cloud_density"]
        assert da.dtype == np.float32
        assert set(da.dims) == {"time", "level", "lat", "lon"}
        assert slice_ds.sizes["time"] == 1
        assert slice_ds.sizes["level"] == 1
        assert float(np.nanmin(da.values)) >= 0.0
        assert float(np.nanmax(da.values)) <= 1.0

    manifest = json.loads((out_dir / "manifest.json").read_text(encoding="utf-8"))
    assert manifest["schema"] == "digital-earth.volume-slices"
    assert manifest["layer"] == "ecmwf/cloud_density"
    assert manifest["levels"] == list(result.levels)


def test_volume_export_input_validation_errors(tmp_path: Path) -> None:
    ds = _rh_datacube_dataset(units="%")
    with pytest.raises(ValueError, match="layer must not be empty"):
        export_cloud_density_slices(
            ds,
            tmp_path,
            layer="",
            rh0=80.0,
            rh1=100.0,
        )

    with pytest.raises(ValueError, match="unsafe"):
        export_cloud_density_slices(
            ds,
            tmp_path,
            layer="ecmwf/../cloud_density",
            rh0=80.0,
            rh1=100.0,
        )

    with pytest.raises(ValueError, match="output_format"):
        export_cloud_density_slices(
            ds,
            tmp_path,
            layer="ecmwf/cloud_density",
            rh0=80.0,
            rh1=100.0,
            output_format="nope",
        )

    with pytest.raises(CloudDensityExportError, match="RH variable.*not found"):
        export_cloud_density_slices(
            ds,
            tmp_path,
            layer="ecmwf/cloud_density",
            rh_variable="missing",
            rh0=80.0,
            rh1=100.0,
        )

    ds_missing_level = ds.rename({"level": "plev"})
    with pytest.raises(CloudDensityExportError, match="coordinate: level"):
        export_cloud_density_slices(
            ds_missing_level,
            tmp_path,
            layer="ecmwf/cloud_density",
            rh0=80.0,
            rh1=100.0,
        )

    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    level = np.array([], dtype=np.float32)
    lat = np.array([0.0], dtype=np.float32)
    lon = np.array([0.0], dtype=np.float32)
    ds_empty_level = xr.Dataset(
        {
            "r": xr.DataArray(
                np.empty((1, 0, 1, 1), dtype=np.float32),
                dims=("time", "level", "lat", "lon"),
                attrs={"units": "%"},
            )
        },
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )
    with pytest.raises(CloudDensityExportError, match="level coordinate is empty"):
        export_cloud_density_slices(
            ds_empty_level,
            tmp_path,
            layer="ecmwf/cloud_density",
            rh0=80.0,
            rh1=100.0,
        )

    ds_missing_dims = xr.Dataset(
        {
            "r": xr.DataArray(
                np.ones((1, 1), dtype=np.float32),
                dims=("time", "level"),
                attrs={"units": "%"},
            )
        },
        coords={"time": time, "level": np.array([850.0], dtype=np.float32)},
    )
    with pytest.raises(CloudDensityExportError, match="missing required dims"):
        export_cloud_density_slices(
            ds_missing_dims,
            tmp_path,
            layer="ecmwf/cloud_density",
            rh0=80.0,
            rh1=100.0,
        )


def test_volume_export_rejects_level_key_collisions(tmp_path: Path) -> None:
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")
    level = np.array([850.0, 850.0000005], dtype=np.float64)
    lat = np.array([0.0], dtype=np.float32)
    lon = np.array([0.0], dtype=np.float32)
    ds = xr.Dataset(
        {
            "r": xr.DataArray(
                np.full((1, 2, 1, 1), 100.0, dtype=np.float32),
                dims=("time", "level", "lat", "lon"),
                attrs={"units": "%"},
            )
        },
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )

    with pytest.raises(CloudDensityExportError, match="Level key collision"):
        export_cloud_density_slices(
            ds,
            tmp_path,
            layer="ecmwf/cloud_density",
            rh0=80.0,
            rh1=100.0,
        )


def test_volume_helpers_cover_error_paths(tmp_path: Path) -> None:
    with pytest.raises(ValueError, match="time_key must not be empty"):
        volume_cloud_density._validate_time_key("")  # noqa: SLF001
    with pytest.raises(ValueError, match="unsafe"):
        volume_cloud_density._validate_time_key("bad/time")  # noqa: SLF001

    with pytest.raises(ValueError, match="level_key must not be empty"):
        volume_cloud_density._validate_level_key("")  # noqa: SLF001
    with pytest.raises(ValueError, match="unsafe"):
        volume_cloud_density._validate_level_key("850/700")  # noqa: SLF001

    with pytest.raises(ValueError, match="escapes output_dir"):
        volume_cloud_density._ensure_relative_to_base(  # noqa: SLF001
            base_dir=tmp_path, path=tmp_path.parent, label="x"
        )


def test_volume_parse_time_variants_and_errors() -> None:
    assert (
        volume_cloud_density._parse_time(np.datetime64("2026-01-01T00:00:00")).tzinfo  # noqa: SLF001
        == timezone.utc
    )
    assert (
        volume_cloud_density._parse_time(datetime(2026, 1, 1, 0, 0, 0)).tzinfo
        == timezone.utc
    )  # noqa: SLF001
    assert (
        volume_cloud_density._parse_time(
            datetime(2026, 1, 1, 0, 0, 0, tzinfo=timezone.utc)
        ).tzinfo
        == timezone.utc
    )
    assert (
        volume_cloud_density._parse_time("2026-01-01T00:00:00Z").tzinfo == timezone.utc
    )  # noqa: SLF001
    assert volume_cloud_density._parse_time("20260101T000000Z").tzinfo == timezone.utc  # noqa: SLF001

    with pytest.raises(ValueError, match="must not be empty"):
        volume_cloud_density._parse_time("")  # noqa: SLF001

    with pytest.raises(ValueError, match="ISO8601"):
        volume_cloud_density._parse_time("not-a-time")  # noqa: SLF001


def test_volume_resolve_time_index_error_paths() -> None:
    with pytest.raises(CloudDensityExportError, match="coordinate: time"):
        volume_cloud_density._resolve_time_index(  # noqa: SLF001
            xr.Dataset(coords={"level": [1]}), valid_time=None
        )

    with pytest.raises(CloudDensityExportError, match="time coordinate is empty"):
        volume_cloud_density._resolve_time_index(  # noqa: SLF001
            xr.Dataset(coords={"time": np.array([], dtype="datetime64[s]")}),
            valid_time=None,
        )

    ds = xr.Dataset(
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
        }
    )
    with pytest.raises(CloudDensityExportError, match="valid_time not found"):
        volume_cloud_density._resolve_time_index(ds, valid_time="2026-01-01T01:00:00Z")  # noqa: SLF001


def test_volume_resolve_time_index_matches_subsecond_valid_time() -> None:
    ds = xr.Dataset(
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
        }
    )
    idx, key = volume_cloud_density._resolve_time_index(  # noqa: SLF001
        ds, valid_time="2026-01-01T00:00:00.999Z"
    )
    assert idx == 0
    assert key == "20260101T000000Z"


def test_volume_resolve_time_index_matches_subsecond_dataset_time() -> None:
    ds = xr.Dataset(
        coords={
            "time": np.array(["2026-01-01T00:00:00.123"], dtype="datetime64[ms]"),
        }
    )
    idx, key = volume_cloud_density._resolve_time_index(  # noqa: SLF001
        ds, valid_time="2026-01-01T00:00:00Z"
    )
    assert idx == 0
    assert key == "20260101T000000Z"


def test_volume_level_key_formats_and_errors() -> None:
    assert volume_cloud_density._level_key("sfc") == "sfc"  # noqa: SLF001
    assert volume_cloud_density._level_key(850.0) == "850"  # noqa: SLF001
    assert volume_cloud_density._level_key(850.5) == "850.5"  # noqa: SLF001

    with pytest.raises(CloudDensityExportError, match="non-finite"):
        volume_cloud_density._level_key(np.nan)  # noqa: SLF001

    with pytest.raises(ValueError, match="unsafe"):
        volume_cloud_density._level_key("850/700")  # noqa: SLF001


def test_volume_cli_exports_and_prints_json(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    ds = _rh_datacube_dataset(units="%")
    input_path = tmp_path / "input.nc"
    write_datacube(ds, input_path)

    output_dir = tmp_path / "out"
    rc = volume_main(
        [
            "--datacube",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--rh0",
            "80",
            "--rh1",
            "100",
            "--format",
            "netcdf",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    payload = json.loads(captured.out.strip() or "{}")
    assert payload["layer"] == "ecmwf/cloud_density"
    assert payload["rh0"] == pytest.approx(0.8)
    assert payload["rh1"] == pytest.approx(1.0)
    assert payload["levels"]
    assert payload["files"]


def test_volume_module_entrypoint_executes(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    ds = _rh_datacube_dataset(units="%")
    input_path = tmp_path / "input.nc"
    write_datacube(ds, input_path)

    output_dir = tmp_path / "out_module"
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "python -m volume",
            "--datacube",
            str(input_path),
            "--output-dir",
            str(output_dir),
            "--rh0",
            "80",
            "--rh1",
            "100",
            "--format",
            "netcdf",
        ],
    )

    with pytest.raises(SystemExit) as exc:
        runpy.run_module("volume.__main__", run_name="__main__")
    assert exc.value.code == 0
