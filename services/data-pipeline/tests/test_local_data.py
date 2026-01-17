from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path
import json
import time

import numpy as np
import pytest
import xarray as xr

from digital_earth_config.local_data import get_local_data_paths

from data_source import DataSourceError, LocalDataSource, RemoteDataSource
from local.cache import get_local_file_index
from local.cldas_loader import CldasLocalLoadError, load_cldas_dataset
from local.ecmwf_loader import EcmwfLocalLoadError, read_ecmwf_grib_bytes
from local.indexer import (
    LocalFileIndex,
    LocalFileIndexItem,
    build_local_file_index,
    build_local_file_index_from_config,
    index_cldas_file,
    index_discovered_file,
    index_ecmwf_file,
    index_town_forecast_file,
)
from local.ecmwf_loader import summarize_ecmwf_grib
from local.scanner import discover_local_files
from local.town_forecast import TownForecastParseError, parse_town_forecast_file


def _write_local_data_config(path: Path) -> None:
    path.write_text(
        "\n".join(
            [
                "schema_version: 1",
                "root_dir: Data",
                "sources:",
                "  cldas: CLDAS",
                "  ecmwf: EC-forecast/EC预报",
                "  town_forecast: 城镇预报导出",
                "",
            ]
        ),
        encoding="utf-8",
    )


def test_indexer_parses_expected_file_patterns(tmp_path: Path) -> None:
    root_dir = tmp_path / "Data"
    root_dir.mkdir(parents=True, exist_ok=True)

    cldas = root_dir / "CLDAS" / "SSRA" / "2022" / "03" / "03"
    cldas.mkdir(parents=True, exist_ok=True)
    cldas_file = cldas / "CHINA_WEST_0P05_HOR-SSRA-2022030315.nc"
    cldas_file.write_bytes(b"test")
    cldas_item = index_cldas_file(cldas_file, root_dir=root_dir)
    assert cldas_item is not None
    assert cldas_item.kind == "cldas"
    assert cldas_item.variable == "SSRA"

    ecmwf = root_dir / "EC-forecast" / "EC预报"
    ecmwf.mkdir(parents=True, exist_ok=True)
    ecmwf_file = ecmwf / "W_NAFP_C_ECMF_20251222052305_P_C1D12220000122300001.grib"
    ecmwf_file.write_bytes(b"test")
    ecmwf_item = index_ecmwf_file(ecmwf_file, root_dir=root_dir)
    assert ecmwf_item is not None
    assert ecmwf_item.kind == "ecmwf"
    assert ecmwf_item.meta["lead_hours"] == 24
    assert ecmwf_item.meta["subset"] == "01"

    town = root_dir / "城镇预报导出"
    town.mkdir(parents=True, exist_ok=True)
    town_file = (
        town / "Z_SEVP_C_BABJ_20251104074025_P_RFFC-SNWFD-202511041600-16812.TXT"
    )
    town_file.write_text("test", encoding="utf-8")
    town_item = index_town_forecast_file(town_file, root_dir=root_dir)
    assert town_item is not None
    assert town_item.kind == "town_forecast"
    assert town_item.variable == "SNWFD"


def test_scanner_discovers_expected_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml")

    root_dir = tmp_path / "Data"
    (root_dir / "CLDAS").mkdir(parents=True, exist_ok=True)
    (root_dir / "EC-forecast" / "EC预报").mkdir(parents=True, exist_ok=True)
    (root_dir / "城镇预报导出").mkdir(parents=True, exist_ok=True)

    (root_dir / "CLDAS" / "x.nc").write_text("x", encoding="utf-8")
    (root_dir / "EC-forecast" / "EC预报" / "y.grib").write_text("y", encoding="utf-8")
    (root_dir / "城镇预报导出" / "z.TXT").write_text("z", encoding="utf-8")
    (root_dir / "城镇预报导出" / "ignore.bin").write_text("z", encoding="utf-8")

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    files = discover_local_files(paths)
    assert [f.kind for f in files] == ["cldas", "ecmwf", "town_forecast"]


def test_cache_invalidates_when_file_changes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml")

    root_dir = tmp_path / "Data"
    cldas_dir = root_dir / "CLDAS"
    cldas_dir.mkdir(parents=True, exist_ok=True)
    sample = cldas_dir / "CHINA_WEST_0P05_HOR-SSRA-2022030315.nc"
    sample.write_text("one", encoding="utf-8")

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    cache_path = tmp_path / ".cache" / "index.json"
    first = get_local_file_index(paths, cache_path=cache_path)
    assert first.items

    sample.write_text("two", encoding="utf-8")
    second = get_local_file_index(paths, cache_path=cache_path)
    assert second.items[0].mtime_ns != first.items[0].mtime_ns


