from __future__ import annotations

from pathlib import Path

import numpy as np
import pytest
from PIL import Image


def test_demo_monitoring_dataset_is_repeatable() -> None:
    from tiling.demo_monitoring import DemoBounds, create_demo_monitoring_dataset

    bounds = DemoBounds(west=110.0, south=30.0, east=111.0, north=31.0)
    ds1 = create_demo_monitoring_dataset(seed=87, bounds=bounds, resolution_deg=0.5)
    ds2 = create_demo_monitoring_dataset(seed=87, bounds=bounds, resolution_deg=0.5)
    ds3 = create_demo_monitoring_dataset(seed=88, bounds=bounds, resolution_deg=0.5)
    try:
        assert set(ds1.data_vars) == {"SD", "PRE"}
        assert list(ds1.dims) == ["time", "lat", "lon"]

        assert np.array_equal(ds1["SD"].values, ds2["SD"].values, equal_nan=True)
        assert np.array_equal(ds1["PRE"].values, ds2["PRE"].values, equal_nan=True)

        assert not np.array_equal(ds1["SD"].values, ds3["SD"].values, equal_nan=True)
        assert not np.array_equal(ds1["PRE"].values, ds3["PRE"].values, equal_nan=True)
    finally:
        ds1.close()
        ds2.close()
        ds3.close()


def test_generate_demo_monitoring_tiles_writes_layers(tmp_path: Path) -> None:
    from tiling.demo_monitoring import DemoBounds, generate_demo_monitoring_tiles

    bounds = DemoBounds(west=110.0, south=30.0, east=115.0, north=35.0)
    results = generate_demo_monitoring_tiles(
        tmp_path,
        seed=87,
        bounds=bounds,
        resolution_deg=0.5,
        min_zoom=0,
        max_zoom=0,
        tile_size=128,
    )
    assert {result.layer for result in results} == {"cldas/sd", "cldas/pre"}
    assert all(result.tiles_written == 1 for result in results)

    time_key = "20260101T000000Z"
    sd_legend = tmp_path / "cldas" / "sd" / "legend.json"
    pre_legend = tmp_path / "cldas" / "pre" / "legend.json"
    assert sd_legend.is_file()
    assert pre_legend.is_file()

    sd_tile = tmp_path / "cldas" / "sd" / time_key / "0" / "0" / "0.png"
    pre_tile = tmp_path / "cldas" / "pre" / time_key / "0" / "0" / "0.png"
    assert sd_tile.is_file()
    assert pre_tile.is_file()

    sd_img = Image.open(sd_tile)
    pre_img = Image.open(pre_tile)
    try:
        assert sd_img.mode == "RGBA"
        assert pre_img.mode == "RGBA"
        sd_pixels = np.asarray(sd_img)
        pre_pixels = np.asarray(pre_img)
        assert sd_pixels.shape == (128, 128, 4)
        assert pre_pixels.shape == (128, 128, 4)

        # Zoom 0 is global; most of the tile should be transparent outside demo bounds.
        assert sd_pixels[..., 3].min() == 0
        assert sd_pixels[..., 3].max() == 255
        assert pre_pixels[..., 3].min() == 0
        assert pre_pixels[..., 3].max() == 255

        assert not np.array_equal(sd_pixels, pre_pixels)
    finally:
        sd_img.close()
        pre_img.close()


def test_gradient_rgba_from_legend_matches_temperature_endpoints() -> None:
    from legend import load_legend
    from tiling.cldas_tiles import gradient_rgba_from_legend, temperature_rgba

    legend = load_legend("cldas", "tmp", "legend.json")
    values = np.array([[-20.0, 0.0, 40.0, np.nan]], dtype=np.float32)
    rgba_expected = temperature_rgba(values)
    rgba_actual = gradient_rgba_from_legend(values, legend=legend)
    assert np.array_equal(rgba_expected, rgba_actual)


def test_demo_bounds_validation_rejects_invalid_inputs() -> None:
    from tiling.demo_monitoring import DemoBounds

    with pytest.raises(ValueError, match="east must be > west"):
        DemoBounds(west=0.0, east=0.0, south=0.0, north=1.0).validate()

    with pytest.raises(ValueError, match="north must be > south"):
        DemoBounds(west=0.0, east=1.0, south=0.0, north=0.0).validate()

    with pytest.raises(ValueError, match="must be finite"):
        DemoBounds(west=float("nan"), east=1.0, south=0.0, north=1.0).validate()


def test_demo_monitoring_cli_entrypoint_runs(tmp_path: Path, capsys) -> None:
    from tiling.demo_monitoring import main

    exit_code = main(
        [
            "--output-dir",
            str(tmp_path),
            "--seed",
            "87",
            "--time-iso",
            "2026-01-01T00:00:00Z",
            "--west",
            "100",
            "--south",
            "20",
            "--east",
            "140",
            "--north",
            "50",
            "--resolution-deg",
            "1.0",
            "--min-zoom",
            "0",
            "--max-zoom",
            "0",
            "--tile-size",
            "32",
        ]
    )
    assert exit_code == 0
    out = capsys.readouterr().out.strip().splitlines()
    assert len(out) == 2
    assert any('"layer": "cldas/sd"' in line for line in out)
    assert any('"layer": "cldas/pre"' in line for line in out)


def test_demo_monitoring_internal_validation_helpers() -> None:
    from tiling.demo_monitoring import _axis, _time_coord_from_iso

    with pytest.raises(ValueError, match="resolution_deg must be > 0"):
        _axis(0.0, 1.0, 0.0)

    with pytest.raises(ValueError, match="time_iso must not be empty"):
        _time_coord_from_iso("")

    parsed = _time_coord_from_iso("2026-01-01T00:00:00Z")
    assert parsed.dtype == np.dtype("datetime64[s]")
