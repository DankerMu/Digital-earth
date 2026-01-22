from __future__ import annotations

import json
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from PIL import Image


def _write_small_cldas_file(
    root: Path, *, ts: str, value: float, var: str = "TMP"
) -> Path:
    path = root / f"CHINA_WEST_0P05_HOR-{var}-{ts}.nc"
    ds = xr.Dataset(
        {
            var: xr.DataArray(
                np.full((2, 2), value, dtype=np.float32), dims=["lat", "lon"]
            )
        },
        coords={
            "lat": np.array([0.0, 1.0], dtype=np.float32),
            "lon": np.array([10.0, 11.0], dtype=np.float32),
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")
    return path


def test_cldas_directory_source_lists_and_iterates(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from statistics.sources import CldasDirectorySource

    root = tmp_path / "cldas"
    root.mkdir()

    _write_small_cldas_file(root, ts="2020010100", value=1.0)
    _write_small_cldas_file(root, ts="2020010101", value=2.0)
    _write_small_cldas_file(root, ts="2020020100", value=3.0)

    source = CldasDirectorySource(root, engine="h5netcdf")
    files = source.list_files(
        variable="TMP",
        start=datetime(2020, 1, 1, tzinfo=timezone.utc),
        end=datetime(2020, 2, 1, tzinfo=timezone.utc),
    )
    assert len(files) == 2
    assert files[0].name.endswith("2020010100.nc")
    assert files[1].name.endswith("2020010101.nc")

    slices = list(
        source.iter_slices(
            variable="TMP",
            start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end=datetime(2020, 2, 1, tzinfo=timezone.utc),
        )
    )
    assert len(slices) == 2
    assert slices[0].values.shape == (2, 2)


def test_archive_dataset_source_iterates(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from statistics.sources import ArchiveDatasetSource

    path = tmp_path / "archive.nc"
    ds = xr.Dataset(
        {
            "TMP": xr.DataArray(
                np.stack([np.full((2, 2), 1.0), np.full((2, 2), 2.0)], axis=0).astype(
                    np.float32
                ),
                dims=["time", "lat", "lon"],
            )
        },
        coords={
            "time": np.array(
                ["2020-01-01T00:00:00", "2020-01-02T00:00:00"], dtype="datetime64[s]"
            ),
            "lat": np.array([0.0, 1.0], dtype=np.float32),
            "lon": np.array([10.0, 11.0], dtype=np.float32),
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")

    source = ArchiveDatasetSource(path, engine="h5netcdf")
    slices = list(
        source.iter_slices(
            variable="TMP",
            start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end=datetime(2020, 1, 3, tzinfo=timezone.utc),
        )
    )
    assert len(slices) == 2
    assert float(slices[0].values[0, 0]) == 1.0


def test_archive_dataset_source_rejects_missing_variable(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from statistics.sources import ArchiveDatasetSource, StatisticsSourceError

    path = tmp_path / "archive.nc"
    ds = xr.Dataset(
        {
            "OTHER": xr.DataArray(
                np.zeros((1, 2, 2), dtype=np.float32), dims=["time", "lat", "lon"]
            )
        },
        coords={
            "time": np.array(["2020-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.array([0.0, 1.0], dtype=np.float32),
            "lon": np.array([10.0, 11.0], dtype=np.float32),
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")

    source = ArchiveDatasetSource(path, engine="h5netcdf")
    with pytest.raises(StatisticsSourceError, match="not found"):
        list(
            source.iter_slices(
                variable="TMP",
                start=datetime(2020, 1, 1, tzinfo=timezone.utc),
                end=datetime(2020, 1, 2, tzinfo=timezone.utc),
            )
        )


def test_run_historical_statistics_writes_netcdf_and_metadata(tmp_path: Path) -> None:
    from datetime import datetime, timezone

    from statistics.batch import run_historical_statistics
    from statistics.sources import CldasDirectorySource
    from statistics.storage import StatisticsStore
    from statistics.time_windows import TimeWindow

    cldas_root = tmp_path / "cldas"
    cldas_root.mkdir()
    for i, value in enumerate(range(1, 7)):
        _write_small_cldas_file(
            cldas_root, ts=f"20200101{str(i).zfill(2)}", value=float(value)
        )

    windows = [
        TimeWindow(
            kind="monthly",
            start=datetime(2020, 1, 1, tzinfo=timezone.utc),
            end=datetime(2020, 2, 1, tzinfo=timezone.utc),
        )
    ]
    store = StatisticsStore(tmp_path / "out")
    source = CldasDirectorySource(cldas_root, engine="h5netcdf")

    results = run_historical_statistics(
        source=source,
        variable="TMP",
        windows=windows,
        store=store,
        output_source_name="cldas",
        version="vtest",
        percentiles=[10, 50, 90],
        exact_percentiles_max_samples=64,
    )
    assert len(results) == 1
    artifact = results[0].artifact
    assert artifact.dataset_path.is_file()
    assert artifact.metadata_path.is_file()

    with xr.open_dataset(artifact.dataset_path, engine="h5netcdf") as ds:
        assert ds.attrs["version"] == "vtest"
        assert ds.attrs["window_key"] == "202001"
        assert ds["mean"].shape == (2, 2)
        assert float(ds["sum"].values[0, 0]) == pytest.approx(21.0)
        assert float(ds["mean"].values[0, 0]) == pytest.approx(3.5)
        assert float(ds["p50"].values[0, 0]) == pytest.approx(3.5)
        assert int(ds["count"].values[0, 0]) == 6

    meta = json.loads(artifact.metadata_path.read_text(encoding="utf-8"))
    assert meta["version"] == "vtest"
    assert meta["window_key"] == "202001"
    assert meta["samples"] == 6


def test_statistics_tile_generator_writes_tiles_and_legend(tmp_path: Path) -> None:
    from statistics.tiles import StatisticsTileGenerator

    legend_dir = tmp_path / "cfg"
    legend_dir.mkdir()
    (legend_dir / "legend.json").write_text(
        json.dumps(
            {
                "title": "test",
                "unit": "u",
                "type": "gradient",
                "stops": [
                    {"value": 0, "color": "#000000"},
                    {"value": 1, "color": "#FFFFFF"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    ds = xr.Dataset(
        {
            "mean": xr.DataArray(
                np.full((3, 3), 0.5, dtype=np.float32), dims=["lat", "lon"]
            )
        },
        coords={
            "lat": np.array([-1.0, 0.0, 1.0], dtype=np.float64),
            "lon": np.array([-1.0, 0.0, 1.0], dtype=np.float64),
        },
    )
    generator = StatisticsTileGenerator(ds, variable="mean", layer="stats/test/mean")
    result = generator.generate(
        tmp_path,
        version="v1",
        window_key="202001",
        min_zoom=0,
        max_zoom=0,
        tile_size=4,
        formats=["png"],
        legend_config_dir=legend_dir,
        legend_filename="legend.json",
    )
    assert result.tiles_written == 1

    legend_path = tmp_path / "stats" / "test" / "mean" / "legend.json"
    assert legend_path.is_file()

    tile_path = (
        tmp_path / "stats" / "test" / "mean" / "v1" / "202001" / "0" / "0" / "0.png"
    )
    assert tile_path.is_file()

    img = Image.open(tile_path)
    try:
        assert img.mode == "RGBA"
        assert img.size == (4, 4)
    finally:
        img.close()


def test_statistics_tile_generator_rejects_unsafe_inputs(tmp_path: Path) -> None:
    from statistics.tiles import StatisticsTileGenerator

    (tmp_path / "legend.json").write_text(
        json.dumps(
            {
                "title": "test",
                "unit": "u",
                "type": "gradient",
                "stops": [
                    {"value": 0, "color": "#000000"},
                    {"value": 1, "color": "#FFFFFF"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    ds = xr.Dataset(
        {"mean": xr.DataArray(np.zeros((1, 1), dtype=np.float32), dims=["lat", "lon"])},
        coords={
            "lat": np.array([0.0], dtype=np.float32),
            "lon": np.array([0.0], dtype=np.float32),
        },
    )

    with pytest.raises(ValueError, match="layer"):
        StatisticsTileGenerator(ds, variable="mean", layer="../evil")

    generator = StatisticsTileGenerator(ds, variable="mean", layer="stats/x/mean")
    with pytest.raises(ValueError, match="version"):
        generator.generate(
            tmp_path,
            version="../evil",
            window_key="202001",
            min_zoom=0,
            max_zoom=0,
            tile_size=1,
            formats=["png"],
            legend_config_dir=tmp_path,
            legend_filename="legend.json",
        )


def test_statistics_cli_runs_end_to_end(tmp_path: Path) -> None:
    from statistics.cli import main

    cldas_root = tmp_path / "cldas"
    cldas_root.mkdir()
    for i, value in enumerate(range(1, 7)):
        _write_small_cldas_file(
            cldas_root, ts=f"20200101{str(i).zfill(2)}", value=float(value)
        )

    output_dir = tmp_path / "out"
    tiles_dir = tmp_path / "tiles"
    legend_dir = tmp_path / "cfg"
    legend_dir.mkdir()
    (legend_dir / "legend.json").write_text(
        json.dumps(
            {
                "title": "test",
                "unit": "u",
                "type": "gradient",
                "stops": [
                    {"value": 0, "color": "#000000"},
                    {"value": 10, "color": "#FFFFFF"},
                ],
            },
            ensure_ascii=False,
        ),
        encoding="utf-8",
    )

    rc = main(
        [
            "--source",
            "cldas",
            "--variable",
            "TMP",
            "--start",
            "2020-01-01T00:00:00Z",
            "--end",
            "2020-02-01T00:00:00Z",
            "--window-kind",
            "monthly",
            "--cldas-root",
            str(cldas_root),
            "--output-dir",
            str(output_dir),
            "--version",
            "vcli",
            "--percentile",
            "50",
            "--tiles",
            "--tiles-output-dir",
            str(tiles_dir),
            "--tile-var",
            "mean",
            "--layer-prefix",
            "stats",
            "--legend-config-dir",
            str(legend_dir),
            "--legend-filename",
            "legend.json",
            "--min-zoom",
            "0",
            "--max-zoom",
            "0",
            "--tile-size",
            "2",
        ]
    )
    assert rc == 0

    expected_ds = (
        output_dir / "cldas" / "TMP" / "monthly" / "vcli" / "202001" / "statistics.nc"
    )
    assert expected_ds.is_file()

    expected_tile = (
        tiles_dir
        / "stats"
        / "cldas"
        / "tmp"
        / "mean"
        / "vcli"
        / "202001"
        / "0"
        / "0"
        / "0.png"
    )
    assert expected_tile.is_file()


def test_statistics_cli_dry_run_prints_windows(capsys) -> None:
    from statistics.cli import main

    rc = main(
        [
            "--variable",
            "TMP",
            "--start",
            "2020-01-01T00:00:00Z",
            "--end",
            "2020-02-01T00:00:00Z",
            "--window-kind",
            "monthly",
            "--dry-run",
        ]
    )
    assert rc == 0
    captured = capsys.readouterr()
    assert "202001" in captured.out
