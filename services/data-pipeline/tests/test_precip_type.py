from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr


def test_precip_type_uses_ptype_priority_and_maps_to_flags() -> None:
    from datacube.normalize import normalize_datacube_dataset

    ds = xr.Dataset(
        {
            "ptype": xr.DataArray(
                np.array([[[1.0, 2.0, 3.0], [4.0, 0.0, np.nan]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
            ),
            "2t": xr.DataArray(
                np.array(
                    [[[268.15, 280.15, 275.15], [270.15, 260.15, 274.15]]],
                    dtype=np.float32,
                ),
                dims=["time", "lat", "lon"],
                attrs={"units": "K"},
            ),
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0, 11.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0, 102.0], dtype=np.float32),
        },
    )

    out = normalize_datacube_dataset(ds, precip_type_temp_threshold_c=0.0)
    assert "precip_type" in out.data_vars
    assert out["precip_type"].attrs.get("flag_values") == [0, 1, 2]
    assert out["precip_type"].attrs.get("flag_meanings") == "rain snow mix"

    precip = out["precip_type"].values
    assert precip.shape == (1, 1, 2, 3)

    assert precip[0, 0, 0, 0] == pytest.approx(0.0)  # ptype=1 => rain (temp ignored)
    assert precip[0, 0, 0, 1] == pytest.approx(1.0)  # ptype=2 => snow
    assert precip[0, 0, 0, 2] == pytest.approx(2.0)  # ptype=3 => mix
    assert precip[0, 0, 1, 0] == pytest.approx(2.0)  # ptype=4 => mix
    assert np.isnan(precip[0, 0, 1, 1])  # ptype=0 => no precip
    assert precip[0, 0, 1, 2] == pytest.approx(0.0)  # ptype missing => fallback


def test_precip_type_fallback_to_temperature_when_ptype_missing() -> None:
    from datacube.normalize import normalize_datacube_dataset

    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.array([[[273.15, 272.15]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "K"},
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0], dtype=np.float32),
            "lon": np.array([100.0, 101.0], dtype=np.float32),
        },
    )

    out_default = normalize_datacube_dataset(ds, precip_type_temp_threshold_c=0.0)
    precip_default = out_default["precip_type"].values
    assert precip_default[0, 0, 0, 0] == pytest.approx(0.0)  # 0°C => rain
    assert precip_default[0, 0, 0, 1] == pytest.approx(1.0)  # -1°C => snow

    out_warmer = normalize_datacube_dataset(ds, precip_type_temp_threshold_c=2.0)
    precip_warmer = out_warmer["precip_type"].values
    assert precip_warmer[0, 0, 0, 0] == pytest.approx(1.0)  # 0°C < 2°C => snow
    assert precip_warmer[0, 0, 0, 1] == pytest.approx(1.0)  # -1°C < 2°C => snow


def test_precip_type_threshold_is_configurable_via_config_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from datacube.normalize import normalize_datacube_dataset

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "dev.json").write_text(
        json.dumps(
            {
                "pipeline": {"precip_type_temp_threshold_c": 2.0},
                "api": {"host": "0.0.0.0", "port": 8000},
                "web": {"api_base_url": "http://localhost:8000"},
                "database": {
                    "host": "localhost",
                    "port": 5432,
                    "name": "digital_earth",
                },
                "redis": {"host": "localhost", "port": 6379},
                "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.delenv(
        "DIGITAL_EARTH_PIPELINE_PRECIP_TYPE_TEMP_THRESHOLD_C", raising=False
    )

    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.array([[[273.15]]], dtype=np.float32),
                dims=["time", "lat", "lon"],
                attrs={"units": "K"},
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0], dtype=np.float32),
            "lon": np.array([100.0], dtype=np.float32),
        },
    )

    out = normalize_datacube_dataset(ds)
    precip = out["precip_type"].values
    assert precip[0, 0, 0, 0] == pytest.approx(1.0)  # 0°C < 2°C => snow


def test_precip_type_threshold_env_var_overrides_config_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    from datacube.normalize import normalize_datacube_dataset

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "dev.json").write_text(
        json.dumps({"pipeline": {"precip_type_temp_threshold_c": 2.0}}),
        encoding="utf-8",
    )

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))

    ds = xr.Dataset(
        {
            "air_temperature": xr.DataArray(
                np.array([[[278.15]]], dtype=np.float32),  # 5°C
                dims=["time", "lat", "lon"],
                attrs={"units": "K"},
            )
        },
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([10.0], dtype=np.float32),
            "lon": np.array([100.0], dtype=np.float32),
        },
    )

    monkeypatch.setenv("DIGITAL_EARTH_PIPELINE_PRECIP_TYPE_TEMP_THRESHOLD_C", "10.0")
    out = normalize_datacube_dataset(ds)
    assert out["precip_type"].values[0, 0, 0, 0] == pytest.approx(1.0)  # 5°C < 10°C

    monkeypatch.setenv("DIGITAL_EARTH_PIPELINE_PRECIP_TYPE_TEMP_THRESHOLD_C", "nope")
    out = normalize_datacube_dataset(ds)
    assert out["precip_type"].values[0, 0, 0, 0] == pytest.approx(0.0)  # 5°C >= 2°C
