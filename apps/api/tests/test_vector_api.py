from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

import numpy as np
import pytest
import xarray as xr
from fastapi import HTTPException
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import Session

from redis_fakes import FakeRedis


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


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


def _base_config(*, data_source: str = "local") -> dict:
    return {
        "api": {
            "host": "0.0.0.0",
            "port": 8000,
            "debug": True,
            "cors_origins": [],
            "rate_limit": {"enabled": False},
        },
        "pipeline": {"workers": 2, "batch_size": 100, "data_source": data_source},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


def _seed_asset(
    db_url: str,
    *,
    run_time: datetime,
    valid_time: datetime,
    variable: str,
    level: str,
    path: str,
) -> None:
    from models import Base, EcmwfAsset, EcmwfRun, EcmwfTime

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)

    with Session(engine) as session:
        run = EcmwfRun(run_time=run_time, status="complete")
        time = EcmwfTime(valid_time=valid_time, run=run)
        asset = EcmwfAsset(
            variable=variable,
            level=level,
            status="complete",
            version=1,
            path=path,
            run=run,
            time=time,
        )
        session.add_all([run, time, asset])
        session.commit()


def _make_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, db_url: str
) -> tuple[TestClient, FakeRedis]:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config(data_source="local"))
    _write_local_data_config(config_dir / "local-data.yaml")

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")
    monkeypatch.setenv("DATABASE_URL", db_url)

    from config import get_settings
    from db import get_engine
    from local_data_service import get_data_source
    import main as main_module

    get_settings.cache_clear()
    get_engine.cache_clear()
    get_data_source.cache_clear()

    from models import Base

    engine = create_engine(db_url)
    Base.metadata.create_all(engine)
    engine.dispose()

    redis = FakeRedis(use_real_time=False)
    monkeypatch.setattr(main_module, "create_redis_client", lambda _url: redis)
    return TestClient(main_module.create_app()), redis


def _write_wind_datacube(
    path: Path,
    *,
    u_name: str,
    v_name: str,
    u_values: np.ndarray,
    v_values: np.ndarray,
    lat: np.ndarray,
    lon: np.ndarray,
    level: xr.DataArray,
) -> None:
    time = np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]")

    ds = xr.Dataset(
        {
            u_name: xr.DataArray(
                u_values,
                dims=["time", "level", "lat", "lon"],
                attrs={"units": "m/s"},
            ),
            v_name: xr.DataArray(
                v_values,
                dims=["time", "level", "lat", "lon"],
                attrs={"units": "m/s"},
            ),
        },
        coords={"time": time, "level": level, "lat": lat, "lon": lon},
    )

    path.parent.mkdir(parents=True, exist_ok=True)
    ds.to_netcdf(path, engine="h5netcdf")


