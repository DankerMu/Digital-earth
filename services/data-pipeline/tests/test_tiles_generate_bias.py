from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr


def _write_bias_config_dir(config_dir: Path, *, tile_size: int = 8) -> None:
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
                '    { "value": -5, "color": "#3B82F6" },',
                '    { "value": 0, "color": "#FFFFFF" },',
                '    { "value": 5, "color": "#EF4444" }',
                "  ]",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_forecast_dataset() -> xr.Dataset:
    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")

    temp = np.full((1, lat.size, lon.size), 1.0, dtype=np.float32)
    return xr.Dataset(
        {"temp": xr.DataArray(temp, dims=("time", "lat", "lon"))},
        coords={"time": time, "lat": lat, "lon": lon},
    )


def _make_observation_dataset() -> xr.Dataset:
    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    tmp = np.full((lat.size, lon.size), 0.0, dtype=np.float32)
    return xr.Dataset(
        {"TMP": xr.DataArray(tmp, dims=("lat", "lon"))},
        coords={"lat": lat, "lon": lon},
    )


def test_tiles_cli_can_generate_bias_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube
    from tiles.generate import main as tiles_main
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import get_temperature_legend
    import tiles.generate as tiles_generate

    config_dir = tmp_path / "config"
    _write_bias_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    forecast_ds = _make_forecast_dataset()

    def fake_open(cls, path, *, format=None, engine=None):  # noqa: ARG001
        return DataCube.from_dataset(forecast_ds)

    monkeypatch.setattr(DataCube, "open", classmethod(fake_open))

    obs_ds = _make_observation_dataset()

    def fake_load(path, *, engine=None):  # noqa: ARG001
        return obs_ds.copy()

    monkeypatch.setattr(tiles_generate, "_load_observation_dataset", fake_load)

    out_dir = tmp_path / "out"
    tiles_main(
        [
            "--datacube",
            "dummy.nc",
            "--output-dir",
            str(out_dir),
            "--no-temperature",
            "--no-cloud",
            "--no-precipitation",
            "--no-wind-speed",
            "--bias",
            "--bias-observation",
            "dummy_obs.nc",
            "--format",
            "png",
            "--min-zoom",
            "0",
            "--max-zoom",
            "0",
            "--tile-size",
            "8",
        ]
    )
    assert (out_dir / "bias" / "temp").is_dir()


def test_tiles_cli_bias_requires_observation_path(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube
    from tiles.generate import main as tiles_main
    from tiling.config import get_tiling_config
    import tiles.generate as tiles_generate

    config_dir = tmp_path / "config"
    _write_bias_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()

    forecast_ds = _make_forecast_dataset()

    def fake_open(cls, path, *, format=None, engine=None):  # noqa: ARG001
        return DataCube.from_dataset(forecast_ds)

    monkeypatch.setattr(DataCube, "open", classmethod(fake_open))

    monkeypatch.setattr(
        tiles_generate,
        "_load_observation_dataset",
        lambda *args, **kwargs: _make_observation_dataset(),  # noqa: ARG005
    )

    with pytest.raises(ValueError, match="--bias-observation is required"):
        tiles_main(
            [
                "--datacube",
                "dummy.nc",
                "--output-dir",
                str(tmp_path / "out"),
                "--no-temperature",
                "--no-cloud",
                "--no-precipitation",
                "--no-wind-speed",
                "--bias",
                "--format",
                "png",
                "--min-zoom",
                "0",
                "--max-zoom",
                "0",
                "--tile-size",
                "8",
            ]
        )