def test_cldas_loader_normalizes_lat_lon_and_adds_time(tmp_path: Path) -> None:
    root_dir = tmp_path / "Data" / "CLDAS"
    root_dir.mkdir(parents=True, exist_ok=True)
    path = root_dir / "CHINA_WEST_0P05_HOR-TMP-2025010100.nc"

    ds = xr.Dataset(
        data_vars={
            "SWDN": (("LAT", "LON"), np.arange(6, dtype=np.float32).reshape(2, 3)),
        },
        coords={
            "LAT": ("LAT", np.array([10.0, 10.5], dtype=np.float64)),
            "LON": ("LON", np.array([70.0, 70.5, 71.0], dtype=np.float64)),
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")

    loaded = load_cldas_dataset(path, engine="h5netcdf")
    try:
        assert "time" in loaded.dims
        assert loaded.dims["time"] == 1
        assert "lat" in loaded.coords
        assert "lon" in loaded.coords
        assert "TMP" in loaded.data_vars
    finally:
        loaded.close()


def test_cldas_loader_accepts_mixed_case_axis_names(tmp_path: Path) -> None:
    root_dir = tmp_path / "Data" / "CLDAS"
    root_dir.mkdir(parents=True, exist_ok=True)
    path = root_dir / "CHINA_WEST_0P05_HOR-TMP-2025010100.nc"

    ds = xr.Dataset(
        data_vars={
            "SWDN": (("Lat", "Lon"), np.arange(6, dtype=np.float32).reshape(2, 3)),
        },
        coords={
            "Lat": ("Lat", np.array([10.0, 10.5], dtype=np.float64)),
            "Lon": ("Lon", np.array([70.0, 70.5, 71.0], dtype=np.float64)),
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")

    loaded = load_cldas_dataset(path, engine="h5netcdf")
    try:
        assert "lat" in loaded.coords
        assert "lon" in loaded.coords
    finally:
        loaded.close()


def test_cldas_loader_rejects_invalid_timestamp_in_filename(tmp_path: Path) -> None:
    path = tmp_path / "CHINA_WEST_0P05_HOR-TMP-2025010124.nc"
    with pytest.raises(CldasLocalLoadError, match="Invalid CLDAS timestamp"):
        load_cldas_dataset(path)


def test_cldas_loader_reports_missing_file(tmp_path: Path) -> None:
    path = tmp_path / "CHINA_WEST_0P05_HOR-TMP-2025010100.nc"
    with pytest.raises(CldasLocalLoadError, match="file not found"):
        load_cldas_dataset(path)


def test_cldas_loader_rejects_file_over_max_bytes(tmp_path: Path) -> None:
    root_dir = tmp_path / "Data" / "CLDAS"
    root_dir.mkdir(parents=True, exist_ok=True)
    path = root_dir / "CHINA_WEST_0P05_HOR-TMP-2025010100.nc"
    path.write_bytes(b"abcd")

    with pytest.raises(CldasLocalLoadError, match="too large"):
        load_cldas_dataset(path, max_file_size_bytes=1)


def test_cldas_loader_wraps_non_netcdf_files(tmp_path: Path) -> None:
    root_dir = tmp_path / "Data" / "CLDAS"
    root_dir.mkdir(parents=True, exist_ok=True)
    path = root_dir / "CHINA_WEST_0P05_HOR-TMP-2025010100.nc"
    path.write_text("not-a-netcdf", encoding="utf-8")

    with pytest.raises(CldasLocalLoadError, match="Failed to load CLDAS NetCDF"):
        load_cldas_dataset(path, engine="h5netcdf")


def test_cldas_loader_rejects_missing_lat_lon_axes(tmp_path: Path) -> None:
    root_dir = tmp_path / "Data" / "CLDAS"
    root_dir.mkdir(parents=True, exist_ok=True)
    path = root_dir / "CHINA_WEST_0P05_HOR-TMP-2025010100.nc"

    ds = xr.Dataset(
        data_vars={
            "SWDN": (("x", "y"), np.arange(6, dtype=np.float32).reshape(2, 3)),
        }
    )
    ds.to_netcdf(path, engine="h5netcdf")

    with pytest.raises(CldasLocalLoadError, match="Missing LAT/LON"):
        load_cldas_dataset(path, engine="h5netcdf")


def test_cldas_loader_enforces_total_cells_limit(tmp_path: Path) -> None:
    root_dir = tmp_path / "Data" / "CLDAS"
    root_dir.mkdir(parents=True, exist_ok=True)
    path = root_dir / "CHINA_WEST_0P05_HOR-TMP-2025010100.nc"

    ds = xr.Dataset(
        data_vars={
            "SWDN": (("LAT", "LON"), np.arange(6, dtype=np.float32).reshape(2, 3)),
        },
        coords={
            "LAT": ("LAT", np.array([10.0, 10.5], dtype=np.float64)),
            "LON": ("LON", np.array([70.0, 70.5, 71.0], dtype=np.float64)),
        },
    )
    ds.to_netcdf(path, engine="h5netcdf")

    with pytest.raises(CldasLocalLoadError, match="dataset too large"):
        load_cldas_dataset(path, engine="h5netcdf", max_total_cells=1)


def test_town_forecast_parser_reads_single_station(tmp_path: Path) -> None:
    root_dir = tmp_path / "Data" / "城镇预报导出"
    root_dir.mkdir(parents=True, exist_ok=True)
    path = root_dir / "Z_SEVP_C_BABJ_20250101000000_P_RFFC-SNWFD-202501010800-1212.TXT"
    values = ["999.9"] * 18 + ["1.0", "2.0", "0.0"]
    path.write_text(
        "\n".join(
            [
                "ZCZC",
                "FSCI50 BABJ 010000",
                "2025010100时公共服务产品",
                "SNWFD 2025010100",
                "1",
                "58321 117.06 31.96 36.5 14 21",
                "12 " + " ".join(values),
                "",
            ]
        ),
        encoding="utf-8",
    )

    parsed = parse_town_forecast_file(path)
    assert parsed.product == "SNWFD"
    assert parsed.station_count == 1
    assert len(parsed.stations) == 1
    assert parsed.stations[0].station_id == "58321"
    assert parsed.stations[0].leads[0].weather == "多云"


def test_data_source_lists_and_loads_files(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))

    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    cldas_dir = paths.root_dir / "CLDAS" / "TMP" / "2025" / "01" / "01"
    cldas_dir.mkdir(parents=True, exist_ok=True)
    cldas_path = cldas_dir / "CHINA_WEST_0P05_HOR-TMP-2025010100.nc"
    ds = xr.Dataset(
        data_vars={
            "SWDN": (("LAT", "LON"), np.arange(6, dtype=np.float32).reshape(2, 3))
        },
        coords={
            "LAT": ("LAT", np.array([10.0, 10.5], dtype=np.float64)),
            "LON": ("LON", np.array([70.0, 70.5, 71.0], dtype=np.float64)),
        },
    )
    ds.to_netcdf(cldas_path, engine="h5netcdf")

    ecmwf_dir = paths.root_dir / "EC-forecast" / "EC预报"
    ecmwf_dir.mkdir(parents=True, exist_ok=True)
    ecmwf_path = ecmwf_dir / "W_NAFP_C_ECMF_20251222052305_P_C1D12220000122300001.grib"
    ecmwf_path.write_bytes(b"abcd")

    town_dir = paths.root_dir / "城镇预报导出"
    town_dir.mkdir(parents=True, exist_ok=True)
    town_path = (
        town_dir / "Z_SEVP_C_BABJ_20250101000000_P_RFFC-SNWFD-202501010800-1212.TXT"
    )
    values = ["999.9"] * 18 + ["1.0", "2.0", "0.0"]
    town_path.write_text(
        "\n".join(
            [
                "ZCZC",
                "FSCI50 BABJ 010000",
                "2025010100时公共服务产品",
                "SNWFD 2025010100",
                "1",
                "58321 117.06 31.96 36.5 14 21",
                "12 " + " ".join(values),
                "",
            ]
        ),
        encoding="utf-8",
    )

    src = LocalDataSource(paths=paths, cache_path=tmp_path / ".cache" / "idx.json")
    assert src.paths == paths
    index = src.list_files()
    assert {item.kind for item in index.items} == {"cldas", "ecmwf", "town_forecast"}
    filtered = src.list_files(kinds={"cldas"})
    assert filtered.items and {item.kind for item in filtered.items} == {"cldas"}

    cldas_rel = str(cldas_path.relative_to(paths.root_dir))
    summary = src.load_cldas_summary(cldas_rel)
    assert summary.variable == "TMP"
    assert summary.dims["time"] == 1

    town_rel = str(town_path.relative_to(paths.root_dir))
    parsed = src.load_town_forecast(town_rel, max_stations=1)
    assert parsed.stations[0].station_id == "58321"

    ecmwf_rel = str(ecmwf_path.relative_to(paths.root_dir))
    assert src.load_ecmwf_bytes(ecmwf_rel, max_bytes=10) == b"abcd"
    with pytest.raises(EcmwfLocalLoadError, match="too large"):
        src.load_ecmwf_bytes(ecmwf_rel, max_bytes=1)

    with pytest.raises(DataSourceError):
        src.open_path("../escape.txt")


def test_data_source_open_path_rejects_symlink_escape_and_absolute_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))

    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()
    paths.root_dir.mkdir(parents=True, exist_ok=True)

    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")

    link_path = paths.root_dir / "link.txt"
    try:
        link_path.symlink_to(outside)
    except OSError:
        pytest.skip("Symlinks are not supported in this environment")

    src = LocalDataSource(paths=paths, cache_path=tmp_path / ".cache" / "idx.json")
    with pytest.raises(DataSourceError, match="resolve within"):
        src.open_path("link.txt")
    with pytest.raises(DataSourceError, match="resolve within"):
        src.open_path(str(outside.resolve()))


def test_remote_data_source_is_not_implemented() -> None:
    remote = RemoteDataSource()
    with pytest.raises(DataSourceError, match="not implemented"):
        remote.list_files()


def test_town_forecast_parser_handles_dynamic_periods(tmp_path: Path) -> None:
    root_dir = tmp_path / "Data" / "城镇预报导出"
    root_dir.mkdir(parents=True, exist_ok=True)
    path = root_dir / "Z_SEVP_C_BABJ_20250101000000_P_RFFC-SNWFD-202501010800-10012.TXT"
    values = ["999.9"] * 18 + ["1.0", "2.0", "0.0"]
    path.write_text(
        "\n".join(
            [
                "ZCZC",
                "FSCI50 BABJ 010000",
                "2025010100时公共服务产品",
                "SNWFD 2025010100",
                "1",
                "58321 117.06 31.96 36.5 14 21",
                "12 " + " ".join(values),
                "24 " + " ".join(values),
                "",
            ]
        ),
        encoding="utf-8",
    )
    parsed = parse_town_forecast_file(path)
    assert len(parsed.stations[0].leads) == 2


def test_town_forecast_parser_rejects_missing_header(tmp_path: Path) -> None:
    path = tmp_path / "bad.TXT"
    path.write_text("ZCZC\n", encoding="utf-8")
    with pytest.raises(TownForecastParseError, match="too short"):
        parse_town_forecast_file(path)


def test_cldas_loader_rejects_unrecognized_filename(tmp_path: Path) -> None:
    path = tmp_path / "not-a-cldas.nc"
    path.write_text("x", encoding="utf-8")
    with pytest.raises(CldasLocalLoadError, match="Unrecognized CLDAS filename"):
        load_cldas_dataset(path)


def test_ecmwf_loader_read_bytes_limit(tmp_path: Path) -> None:
    path = tmp_path / "a.grib"
    path.write_bytes(b"abcd")
    assert read_ecmwf_grib_bytes(path, max_bytes=10) == b"abcd"
    with pytest.raises(EcmwfLocalLoadError, match="too large"):
        read_ecmwf_grib_bytes(path, max_bytes=1)


def test_data_source_get_index_item_and_read_bytes(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    town_dir = paths.root_dir / "城镇预报导出"
    town_dir.mkdir(parents=True, exist_ok=True)
    town_path = (
        town_dir / "Z_SEVP_C_BABJ_20250101000000_P_RFFC-SNWFD-202501010800-1212.TXT"
    )
    values = ["999.9"] * 18 + ["1.0", "0.0", "0.0"]
    town_path.write_text(
        "\n".join(
            [
                "ZCZC",
                "FSCI50 BABJ 010000",
                "2025010100时公共服务产品",
                "SNWFD 2025010100",
                "1",
                "58321 117.06 31.96 36.5 14 21",
                "12 " + " ".join(values),
                "",
            ]
        ),
        encoding="utf-8",
    )

    src = LocalDataSource(paths=paths, cache_path=tmp_path / ".cache" / "idx.json")
    _ = src.list_files()
    rel = str(town_path.relative_to(paths.root_dir))

    item = src.get_index_item(rel)
    assert item.kind == "town_forecast"

    raw = src.read_bytes(rel)
    assert b"SNWFD" in raw

    with pytest.raises(DataSourceError, match="must not be empty"):
        src.open_path(" ")
    with pytest.raises(FileNotFoundError):
        src.open_path("missing.txt")
    with pytest.raises(FileNotFoundError):
        src.get_index_item("missing.txt")

    remote = RemoteDataSource()
    with pytest.raises(DataSourceError, match="not implemented"):
        remote.open_path("x")


def test_cache_loads_cached_index_when_valid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    cldas_dir = paths.root_dir / "CLDAS"
    cldas_dir.mkdir(parents=True, exist_ok=True)
    cldas_path = cldas_dir / "CHINA_WEST_0P05_HOR-SSRA-2022030315.nc"
    cldas_path.write_text("x", encoding="utf-8")

    cache_path = tmp_path / ".cache" / "index.json"
    first = get_local_file_index(paths, cache_path=cache_path)
    second = get_local_file_index(paths, cache_path=cache_path)
    assert second.generated_at == first.generated_at

    cache_path.write_text("not-json", encoding="utf-8")
    rebuilt = get_local_file_index(paths, cache_path=cache_path)
    assert rebuilt.items

    cldas_path.unlink()
    rebuilt2 = get_local_file_index(paths, cache_path=cache_path)
    assert (
        rebuilt2.generated_at != rebuilt.generated_at or rebuilt2.items != rebuilt.items
    )


def test_cache_ttl_zero_disables_cached_reads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    (config_dir / "local-data.yaml").write_text(
        "\n".join(
            [
                "schema_version: 1",
                "root_dir: Data",
                "index_cache_ttl_seconds: 0",
                "sources:",
                "  cldas: CLDAS",
                "  ecmwf: EC-forecast/EC预报",
                "  town_forecast: 城镇预报导出",
                "",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    cldas_dir = paths.root_dir / "CLDAS"
    cldas_dir.mkdir(parents=True, exist_ok=True)
    cldas_path = cldas_dir / "CHINA_WEST_0P05_HOR-SSRA-2022030315.nc"
    cldas_path.write_text("x", encoding="utf-8")

    cache_path = tmp_path / ".cache" / "index.json"
    first = get_local_file_index(paths, cache_path=cache_path)
    time.sleep(0.001)
    second = get_local_file_index(paths, cache_path=cache_path)
    assert second.generated_at != first.generated_at


def test_indexer_covers_edge_cases(tmp_path: Path) -> None:
    root_dir = tmp_path / "Data"
    root_dir.mkdir(parents=True, exist_ok=True)

    bad_ts = root_dir / "CHINA_WEST_0P05_HOR-SSRA-2025010124.nc"
    bad_ts.write_text("x", encoding="utf-8")
    assert index_cldas_file(bad_ts, root_dir=root_dir) is None

    outside_root = tmp_path / "outside"
    outside_root.mkdir(parents=True, exist_ok=True)
    outside_file = outside_root / "CHINA_WEST_0P05_HOR-SSRA-2022030315.nc"
    outside_file.write_text("x", encoding="utf-8")
    item = index_cldas_file(outside_file, root_dir=root_dir)
    assert item is not None
    assert item.relative_path == str(outside_file.resolve())

    rollover_dir = root_dir / "EC-forecast"
    rollover_dir.mkdir(parents=True, exist_ok=True)
    rollover = rollover_dir / "W_NAFP_C_ECMF_20251231235959_P_C1D12312300010100001.grib"
    rollover.write_text("x", encoding="utf-8")
    ecmwf_item = index_ecmwf_file(rollover, root_dir=root_dir)
    assert ecmwf_item is not None
    assert ecmwf_item.meta["lead_hours"] == 1

    invalid_valid = (
        rollover_dir / "W_NAFP_C_ECMF_20251222052305_P_C1D12220000122300601.grib"
    )
    invalid_valid.write_text("x", encoding="utf-8")
    assert index_ecmwf_file(invalid_valid, root_dir=root_dir) is None

    _ = index_discovered_file(kind="unknown", path=rollover, root_dir=root_dir)  # type: ignore[arg-type]

    missing = root_dir / "CHINA_WEST_0P05_HOR-SSRA-2022030315.nc"
    built = build_local_file_index([("cldas", missing)], root_dir=root_dir)
    assert built.items == []


def test_indexer_model_validators_and_helpers(tmp_path: Path) -> None:
    item = LocalFileIndexItem(
        kind="cldas",
        path=tmp_path / "a.nc",
        relative_path=tmp_path / "a.nc",
        size=1,
        mtime_ns=1,
    )
    assert isinstance(item.path, str)

    with pytest.raises(ValueError, match="Unsupported local index schema_version"):
        LocalFileIndex(schema_version=2, generated_at="x", root_dir="x")  # type: ignore[call-arg]


def test_build_local_file_index_from_config(tmp_path: Path) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml")

    data_dir = tmp_path / "Data" / "CLDAS"
    data_dir.mkdir(parents=True, exist_ok=True)
    sample = data_dir / "CHINA_WEST_0P05_HOR-SSRA-2022030315.nc"
    sample.write_text("x", encoding="utf-8")

    monkeypatch = pytest.MonkeyPatch()
    try:
        monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
        get_local_data_paths.cache_clear()
        paths = get_local_data_paths()
    finally:
        monkeypatch.undo()

    index = build_local_file_index_from_config(
        paths,
        discovered=[("cldas", sample)],  # type: ignore[list-item]
    )
    assert index.items and index.root_dir == str(paths.root_dir.resolve())


def test_ecmwf_loader_summary_and_not_found(tmp_path: Path) -> None:
    path = tmp_path / "a.grib"
    path.write_bytes(b"abcd")
    summary = summarize_ecmwf_grib(path)
    assert summary.size == 4

    with pytest.raises(EcmwfLocalLoadError, match="not found"):
        summarize_ecmwf_grib(tmp_path / "missing.grib")
    with pytest.raises(EcmwfLocalLoadError, match="not found"):
        read_ecmwf_grib_bytes(tmp_path / "missing.grib")


def test_data_source_abstract_base_default_raises() -> None:
    from data_source import DataSource

    class Dummy(DataSource):
        def list_files(self, *, kinds=None):  # type: ignore[override]
            return super().list_files(kinds=kinds)

        def open_path(self, relative_path: str) -> Path:
            return super().open_path(relative_path)

    dummy = Dummy()
    with pytest.raises(NotImplementedError):
        dummy.list_files()
    with pytest.raises(NotImplementedError):
        dummy.open_path("x")


def test_cache_invalidates_when_item_outside_root(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    outside = tmp_path / "outside.txt"
    outside.write_text("x", encoding="utf-8")
    stat = outside.stat()
    generated_at = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    cache_path = tmp_path / ".cache" / "index.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": generated_at,
                "root_dir": str(paths.root_dir.resolve()),
                "items": [
                    {
                        "kind": "cldas",
                        "path": str(outside.resolve()),
                        "relative_path": str(outside.resolve()),
                        "size": int(stat.st_size),
                        "mtime_ns": int(stat.st_mtime_ns),
                        "time": "2020-01-01T00:00:00Z",
                        "variable": "SSRA",
                        "meta": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    index = get_local_file_index(paths, cache_path=cache_path)
    assert index.items == []


def test_cache_handles_missing_files_between_is_file_and_stat(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    missing_path = tmp_path / "missing.nc"
    generated_at = (
        datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    )
    cache_path = tmp_path / ".cache" / "index.json"
    cache_path.parent.mkdir(parents=True, exist_ok=True)
    cache_path.write_text(
        json.dumps(
            {
                "schema_version": 1,
                "generated_at": generated_at,
                "root_dir": str(paths.root_dir.resolve()),
                "items": [
                    {
                        "kind": "cldas",
                        "path": str(missing_path.resolve()),
                        "relative_path": "missing.nc",
                        "size": 1,
                        "mtime_ns": 1,
                        "time": "2020-01-01T00:00:00Z",
                        "variable": "SSRA",
                        "meta": {},
                    }
                ],
            }
        ),
        encoding="utf-8",
    )

    monkeypatch.setattr(Path, "is_file", lambda self: True)
    index = get_local_file_index(paths, cache_path=cache_path)
    assert index.items == []


def test_scanner_skips_non_directory_sources(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    config_dir.mkdir(parents=True, exist_ok=True)
    _write_local_data_config(config_dir / "local-data.yaml")

    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    get_local_data_paths.cache_clear()
    paths = get_local_data_paths()

    # Replace one of the expected source directories with a file to exercise the
    # `not root.is_dir()` branch in the scanner.
    paths.cldas_dir.parent.mkdir(parents=True, exist_ok=True)
    paths.cldas_dir.write_text("not-a-dir", encoding="utf-8")

    files = discover_local_files(paths)
    assert all(item.kind != "cldas" for item in files)