def test_vector_helpers_cover_edge_cases() -> None:
    from routers import vector as vector_router

    parsed = vector_router._parse_time("2026-01-01T00:00:00", label="run")
    assert parsed.tzinfo == timezone.utc
    assert vector_router._parse_time("20260101T000000Z", label="run") == datetime(
        2026, 1, 1, tzinfo=timezone.utc
    )
    assert vector_router._time_key(datetime(2026, 1, 1)) == "20260101T000000Z"

    with pytest.raises(ValueError, match="must not be empty"):
        vector_router._parse_time("", label="run")

    with pytest.raises(ValueError, match="must be an ISO8601 timestamp"):
        vector_router._parse_time("not-a-time", label="run")

    with pytest.raises(ValueError, match="level must not be empty"):
        vector_router._normalize_level(" ")

    assert vector_router._normalize_level("sfc") == ("sfc", None)
    assert vector_router._normalize_level("850hPa") == ("850", 850.0)
    assert vector_router._normalize_level("0.5") == ("0p5", 0.5)

    assert vector_router._parse_bbox(None) is None
    assert vector_router._parse_bbox("  ") is None

    with pytest.raises(ValueError, match="bbox must have 4"):
        vector_router._parse_bbox("1,2,3")

    with pytest.raises(ValueError, match="bbox must have 4"):
        vector_router._parse_bbox("a,b,c,d")

    with pytest.raises(ValueError, match="bbox latitude values must be within"):
        vector_router._parse_bbox("0,91,1,2")

    with pytest.raises(ValueError, match="bbox longitude values must be finite"):
        vector_router._parse_bbox("nan,0,1,2")

    lon_360 = np.array([0.0, 359.0], dtype=np.float64)
    assert vector_router._dataset_lon_uses_360(lon_360) is True
    assert vector_router._normalize_lon(-10.0, lon_360) == 350.0

    lon_180 = np.array([-179.0, 179.0], dtype=np.float64)
    assert vector_router._dataset_lon_uses_360(lon_180) is False
    assert vector_router._normalize_lon(190.0, lon_180) == -170.0

    assert vector_router._dataset_lon_uses_360(np.array([], dtype=np.float64)) is False

    lon_coord = np.array([0.0, 10.0, 350.0], dtype=np.float64)
    selected = vector_router._select_lon_indices(
        lon_coord, min_lon=-10.0, max_lon=10.0, stride=1
    )
    assert selected.tolist() == [0, 1, 2]

    lon_180_full = np.array([-180.0, -90.0, 0.0, 90.0, 180.0], dtype=np.float64)
    selected = vector_router._select_lon_indices(
        lon_180_full, min_lon=-180.0, max_lon=180.0, stride=1
    )
    assert selected.tolist() == [0, 1, 2, 3, 4]

    lon_360_full = np.array([0.0, 90.0, 180.0, 270.0, 359.0], dtype=np.float64)
    selected = vector_router._select_lon_indices(
        lon_360_full, min_lon=0.0, max_lon=360.0, stride=1
    )
    assert selected.tolist() == [0, 1, 2, 3, 4]

    assert vector_router._flatten_values(np.array([1.0, np.nan], dtype=np.float32)) == [
        1.0,
        None,
    ]

    with pytest.raises(HTTPException) as exc:
        vector_router._resolve_surface_level_index(
            np.array([850.0], dtype=np.float32),
            {"units": "hPa"},
        )
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        vector_router._resolve_level_index(xr.Dataset(), level_key="850", numeric=850.0)
    assert exc.value.status_code == 500

    with pytest.raises(HTTPException) as exc:
        vector_router._resolve_time_index(xr.Dataset(), valid_time=parsed)
    assert exc.value.status_code == 500

    ds_one_time = xr.Dataset(
        coords={
            "time": np.array(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
        }
    )
    with pytest.raises(HTTPException) as exc:
        vector_router._resolve_time_index(
            ds_one_time, valid_time=datetime(2026, 1, 2, tzinfo=timezone.utc)
        )
    assert exc.value.status_code == 404

    with pytest.raises(HTTPException) as exc:
        vector_router._resolve_wind_components(
            xr.Dataset({"temp": xr.DataArray([1.0])})
        )
    assert exc.value.status_code == 404


def test_streamlines_helpers_cover_edge_cases() -> None:
    from routers import vector as vector_router

    # normalize axis: no-op vs reversed coordinate
    values = np.arange(6, dtype=np.float32).reshape(3, 2)
    coord = np.array([0.0, 1.0, 2.0], dtype=np.float32)
    norm_coord, norm_values = vector_router._normalize_grid_axis(coord, values, axis=0)
    assert norm_coord.tolist() == [0.0, 1.0, 2.0]
    assert norm_values.tolist() == values.astype(np.float64).tolist()

    desc_coord = np.array([2.0, 1.0, 0.0], dtype=np.float32)
    flipped_coord, flipped_values = vector_router._normalize_grid_axis(
        desc_coord, values, axis=0
    )
    assert flipped_coord.tolist() == [0.0, 1.0, 2.0]
    assert flipped_values.tolist() == values[::-1].astype(np.float64).tolist()

    # bilinear sampling: hit/miss + NaN handling
    lat_coord = np.array([0.0, 1.0], dtype=np.float64)
    lon_coord = np.array([0.0, 1.0], dtype=np.float64)
    u_grid = np.array([[0.0, 2.0], [4.0, 6.0]], dtype=np.float64)
    v_grid = np.array([[0.0, 0.0], [2.0, 2.0]], dtype=np.float64)

    sampled = vector_router._bilinear_sample_wind(
        lat=0.5,
        lon=0.5,
        lat_coord=lat_coord,
        lon_coord=lon_coord,
        u_grid=u_grid,
        v_grid=v_grid,
    )
    assert sampled == pytest.approx((3.0, 1.0))

    assert (
        vector_router._bilinear_sample_wind(
            lat=-1.0,
            lon=0.5,
            lat_coord=lat_coord,
            lon_coord=lon_coord,
            u_grid=u_grid,
            v_grid=v_grid,
        )
        is None
    )
    assert (
        vector_router._bilinear_sample_wind(
            lat=0.5,
            lon=5.0,
            lat_coord=lat_coord,
            lon_coord=lon_coord,
            u_grid=u_grid,
            v_grid=v_grid,
        )
        is None
    )

    u_nan = u_grid.copy()
    u_nan[0, 0] = np.nan
    assert (
        vector_router._bilinear_sample_wind(
            lat=0.5,
            lon=0.5,
            lat_coord=lat_coord,
            lon_coord=lon_coord,
            u_grid=u_nan,
            v_grid=v_grid,
        )
        is None
    )

    # rk4 step: speed threshold + polar singularity guard
    lat_coord2 = np.array([0.0, 1.0], dtype=np.float64)
    lon_coord2 = np.array([0.0, 1.0], dtype=np.float64)
    u_zero = np.zeros((2, 2), dtype=np.float64)
    v_zero = np.zeros((2, 2), dtype=np.float64)
    assert (
        vector_router._rk4_step(
            lat=0.5,
            lon_unwrapped=0.5,
            lon_coord=lon_coord2,
            lat_coord=lat_coord2,
            u_grid=u_zero,
            v_grid=v_zero,
            step_m=1000.0,
            min_speed=0.1,
            direction=1.0,
        )
        is None
    )

    lat_polar = np.array([89.0, 90.0], dtype=np.float64)
    lon_polar = np.array([0.0, 1.0], dtype=np.float64)
    u_polar = np.ones((2, 2), dtype=np.float64)
    v_polar = np.zeros((2, 2), dtype=np.float64)
    assert (
        vector_router._rk4_step(
            lat=89.99999,
            lon_unwrapped=0.5,
            lon_coord=lon_polar,
            lat_coord=lat_polar,
            u_grid=u_polar,
            v_grid=v_polar,
            step_m=1000.0,
            min_speed=0.0,
            direction=1.0,
        )
        is None
    )

    # streamline integration: seed outside bbox returns empty polyline
    bbox = (0.0, 0.0, 1.0, 1.0)
    empty_lat, empty_lon = vector_router._integrate_streamline(
        seed_lat=2.0,
        seed_lon=2.0,
        bbox=bbox,
        lat_coord=lat_coord2,
        lon_coord=lon_coord2,
        u_grid=u_polar,
        v_grid=v_polar,
        step_km=1.0,
        max_steps=5,
        min_speed=0.0,
    )
    assert empty_lat == []
    assert empty_lon == []


def test_streamlines_helpers_cover_wrap_bbox_and_short_lines() -> None:
    from routers import vector as vector_router

    # bbox span >= 360 means "any lon" within lat range.
    lon_coord = np.array([0.0, 359.0], dtype=np.float64)
    bbox_global = (0.0, -10.0, 360.0, 10.0)
    assert (
        vector_router._bbox_contains(
            lon=123.0, lat=0.0, bbox=bbox_global, lon_coord=lon_coord
        )
        is True
    )
    assert (
        vector_router._bbox_contains(
            lon=123.0, lat=20.0, bbox=bbox_global, lon_coord=lon_coord
        )
        is False
    )

    # bbox that crosses dateline should accept lon near 360 and near 0.
    bbox_wrap = (350.0, -10.0, 10.0, 10.0)
    assert (
        vector_router._bbox_contains(
            lon=355.0, lat=0.0, bbox=bbox_wrap, lon_coord=lon_coord
        )
        is True
    )
    assert (
        vector_router._bbox_contains(
            lon=5.0, lat=0.0, bbox=bbox_wrap, lon_coord=lon_coord
        )
        is True
    )
    assert (
        vector_router._bbox_contains(
            lon=180.0, lat=0.0, bbox=bbox_wrap, lon_coord=lon_coord
        )
        is False
    )

    # streamline integration: if RK4 cannot advance, return empty polyline.
    lat_coord2 = np.array([0.0, 1.0], dtype=np.float64)
    lon_coord2 = np.array([0.0, 1.0], dtype=np.float64)
    u_zero = np.zeros((2, 2), dtype=np.float64)
    v_zero = np.zeros((2, 2), dtype=np.float64)
    bbox = (0.0, 0.0, 1.0, 1.0)
    line_lat, line_lon = vector_router._integrate_streamline(
        seed_lat=0.5,
        seed_lon=0.5,
        bbox=bbox,
        lat_coord=lat_coord2,
        lon_coord=lon_coord2,
        u_grid=u_zero,
        v_grid=v_zero,
        step_km=1.0,
        max_steps=5,
        min_speed=0.1,
    )
    assert line_lat == []
    assert line_lon == []


def test_streamlines_helpers_cover_degenerate_grids() -> None:
    from routers import vector as vector_router

    coord = np.array([0.0], dtype=np.float32)
    values = np.array([[1.0]], dtype=np.float32)
    norm_coord, norm_values = vector_router._normalize_grid_axis(coord, values, axis=0)
    assert norm_coord.tolist() == [0.0]
    assert norm_values.tolist() == [[1.0]]

    lat_coord = np.array([0.0], dtype=np.float64)
    lon_coord = np.array([0.0, 1.0], dtype=np.float64)
    u_grid = np.zeros((1, 2), dtype=np.float64)
    v_grid = np.zeros((1, 2), dtype=np.float64)
    assert (
        vector_router._bilinear_sample_wind(
            lat=0.0,
            lon=0.5,
            lat_coord=lat_coord,
            lon_coord=lon_coord,
            u_grid=u_grid,
            v_grid=v_grid,
        )
        is None
    )

    lat_coord2 = np.array([0.0, 0.0], dtype=np.float64)
    lon_coord2 = np.array([0.0, 1.0], dtype=np.float64)
    u_grid2 = np.zeros((2, 2), dtype=np.float64)
    v_grid2 = np.zeros((2, 2), dtype=np.float64)
    assert (
        vector_router._bilinear_sample_wind(
            lat=0.0,
            lon=0.5,
            lat_coord=lat_coord2,
            lon_coord=lon_coord2,
            u_grid=u_grid2,
            v_grid=v_grid2,
        )
        is None
    )

    assert (
        vector_router._rk4_step(
            lat=0.5,
            lon_unwrapped=0.5,
            lon_coord=np.array([0.0, 1.0], dtype=np.float64),
            lat_coord=np.array([0.0, 1.0], dtype=np.float64),
            u_grid=np.zeros((2, 2), dtype=np.float64),
            v_grid=np.zeros((2, 2), dtype=np.float64),
            step_m=1000.0,
            min_speed=0.0,
            direction=1.0,
        )
        is None
    )


def test_vector_bbox_stride_returns_points_matching_datacube(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-850.nc"
    lat = np.array([0.0, 1.0, 2.0], dtype=np.float32)
    lon = np.array([10.0, 11.0, 12.0, 13.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_grid = (lat[:, None] + lon[None, :]).astype(np.float32)
    v_grid = (lat[:, None] - lon[None, :]).astype(np.float32)
    u_values = u_grid[None, None, :, :]
    v_values = v_grid[None, None, :, :]
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z",
        params={"bbox": "10,0,12,2", "stride": 2},
    )
    assert resp.status_code == 200
    payload = resp.json()

    assert payload["lat"] == [0.0, 0.0, 2.0, 2.0]
    assert payload["lon"] == [10.0, 12.0, 10.0, 12.0]
    assert payload["u"] == pytest.approx([10.0, 12.0, 12.0, 14.0])
    assert payload["v"] == pytest.approx([-10.0, -12.0, -8.0, -10.0])


def test_vector_cache_hit_skips_db_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-sfc.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray(
        [0.0], dims=["level"], attrs={"long_name": "surface", "units": "1"}
    )

    u_values = np.zeros((1, 1, 2, 2), dtype=np.float32)
    v_values = np.ones((1, 1, 2, 2), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="sfc",
        path=rel_path,
    )

    url = "/api/v1/vector/ecmwf/20260101T000000Z/wind/sfc/20260101T000000Z"
    params = {"bbox": "0,0,1,1", "stride": 1}
    first = client.get(url, params=params)
    assert first.status_code == 200

    from routers import vector as vector_router

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected cached response (no DB query)")

    monkeypatch.setattr(vector_router, "_query_asset_path", _boom)

    second = client.get(url, params=params)
    assert second.status_code == 200
    assert second.json() == first.json()


def test_vector_cache_keys_include_run_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-850.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.zeros((1, 1, 2, 2), dtype=np.float32)
    v_values = np.ones((1, 1, 2, 2), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time_1 = datetime(2026, 1, 1, tzinfo=timezone.utc)
    run_time_2 = datetime(2026, 1, 2, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time_1,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )
    _seed_asset(
        db_url,
        run_time=run_time_2,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )

    bbox = "0,0,1,1"
    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z",
        params={"bbox": bbox, "stride": 1},
    )
    assert resp.status_code == 200

    resp2 = client.get(
        "/api/v1/vector/ecmwf/20260102T000000Z/wind/850/20260101T000000Z",
        params={"bbox": bbox, "stride": 1},
    )
    assert resp2.status_code == 200

    keys = sorted(redis.values.keys())
    assert any(
        key.startswith("vector:ecmwf:wind:run=20260101T000000Z:fresh:") for key in keys
    )
    assert any(
        key.startswith("vector:ecmwf:wind:run=20260102T000000Z:fresh:") for key in keys
    )


def test_vector_file_cache_hit_skips_db_query_when_redis_disabled(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)
    client.app.state.redis_client = None
    monkeypatch.setenv("DIGITAL_EARTH_VECTOR_CACHE_DIR", str(tmp_path / "vector-cache"))

    cube_path = tmp_path / "Data" / "cubes" / "wind-850.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.zeros((1, 1, 2, 2), dtype=np.float32)
    v_values = np.ones((1, 1, 2, 2), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )

    url = "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z"
    params = {"bbox": "0,0,1,1", "stride": 1}
    first = client.get(url, params=params)
    assert first.status_code == 200

    from routers import vector as vector_router

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected cached response (no DB query)")

    monkeypatch.setattr(vector_router, "_query_asset_path", _boom)

    second = client.get(url, params=params)
    assert second.status_code == 200
    assert second.json() == first.json()


def test_vector_prewarm_endpoint_warms_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    monkeypatch.setenv("ENABLE_EDITOR", "true")
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-850.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.zeros((1, 1, 2, 2), dtype=np.float32)
    v_values = np.ones((1, 1, 2, 2), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )

    prewarm = client.post(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z/prewarm",
        json={"bboxes": ["0,0,1,1"], "stride": 1},
    )
    assert prewarm.status_code == 200
    payload = prewarm.json()
    assert payload["results"][0]["status"] == "computed"

    from routers import vector as vector_router

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected cached response (no DB query)")

    monkeypatch.setattr(vector_router, "_query_asset_path", _boom)

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z",
        params={"bbox": "0,0,1,1", "stride": 1},
    )
    assert resp.status_code == 200


def test_vector_prewarm_requires_editor_permission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    prewarm = client.post(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z/prewarm",
        json={"bboxes": ["0,0,1,1"], "stride": 1},
    )
    assert prewarm.status_code == 403


def test_vector_supports_surface_wind_10m_component_names(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-10m.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray(
        [0.0], dims=["level"], attrs={"long_name": "surface", "units": "1"}
    )

    u_values = np.array([[[[1.0, 2.0], [3.0, 4.0]]]], dtype=np.float32)
    v_values = np.array([[[[5.0, 6.0], [7.0, 8.0]]]], dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="eastward_wind_10m",
        v_name="northward_wind_10m",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="sfc",
        path=rel_path,
    )

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/sfc/20260101T000000Z",
        params={"bbox": "0,0,1,1", "stride": 1},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["lat"] == [0.0, 0.0, 1.0, 1.0]
    assert payload["lon"] == [0.0, 1.0, 0.0, 1.0]
    assert payload["u"] == pytest.approx([1.0, 2.0, 3.0, 4.0])
    assert payload["v"] == pytest.approx([5.0, 6.0, 7.0, 8.0])


def test_vector_oob_bbox_returns_empty_payload(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-850.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.zeros((1, 1, 2, 2), dtype=np.float32)
    v_values = np.ones((1, 1, 2, 2), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z",
        params={"bbox": "10,10,20,20", "stride": 1},
    )
    assert resp.status_code == 200
    assert resp.json() == {"u": [], "v": [], "lat": [], "lon": []}


def test_vector_guard_rejects_excessive_points(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-850.nc"
    lat = np.linspace(0.0, 100.0, 101, dtype=np.float32)
    lon = np.linspace(0.0, 100.0, 101, dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.zeros((1, 1, lat.size, lon.size), dtype=np.float32)
    v_values = np.ones((1, 1, lat.size, lon.size), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z",
        params={"stride": 1},
    )
    assert resp.status_code == 400
    assert resp.json()["message"] == "reduce bbox or increase stride"


def test_vector_invalid_bbox_returns_400(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z",
        params={"bbox": "not-a-bbox", "stride": 1},
    )
    assert resp.status_code == 400
    assert resp.json()["error_code"] == 40000


def test_vector_works_without_redis_and_with_absolute_asset_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)
    client.app.state.redis_client = None
    monkeypatch.setenv("DIGITAL_EARTH_VECTOR_CACHE_DIR", str(tmp_path / "vector-cache"))

    cube_path = tmp_path / "wind-850-abs.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.zeros((1, 1, 2, 2), dtype=np.float32)
    v_values = np.ones((1, 1, 2, 2), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=str(cube_path),
    )

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z",
        params={"bbox": "0,0,1,1", "stride": 1},
    )
    assert resp.status_code == 200


def test_vector_cache_timeout_returns_503(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    from routers import vector as vector_router

    async def _timeout(*_args: object, **_kwargs: object) -> object:
        raise TimeoutError("boom")

    monkeypatch.setattr(vector_router, "get_or_compute_cached_bytes", _timeout)

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z",
        params={"bbox": "0,0,1,1", "stride": 1},
    )
    assert resp.status_code == 503
    assert resp.json()["error_code"] == 50000


def test_vector_cache_error_falls_back_to_compute(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-850.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.zeros((1, 1, 2, 2), dtype=np.float32)
    v_values = np.ones((1, 1, 2, 2), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )

    from routers import vector as vector_router

    async def _fail(*_args: object, **_kwargs: object) -> object:
        raise RuntimeError("boom")

    monkeypatch.setattr(vector_router, "get_or_compute_cached_bytes", _fail)

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z",
        params={"bbox": "0,0,1,1", "stride": 1},
    )
    assert resp.status_code == 200


def test_streamlines_endpoint_returns_polylines_in_bbox(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-850.nc"
    lat = np.array([0.0, 1.0, 2.0], dtype=np.float32)
    lon = np.array([0.0, 1.0, 2.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.full((1, 1, lat.size, lon.size), 10.0, dtype=np.float32)
    v_values = np.zeros((1, 1, lat.size, lon.size), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z/streamlines",
        params={"bbox": "0,0,2,2", "stride": 1, "step_km": 10.0, "max_steps": 25},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert "streamlines" in payload
    assert len(payload["streamlines"]) == 9

    for line in payload["streamlines"]:
        assert isinstance(line["lat"], list)
        assert isinstance(line["lon"], list)
        assert len(line["lat"]) == len(line["lon"])
        assert len(line["lat"]) >= 2

        assert line["lon"][-1] > line["lon"][0]
        assert all(-1e-6 <= value <= 2.0 + 1e-6 for value in line["lat"])
        assert all(-1e-6 <= value <= 2.0 + 1e-6 for value in line["lon"])


def test_streamlines_cache_hit_skips_db_query(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-850.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.full((1, 1, lat.size, lon.size), 10.0, dtype=np.float32)
    v_values = np.zeros((1, 1, lat.size, lon.size), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )

    url = "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z/streamlines"
    params = {"bbox": "0,0,1,1", "stride": 1, "step_km": 10.0, "max_steps": 10}
    first = client.get(url, params=params)
    assert first.status_code == 200

    from routers import vector as vector_router

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected cached response (no DB query)")

    monkeypatch.setattr(vector_router, "_query_asset_path", _boom)

    second = client.get(url, params=params)
    assert second.status_code == 200
    assert second.json() == first.json()


def test_streamlines_prewarm_endpoint_warms_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    monkeypatch.setenv("ENABLE_EDITOR", "true")
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    cube_path = tmp_path / "Data" / "cubes" / "wind-850.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.full((1, 1, lat.size, lon.size), 10.0, dtype=np.float32)
    v_values = np.zeros((1, 1, lat.size, lon.size), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    rel_path = str(cube_path.relative_to(tmp_path / "Data"))
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=rel_path,
    )

    prewarm = client.post(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z/streamlines/prewarm",
        params={"step_km": 10.0, "max_steps": 10},
        json={"bboxes": ["0,0,1,1"], "stride": 1},
    )
    assert prewarm.status_code == 200
    payload = prewarm.json()
    assert payload["results"][0]["status"] == "computed"

    from routers import vector as vector_router

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected cached response (no DB query)")

    monkeypatch.setattr(vector_router, "_query_asset_path", _boom)

    resp = client.get(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z/streamlines",
        params={"bbox": "0,0,1,1", "stride": 1, "step_km": 10.0, "max_steps": 10},
    )
    assert resp.status_code == 200


def test_streamlines_prewarm_requires_editor_permission(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)

    prewarm = client.post(
        "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z/streamlines/prewarm",
        json={"bboxes": ["0,0,1,1"], "stride": 1},
    )
    assert prewarm.status_code == 403


def test_streamlines_works_without_redis_and_with_absolute_asset_path(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    db_url = f"sqlite+pysqlite:///{tmp_path / 'catalog.db'}"
    client, _redis = _make_client(monkeypatch, tmp_path, db_url=db_url)
    client.app.state.redis_client = None
    monkeypatch.setenv(
        "DIGITAL_EARTH_VECTOR_CACHE_DIR", str(tmp_path / "vector-cache-streamlines")
    )

    cube_path = tmp_path / "wind-850-abs.nc"
    lat = np.array([0.0, 1.0], dtype=np.float32)
    lon = np.array([0.0, 1.0], dtype=np.float32)
    level = xr.DataArray([850.0], dims=["level"], attrs={"units": "hPa"})

    u_values = np.full((1, 1, 2, 2), 10.0, dtype=np.float32)
    v_values = np.zeros((1, 1, 2, 2), dtype=np.float32)
    _write_wind_datacube(
        cube_path,
        u_name="u",
        v_name="v",
        u_values=u_values,
        v_values=v_values,
        lat=lat,
        lon=lon,
        level=level,
    )

    run_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    valid_time = datetime(2026, 1, 1, tzinfo=timezone.utc)
    _seed_asset(
        db_url,
        run_time=run_time,
        valid_time=valid_time,
        variable="wind",
        level="850",
        path=str(cube_path),
    )

    url = "/api/v1/vector/ecmwf/20260101T000000Z/wind/850/20260101T000000Z/streamlines"
    params = {"bbox": "0,0,1,1", "stride": 1, "step_km": 10.0, "max_steps": 10}
    first = client.get(url, params=params)
    assert first.status_code == 200

    from routers import vector as vector_router

    def _boom(*_args: object, **_kwargs: object) -> object:
        raise AssertionError("expected cached response (no DB query)")

    monkeypatch.setattr(vector_router, "_query_asset_path", _boom)

    second = client.get(url, params=params)
    assert second.status_code == 200
    assert second.json() == first.json()
