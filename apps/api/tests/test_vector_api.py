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
    assert (
        vector_router._parse_time("20260101T000000Z", label="run")
        == datetime(2026, 1, 1, tzinfo=timezone.utc)
    )
    assert vector_router._time_key(datetime(2026, 1, 1)) == "20260101T000000Z"

    with pytest.raises(ValueError, match="must not be empty"):
        vector_router._parse_time("", label="run")

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
        vector_router._resolve_wind_components(xr.Dataset({"temp": xr.DataArray([1.0])}))
    assert exc.value.status_code == 404


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
