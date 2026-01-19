from __future__ import annotations

import json
from pathlib import Path
from typing import Any

import pytest

from redis_fakes import FakeRedis


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
        "pipeline": {"workers": 2, "batch_size": 100},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


def _create_app(monkeypatch: pytest.MonkeyPatch, tmp_path: Path):
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings

    get_settings.cache_clear()

    import main as main_module

    redis = FakeRedis(use_real_time=False)
    monkeypatch.setattr(main_module, "create_redis_client", lambda _url: redis)
    return main_module.create_app()


def _canonical_json(data: Any) -> str:
    return json.dumps(data, indent=2, sort_keys=True) + "\n"


def _load_openapi_snapshot() -> tuple[Path, str, dict[str, Any]]:
    snapshot_path = Path(__file__).resolve().parents[1] / "openapi.json"
    raw = snapshot_path.read_text(encoding="utf-8")
    return snapshot_path, raw, json.loads(raw)


def _resolve_ref(openapi: dict[str, Any], ref: str) -> Any:
    if not ref.startswith("#/"):
        raise ValueError(f"Unsupported ref: {ref!r}")
    cursor: Any = openapi
    for part in ref.removeprefix("#/").split("/"):
        cursor = cursor[part]
    return cursor


def _resolve_schema(openapi: dict[str, Any], schema: dict[str, Any]) -> dict[str, Any]:
    cursor = schema
    while "$ref" in cursor:
        cursor = _resolve_ref(openapi, cursor["$ref"])
    return cursor


def _response_schema(
    openapi: dict[str, Any],
    *,
    path: str,
    method: str,
    status_code: int,
    content_type: str = "application/json",
) -> dict[str, Any]:
    operation = openapi["paths"][path][method.lower()]
    responses = operation["responses"]
    response = responses[str(status_code)]
    content = response["content"][content_type]
    return content.get("schema", {})


def test_openapi_snapshot_matches_implementation(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _create_app(monkeypatch, tmp_path)

    snapshot_path, expected_text, _expected = _load_openapi_snapshot()
    actual_text = _canonical_json(app.openapi())

    if actual_text != expected_text:
        output_path = tmp_path / "openapi.actual.json"
        output_path.write_text(actual_text, encoding="utf-8")
        pytest.fail(
            "OpenAPI snapshot is out of date.\n"
            f"- Expected: {snapshot_path}\n"
            f"- Actual: {output_path}\n"
            "Re-generate with:\n"
            "  DIGITAL_EARTH_DB_USER=app DIGITAL_EARTH_DB_PASSWORD=secret "
            "PYTHONPATH=apps/api/src:packages/config/src:packages/shared/src:"
            "services/data-pipeline/src python3.11 - <<'PY'\n"
            "  import json\n"
            "  from pathlib import Path\n"
            "  import main\n"
            "  schema = main.create_app().openapi()\n"
            "  Path('apps/api/openapi.json').write_text(\n"
            "      json.dumps(schema, indent=2, sort_keys=True) + '\\n',\n"
            "      encoding='utf-8',\n"
            "  )\n"
            "  PY"
        )


def test_contract_key_fields_exist(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    app = _create_app(monkeypatch, tmp_path)
    openapi = app.openapi()

    # Catalog
    cldas_times = _resolve_schema(
        openapi,
        _response_schema(
            openapi, path="/api/v1/catalog/cldas/times", method="GET", status_code=200
        ),
    )
    assert cldas_times["type"] == "object"
    assert cldas_times["properties"]["times"]["type"] == "array"
    assert cldas_times["properties"]["times"]["items"]["type"] == "string"

    # Tiles
    cldas_tile = _response_schema(
        openapi,
        path="/api/v1/tiles/cldas/{time_key}/{var}/{z}/{x}/{y}.png",
        method="GET",
        status_code=200,
        content_type="image/png",
    )
    assert cldas_tile["type"] == "string"
    assert cldas_tile["format"] == "binary"

    storage_tile = _response_schema(
        openapi,
        path="/api/v1/tiles/{tile_path}",
        method="GET",
        status_code=200,
        content_type="application/octet-stream",
    )
    assert storage_tile["type"] == "string"
    assert storage_tile["format"] == "binary"

    # Vector
    wind = _resolve_schema(
        openapi,
        _response_schema(
            openapi,
            path="/api/v1/vector/ecmwf/{run}/wind/{level}/{time}",
            method="GET",
            status_code=200,
        ),
    )
    assert wind["type"] == "object"
    assert set(wind["properties"]) >= {"u", "v", "lat", "lon"}

    # Products
    products = _resolve_schema(
        openapi,
        _response_schema(
            openapi, path="/api/v1/products", method="GET", status_code=200
        ),
    )
    assert products["type"] == "object"
    assert set(products["properties"]) >= {"page", "page_size", "total", "items"}
    assert products["properties"]["items"]["type"] == "array"
    assert products["properties"]["items"]["items"]["$ref"].endswith(
        "/ProductSummaryResponse"
    )

    # Risk
    pois = _resolve_schema(
        openapi,
        _response_schema(
            openapi, path="/api/v1/risk/pois", method="GET", status_code=200
        ),
    )
    assert pois["type"] == "object"
    assert set(pois["properties"]) >= {"page", "page_size", "total", "items"}
