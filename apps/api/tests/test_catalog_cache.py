from __future__ import annotations

import asyncio
import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from catalog_cache import CacheRecord, StaleRedisCache
from data_source import DataNotFoundError, DataSourceError
from tests.fake_redis import FakeRedis


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


def _base_config() -> dict:
    return {
        "api": {
            "host": "0.0.0.0",
            "port": 8000,
            "debug": True,
            "cors_origins": [],
            "rate_limit": {"enabled": False},
        },
        "pipeline": {"workers": 2, "batch_size": 100, "data_source": "local"},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


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
                "index_cache_ttl_seconds: 0",
                "",
            ]
        ),
        encoding="utf-8",
    )


def _make_client(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> TestClient:
    monkeypatch.chdir(tmp_path)

    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())
    _write_local_data_config(config_dir / "local-data.yaml")

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings
    from digital_earth_config.local_data import get_local_data_paths
    from local_data_service import get_data_source
    import main

    get_settings.cache_clear()
    get_data_source.cache_clear()
    get_local_data_paths.cache_clear()

    redis = FakeRedis()
    monkeypatch.setattr(main, "create_redis_client", lambda _url: redis)
    return TestClient(main.create_app())


def _write_ecmwf_file(
    tmp_path: Path,
    *,
    file_ts: str,
    init_token: str,
    valid_token: str,
    subset: str = "00",
) -> Path:
    ecmwf_dir = tmp_path / "Data" / "EC-forecast" / "EC预报"
    ecmwf_dir.mkdir(parents=True, exist_ok=True)
    c1d = f"{init_token}{valid_token}{subset}"
    path = ecmwf_dir / f"W_NAFP_C_ECMF_{file_ts}_P_C1D{c1d}.grib2"
    path.write_bytes(b"")
    return path


def _write_cldas_stub_file(tmp_path: Path, *, ts: str = "2025010100") -> Path:
    cldas_dir = tmp_path / "Data" / "CLDAS" / "TMP" / ts[0:4] / ts[4:6] / ts[6:8]
    cldas_dir.mkdir(parents=True, exist_ok=True)
    path = cldas_dir / f"CHINA_WEST_0P05_HOR-TMP-{ts}.nc"
    path.write_bytes(b"")
    return path


def test_stale_redis_cache_prevents_stampede() -> None:
    redis = FakeRedis()
    cache = StaleRedisCache(redis, wait_timeout_s=0.2)
    calls = {"count": 0}

    async def compute() -> CacheRecord:
        calls["count"] += 1
        await asyncio.sleep(0.05)
        return CacheRecord(etag='"etag"', payload={"times": ["t1"]})

    async def runner() -> list[str]:
        results = await asyncio.gather(
            *[
                cache.get_or_compute("cldas:times:all", compute=compute)
                for _ in range(8)
            ]
        )
        return [item.status for item in results]

    statuses = asyncio.run(runner())
    assert calls["count"] == 1
    assert statuses.count("miss") == 1
    assert all(item in {"miss", "wait", "hit"} for item in statuses)


def test_stale_redis_cache_returns_stale_on_compute_failure() -> None:
    redis = FakeRedis()
    cache = StaleRedisCache(redis)

    async def setup_and_run() -> CacheRecord:
        record = CacheRecord(etag='"etag"', payload={"times": ["t1"]})
        await cache.set_record("cldas:times:all", record)
        await redis.delete("catalog:cldas:times:all")

        async def compute() -> CacheRecord:
            raise DataSourceError("boom")

        result = await cache.get_or_compute("cldas:times:all", compute=compute)
        return result.record

    record = asyncio.run(setup_and_run())
    assert record.payload["times"] == ["t1"]


def test_cache_record_from_bytes_validates_schema_and_fields() -> None:
    with pytest.raises(ValueError):
        CacheRecord.from_bytes(b'"not-a-dict"')

    with pytest.raises(ValueError):
        CacheRecord.from_bytes(b'{"schema_version":2,"etag":"x","payload":{}}')

    with pytest.raises(ValueError):
        CacheRecord.from_bytes(b'{"schema_version":1,"etag":123,"payload":{}}')


