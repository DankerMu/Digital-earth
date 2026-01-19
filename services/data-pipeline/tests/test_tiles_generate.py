from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
import xarray as xr


def _write_test_config_dir(config_dir: Path, *, tile_size: int = 8) -> None:
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

    (config_dir / "legend.json").write_text(
        "\n".join(
            [
                "{",
                '  "title": "温度",',
                '  "unit": "°C",',
                '  "type": "gradient",',
                '  "stops": [',
                '    { "value": -20, "color": "#3B82F6", "label": "-20" },',
                '    { "value": 0, "color": "#FFFFFF", "label": "0" },',
                '    { "value": 40, "color": "#EF4444", "label": "40" }',
                "  ]",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )

    (config_dir / "wind_speed_legend.json").write_text(
        "\n".join(
            [
                "{",
                '  "title": "风速",',
                '  "unit": "m/s",',
                '  "type": "gradient",',
                '  "stops": [',
                '    { "value": 0, "color": "#ECFEFF", "label": "0" },',
                '    { "value": 50, "color": "#4C1D95", "label": "50" }',
                "  ]",
                "}",
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
                '    { "value": 0, "color": "#FFFFFF", "label": "0" },',
                '    { "value": 10, "color": "#3B82F6", "label": "10" }',
                "  ]",
                "}",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_dataset() -> xr.Dataset:
    lat = np.array([-90.0, 0.0, 90.0], dtype=np.float32)
    lon = np.array([-180.0, 0.0, 180.0], dtype=np.float32)
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")

    tmp = np.full((1, lat.size, lon.size), 0.0, dtype=np.float32)
    wind = np.full((1, lat.size, lon.size), 10.0, dtype=np.float32)
    cloud = np.full((1, lat.size, lon.size), 0.5, dtype=np.float32)
    precip = np.full((1, lat.size, lon.size), 1.0, dtype=np.float32)

    return xr.Dataset(
        {
            "temp": xr.DataArray(tmp, dims=["time", "lat", "lon"]),
            "tcc": xr.DataArray(cloud, dims=["time", "lat", "lon"]),
            "precipitation_amount": xr.DataArray(precip, dims=["time", "lat", "lon"]),
            "wind_speed": xr.DataArray(wind, dims=["time", "lat", "lon"]),
        },
        coords={"time": time, "lat": lat, "lon": lon},
    )


def test_parse_formats_splits_and_dedupes() -> None:
    from tiles.generate import _parse_formats

    assert _parse_formats(["png, webp", "PNG", "", "webp"]) == ("png", "webp")


def test_default_valid_time_requires_time_coord() -> None:
    from datacube.core import DataCube
    from tiles.generate import _default_valid_time

    cube = DataCube(dataset=xr.Dataset(coords={"lat": [0.0], "lon": [0.0]}))
    with pytest.raises(ValueError, match="missing required coordinate: time"):
        _default_valid_time(cube)


def test_generate_ecmwf_tiles_requires_at_least_one_layer() -> None:
    from datacube.core import DataCube
    from tiles.generate import generate_ecmwf_raster_tiles

    cube = DataCube.from_dataset(_make_dataset())
    with pytest.raises(ValueError, match="No tile layers selected"):
        generate_ecmwf_raster_tiles(
            cube,
            "out",
            temperature=False,
            cloud=False,
            precipitation=False,
            wind_speed=False,
        )


def test_generate_ecmwf_tiles_supports_cloud_and_precipitation(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube
    from tiles.generate import generate_ecmwf_raster_tiles
    from tiling.config import get_tiling_config
    from tiling.precip_amount_tiles import get_precip_amount_legend
    from tiling.temperature_tiles import get_temperature_legend

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()
    get_precip_amount_legend.cache_clear()

    cube = DataCube.from_dataset(_make_dataset())
    results = generate_ecmwf_raster_tiles(
        cube,
        tmp_path / "tiles",
        temperature=True,
        cloud=True,
        precipitation=True,
        wind_speed=True,
        wind_speed_opacity=0.25,
        min_zoom=0,
        max_zoom=0,
        tile_size=8,
        formats=("png",),
    )
    assert len(results) == 4
    assert (tmp_path / "tiles" / "ecmwf" / "temp").is_dir()
    assert (tmp_path / "tiles" / "ecmwf" / "tcc").is_dir()
    assert (tmp_path / "tiles" / "ecmwf" / "precip_amount").is_dir()
    assert (tmp_path / "tiles" / "ecmwf" / "wind_speed").is_dir()


def test_tiles_cli_wind_speed_toggle(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube
    from tiles.generate import main as tiles_main
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import get_temperature_legend

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    ds = _make_dataset()

    def fake_open(cls, path, *, format=None, engine=None):  # noqa: ARG001
        return DataCube.from_dataset(ds)

    monkeypatch.setattr(DataCube, "open", classmethod(fake_open))

    out_temp = tmp_path / "temp_only"
    tiles_main(
        [
            "--datacube",
            "dummy.nc",
            "--output-dir",
            str(out_temp),
            "--no-cloud",
            "--no-precipitation",
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
    assert (out_temp / "ecmwf" / "temp").is_dir()
    assert not (out_temp / "ecmwf" / "wind_speed").exists()

    out_wind = tmp_path / "temp_and_wind"
    tiles_main(
        [
            "--datacube",
            "dummy.nc",
            "--output-dir",
            str(out_wind),
            "--no-cloud",
            "--no-precipitation",
            "--wind-speed",
            "--wind-speed-opacity",
            "0.25",
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
    assert (out_wind / "ecmwf" / "temp").is_dir()
    assert (out_wind / "ecmwf" / "wind_speed").is_dir()


def test_tiles_cli_rejects_invalid_wind_speed_opacity(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    from datacube.core import DataCube
    from tiles.generate import main as tiles_main
    from tiling.config import get_tiling_config
    from tiling.temperature_tiles import get_temperature_legend

    config_dir = tmp_path / "config"
    _write_test_config_dir(config_dir, tile_size=8)
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_tiling_config.cache_clear()
    get_temperature_legend.cache_clear()

    ds = _make_dataset()

    def fake_open(cls, path, *, format=None, engine=None):  # noqa: ARG001
        return DataCube.from_dataset(ds)

    monkeypatch.setattr(DataCube, "open", classmethod(fake_open))

    with pytest.raises(ValueError, match="opacity must be between 0 and 1"):
        tiles_main(
            [
                "--datacube",
                "dummy.nc",
                "--output-dir",
                str(tmp_path / "out"),
                "--no-temperature",
                "--no-cloud",
                "--no-precipitation",
                "--wind-speed",
                "--wind-speed-opacity",
                "2",
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