def test_stale_redis_cache_ignores_corrupt_cached_bytes() -> None:
    redis = FakeRedis()
    cache = StaleRedisCache(redis)

    async def runner() -> str:
        await redis.set("catalog:cldas:times:all", b"not-json")

        calls = {"count": 0}

        async def compute() -> CacheRecord:
            calls["count"] += 1
            return CacheRecord(etag='"etag"', payload={"times": ["t1"]})

        result = await cache.get_or_compute("cldas:times:all", compute=compute)
        assert calls["count"] == 1
        return result.status

    assert asyncio.run(runner()) in {"miss", "miss_unlocked"}


def test_stale_redis_cache_survives_redis_get_set_eval_errors() -> None:
    class BrokenGet(FakeRedis):
        async def get(self, key: str) -> bytes | None:
            raise RuntimeError("redis down")

    class BrokenSet(FakeRedis):
        async def set(self, key: str, value: bytes, **_kwargs: object) -> object:
            raise RuntimeError("redis down")

    class BrokenEval(FakeRedis):
        async def eval(
            self, script: str, numkeys: int, *keys_and_args: object
        ) -> object:
            raise RuntimeError("redis down")

    async def compute() -> CacheRecord:
        return CacheRecord(etag='"etag"', payload={"times": ["t1"]})

    status_get = asyncio.run(
        StaleRedisCache(BrokenGet()).get_or_compute("cldas:times:all", compute=compute)
    ).status
    assert status_get in {"miss", "miss_unlocked"}

    status_set = asyncio.run(
        StaleRedisCache(BrokenSet(), wait_timeout_s=0.01).get_or_compute(
            "cldas:times:all", compute=compute
        )
    ).status
    assert status_set == "miss_unlocked"

    async def compute_with_lock() -> CacheRecord:
        return CacheRecord(etag='"etag"', payload={"times": ["t1"]})

    status_eval = asyncio.run(
        StaleRedisCache(BrokenEval()).get_or_compute(
            "cldas:times:all", compute=compute_with_lock
        )
    ).status
    assert status_eval in {"miss", "miss_unlocked"}


def test_catalog_time_key_helpers_cover_edge_cases() -> None:
    from routers.catalog import (
        _cache_key_suffix,
        _handle_data_source_error,
        _time_key_from_any,
        _time_key_from_index_item,
    )

    assert _cache_key_suffix("TMP:BAD", default="all").startswith("sha256-")
    assert _time_key_from_any("2025010100") == "20250101T000000Z"
    assert _time_key_from_any("2025-01-01T00:00:00") == "20250101T000000Z"
    assert _time_key_from_any("not-a-time") is None

    bad_item = type("Item", (), {"meta": {}, "time": ""})()
    assert _time_key_from_index_item(bad_item) is None

    not_found = _handle_data_source_error(DataNotFoundError("missing"))
    assert not_found.status_code == 404
    internal = _handle_data_source_error(RuntimeError("boom"))
    assert internal.status_code == 500


def test_catalog_cldas_times_falls_back_to_stale_cache_on_failure(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_cldas_stub_file(tmp_path, ts="2025010100")
    client = _make_client(monkeypatch, tmp_path)

    initial = client.get("/api/v1/catalog/cldas/times")
    assert initial.status_code == 200
    assert initial.json()["times"] == ["20250101T000000Z"]

    redis: FakeRedis = client.app.state.redis_client
    asyncio.run(redis.delete("catalog:cldas:times:all"))

    from local_data_service import get_data_source

    ds = get_data_source()

    def boom(*_args: object, **_kwargs: object) -> object:
        raise DataSourceError("boom")

    monkeypatch.setattr(ds, "list_files", boom)

    degraded = client.get("/api/v1/catalog/cldas/times")
    assert degraded.status_code == 200
    assert degraded.json()["times"] == ["20250101T000000Z"]


def test_catalog_cldas_times_works_without_cache(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_cldas_stub_file(tmp_path, ts="2025010100")
    client = _make_client(monkeypatch, tmp_path)
    client.app.state.catalog_cache = "disabled"

    response = client.get("/api/v1/catalog/cldas/times")
    assert response.status_code == 200
    assert response.json()["times"] == ["20250101T000000Z"]


def test_catalog_handles_corrupt_cached_payloads(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_cldas_stub_file(tmp_path, ts="2025010100")
    _write_ecmwf_file(
        tmp_path,
        file_ts="20250101000000",
        init_token="01010000",
        valid_token="0101030",
    )
    client = _make_client(monkeypatch, tmp_path)

    redis: FakeRedis = client.app.state.redis_client
    bad_times = CacheRecord(etag='"etag"', payload={"times": "not-a-list"})
    asyncio.run(redis.set("catalog:cldas:times:all", bad_times.to_bytes(), ex=60))

    resp = client.get("/api/v1/catalog/cldas/times")
    assert resp.status_code == 200
    assert resp.json()["times"] == []

    bad_runs = CacheRecord(etag='"etag"', payload={"runs": "not-a-list"})
    asyncio.run(redis.set("catalog:ecmwf:runs", bad_runs.to_bytes(), ex=60))

    runs = client.get("/api/v1/catalog/ecmwf/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"] == []

    bad_ecmwf_times = CacheRecord(etag='"etag"', payload={"run": "x", "times": "bad"})
    asyncio.run(
        redis.set(
            "catalog:ecmwf:times:20250101T000000Z", bad_ecmwf_times.to_bytes(), ex=60
        )
    )

    times = client.get("/api/v1/catalog/ecmwf/20250101T000000Z/times")
    assert times.status_code == 200
    assert times.json()["times"] == []


def test_catalog_ecmwf_runs_and_times_support_etag(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_ecmwf_file(
        tmp_path,
        file_ts="20250101000000",
        init_token="01010000",
        valid_token="0101030",
    )
    _write_ecmwf_file(
        tmp_path,
        file_ts="20250101120000",
        init_token="01011200",
        valid_token="0101150",
    )

    client = _make_client(monkeypatch, tmp_path)

    runs = client.get("/api/v1/catalog/ecmwf/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"] == ["20250101T120000Z", "20250101T000000Z"]
    assert runs.headers["cache-control"] == "public, max-age=60"
    runs_etag = runs.headers["etag"]

    cached = client.get(
        "/api/v1/catalog/ecmwf/runs", headers={"If-None-Match": runs_etag}
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == runs_etag

    times = client.get("/api/v1/catalog/ecmwf/20250101T120000Z/times")
    assert times.status_code == 200
    assert times.json()["run"] == "20250101T120000Z"
    assert times.json()["times"] == ["20250101T150000Z"]

    non_hot = client.get("/api/v1/catalog/ecmwf/20250101T000000Z/times")
    assert non_hot.status_code == 200
    assert non_hot.json()["times"] == ["20250101T030000Z"]


def test_catalog_ecmwf_times_rejects_invalid_run(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path)
    response = client.get("/api/v1/catalog/ecmwf/not-a-run/times")
    assert response.status_code == 400


def test_catalog_ecmwf_hot_run_is_prewarmed(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    _write_ecmwf_file(
        tmp_path,
        file_ts="20250101000000",
        init_token="01010000",
        valid_token="0101030",
    )
    client = _make_client(monkeypatch, tmp_path)

    runs = client.get("/api/v1/catalog/ecmwf/runs")
    assert runs.status_code == 200
    assert runs.json()["runs"] == ["20250101T000000Z"]

    from local_data_service import get_data_source

    ds = get_data_source()

    def boom(*_args: object, **_kwargs: object) -> object:
        raise DataSourceError("boom")

    monkeypatch.setattr(ds, "list_files", boom)

    warmed = client.get("/api/v1/catalog/ecmwf/20250101T000000Z/times")
    assert warmed.status_code == 200
    assert warmed.json()["times"] == ["20250101T030000Z"]
