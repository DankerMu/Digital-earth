from __future__ import annotations

import gzip
import json
import sys
from pathlib import Path
from types import ModuleType
from typing import Any, Callable

import pytest
from fastapi.testclient import TestClient


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


def _make_client(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path, *, config_overrides: dict | None
) -> TestClient:
    config_dir = tmp_path / "config"
    base = _base_config()
    if config_overrides:
        for section, overrides in config_overrides.items():
            if isinstance(overrides, dict):
                base.setdefault(section, {}).update(overrides)
            else:
                base[section] = overrides
    _write_config(config_dir, "dev", base)

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    from config import get_settings
    from main import create_app

    get_settings.cache_clear()
    return TestClient(create_app())


class FakeBody:
    def __init__(self, data: bytes) -> None:
        self._data = data

    def read(self) -> bytes:
        return self._data


class FakeClientError(RuntimeError):
    def __init__(self, *, status_code: int, code: str) -> None:
        super().__init__(code)
        self.response = {
            "Error": {"Code": code},
            "ResponseMetadata": {"HTTPStatusCode": status_code},
        }


def _install_fake_boto3(
    monkeypatch: pytest.MonkeyPatch, *, client_factory: Callable[..., object]
) -> None:
    fake_boto3 = ModuleType("boto3")
    fake_boto3.client = lambda *args, **kwargs: client_factory(*args, **kwargs)  # type: ignore[attr-defined]
    monkeypatch.setitem(sys.modules, "boto3", fake_boto3)


def test_tiles_redirects_to_base_url_and_sets_cache_headers(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(
        monkeypatch,
        tmp_path,
        config_overrides={
            "storage": {"tiles_base_url": "https://cdn.example/tiles"},
        },
    )

    response = client.get("/api/v1/tiles/layer/time/1/2/3.png", follow_redirects=False)
    assert response.status_code == 302
    assert (
        response.headers["location"] == "https://cdn.example/tiles/layer/time/1/2/3.png"
    )
    assert response.headers["cache-control"] == "public, max-age=3600"
    assert "x-trace-id" in response.headers


def test_tiles_redirects_to_webp_when_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(
        monkeypatch,
        tmp_path,
        config_overrides={
            "storage": {"tiles_base_url": "https://cdn.example/tiles"},
        },
    )

    response = client.get(
        "/api/v1/tiles/layer/time/1/2/3.png",
        headers={"Accept": "image/webp"},
        follow_redirects=False,
    )
    assert response.status_code == 302
    assert response.headers["location"].endswith(".webp")
    assert response.headers["vary"] == "Accept"


def test_tiles_redirects_to_signed_url_when_credentials_present(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class SignedClient:
        def generate_presigned_url(
            self, operation: str, *, Params: dict[str, str], ExpiresIn: int
        ) -> str:
            assert operation == "get_object"
            assert Params["Bucket"] == "tiles"
            assert Params["Key"] == "a/b/c.png"
            assert ExpiresIn == 900
            return "https://signed.example/object?a=1"

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: SignedClient()
    )
    monkeypatch.setenv("DIGITAL_EARTH_STORAGE_ACCESS_KEY_ID", "a")
    monkeypatch.setenv("DIGITAL_EARTH_STORAGE_SECRET_ACCESS_KEY", "b")

    client = _make_client(
        monkeypatch,
        tmp_path,
        config_overrides={"storage": {"endpoint_url": "https://s3.example"}},
    )

    response = client.get("/api/v1/tiles/a/b/c.png", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://signed.example/object?a=1"
    assert response.headers["cache-control"] == "public, max-age=899"


def test_tiles_proxy_returns_bytes_with_etag_and_supports_304(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ProxyClient:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            assert Bucket == "tiles"
            assert Key == "a/b/c.png"
            return {
                "Body": FakeBody(b"png-bytes"),
                "ContentType": "image/png",
                "CacheControl": "public, max-age=3600",
                "ETag": '"t"',
            }

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: ProxyClient()
    )
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    ok = client.get("/api/v1/tiles/a/b/c.png?redirect=false")
    assert ok.status_code == 200
    assert ok.content == b"png-bytes"
    assert ok.headers["etag"] == '"t"'
    assert ok.headers["cache-control"] == "public, max-age=3600"

    cached = client.get(
        "/api/v1/tiles/a/b/c.png?redirect=false", headers={"If-None-Match": '"t"'}
    )
    assert cached.status_code == 304
    assert cached.headers["etag"] == '"t"'
    assert cached.text == ""


def test_tiles_proxy_gzips_vector_tiles_when_accepted(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"a" * 2048

    class ProxyClient:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            assert Bucket == "tiles"
            assert Key == "vector/0/0/0.pbf"
            return {
                "Body": FakeBody(payload),
                "ContentType": "application/x-protobuf",
                "CacheControl": "public, max-age=3600",
                "ETag": '"v"',
            }

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: ProxyClient()
    )
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    response = client.get(
        "/api/v1/tiles/vector/0/0/0.pbf?redirect=false",
        headers={"Accept-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert response.headers["content-encoding"] == "gzip"
    assert response.headers["vary"] == "Accept-Encoding"
    assert "etag" not in response.headers
    assert int(response.headers["content-length"]) < len(payload)
    # httpx TestClient transparently decodes gzip; response bytes are the decoded payload.
    assert response.content == payload


def test_tiles_proxy_decompresses_when_storage_is_gzip_but_client_disallows(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = b"hello" * 300
    encoded = gzip.compress(raw)

    class ProxyClient:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            assert Bucket == "tiles"
            assert Key == "vector/0/0/0.pbf"
            return {
                "Body": FakeBody(encoded),
                "ContentType": "application/x-protobuf",
                "ContentEncoding": "gzip",
                "CacheControl": "public, max-age=3600",
                "ETag": '"gz"',
            }

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: ProxyClient()
    )
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    response = client.get(
        "/api/v1/tiles/vector/0/0/0.pbf?redirect=false",
        headers={"Accept-Encoding": "identity"},
    )
    assert response.status_code == 200
    assert response.content == raw
    assert "content-encoding" not in response.headers
    assert response.headers["vary"] == "Accept-Encoding"
    assert "etag" not in response.headers


def test_tiles_proxy_prefers_webp_and_falls_back_when_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    png_bytes = b"png-bytes"

    class ProxyClient:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            assert Bucket == "tiles"
            if Key.endswith(".webp"):
                raise FakeClientError(status_code=404, code="NoSuchKey")
            assert Key == "a/b/c.png"
            return {
                "Body": FakeBody(png_bytes),
                "ContentType": "image/png",
                "CacheControl": "public, max-age=3600",
            }

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: ProxyClient()
    )
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    response = client.get(
        "/api/v1/tiles/a/b/c.png?redirect=false", headers={"Accept": "image/webp"}
    )
    assert response.status_code == 200
    assert response.content == png_bytes
    assert response.headers["vary"] == "Accept"


def test_tiles_invalid_path_returns_unified_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(
        monkeypatch,
        tmp_path,
        config_overrides={"storage": {"tiles_base_url": "https://cdn.example/tiles"}},
    )

    response = client.get("/api/v1/tiles/%2e%2e/secret.png")
    assert response.status_code == 400
    assert response.headers["content-type"].startswith("application/json")
    payload = response.json()
    assert payload["error_code"] == 40000
    assert payload["message"] == "Invalid tile path"
    assert payload["trace_id"] == response.headers["x-trace-id"]


def test_tiles_missing_storage_config_returns_500(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    response = client.get("/api/v1/tiles/a/b/c.png")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "Tiles storage is not configured" in payload["message"]


def test_tiles_redirects_to_unsigned_endpoint_url_when_configured(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    client = _make_client(
        monkeypatch,
        tmp_path,
        config_overrides={"storage": {"endpoint_url": "https://s3.example"}},
    )

    response = client.get("/api/v1/tiles/a/b/c.png", follow_redirects=False)
    assert response.status_code == 302
    assert response.headers["location"] == "https://s3.example/tiles/a/b/c.png"


def test_tiles_signed_url_requires_boto3(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    monkeypatch.delitem(sys.modules, "boto3", raising=False)
    monkeypatch.setenv("DIGITAL_EARTH_STORAGE_ACCESS_KEY_ID", "a")
    monkeypatch.setenv("DIGITAL_EARTH_STORAGE_SECRET_ACCESS_KEY", "b")

    client = _make_client(
        monkeypatch,
        tmp_path,
        config_overrides={"storage": {"endpoint_url": "https://s3.example"}},
    )

    response = client.get("/api/v1/tiles/a/b/c.png", follow_redirects=False)
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
    assert "boto3 is required for signed tiles URLs" in payload["message"]


def test_tiles_proxy_returns_404_when_object_missing(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ProxyClient:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            raise FakeClientError(status_code=404, code="NoSuchKey")

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: ProxyClient()
    )
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    response = client.get("/api/v1/tiles/a/b/c.png?redirect=false")
    assert response.status_code == 404
    payload = response.json()
    assert payload["error_code"] == 40400
    assert payload["message"] == "Not Found"


def test_tiles_proxy_returns_500_when_storage_body_invalid(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ProxyClient:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            return {"Body": None}

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: ProxyClient()
    )
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    response = client.get("/api/v1/tiles/a/b/c.png?redirect=false")
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000


@pytest.mark.parametrize(
    ("path", "expected_content_type"),
    [
        ("/api/v1/tiles/a/b/c.json?redirect=false", "application/json"),
        ("/api/v1/tiles/a/b/c.jpg?redirect=false", "image/jpeg"),
        ("/api/v1/tiles/a/b/c.mvt?redirect=false", "application/x-protobuf"),
    ],
)
def test_tiles_proxy_guesses_content_type_when_missing(
    monkeypatch: pytest.MonkeyPatch,
    tmp_path: Path,
    path: str,
    expected_content_type: str,
) -> None:
    class ProxyClient:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            return {"Body": FakeBody(b"data"), "CacheControl": "public, max-age=3600"}

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: ProxyClient()
    )
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    response = client.get(path, headers={"Accept-Encoding": "identity"})
    assert response.status_code == 200
    assert response.headers["content-type"].startswith(expected_content_type)


def test_tiles_proxy_does_not_gzip_images(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    payload = b"a" * 2048

    class ProxyClient:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            return {
                "Body": FakeBody(payload),
                "ContentType": "image/png",
                "CacheControl": "public, max-age=3600",
                "ETag": '"img"',
            }

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: ProxyClient()
    )
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    response = client.get(
        "/api/v1/tiles/a/b/c.png?redirect=false",
        headers={"Accept-Encoding": "gzip"},
    )
    assert response.status_code == 200
    assert "content-encoding" not in response.headers
    assert "vary" not in response.headers
    assert response.headers["etag"] == '"img"'


def test_tiles_proxy_can_return_304_for_gzipped_object_when_client_accepts_gzip(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    raw = b"hello" * 300
    encoded = gzip.compress(raw)

    class ProxyClient:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            return {
                "Body": FakeBody(encoded),
                "ContentType": "application/x-protobuf",
                "ContentEncoding": "gzip",
                "CacheControl": "public, max-age=3600",
                "ETag": '"gz"',
            }

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: ProxyClient()
    )
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    response = client.get(
        "/api/v1/tiles/vector/0/0/0.pbf?redirect=false",
        headers={"Accept-Encoding": "gzip", "If-None-Match": '"gz"'},
    )
    assert response.status_code == 304
    assert response.headers["etag"] == '"gz"'
    assert response.headers["vary"] == "Accept-Encoding"


def test_tiles_proxy_returns_500_when_gzip_decode_fails(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    class ProxyClient:
        def get_object(self, *, Bucket: str, Key: str) -> dict[str, Any]:
            return {
                "Body": FakeBody(b"not-gzip"),
                "ContentType": "application/x-protobuf",
                "ContentEncoding": "gzip",
                "CacheControl": "public, max-age=3600",
            }

    _install_fake_boto3(
        monkeypatch, client_factory=lambda *args, **kwargs: ProxyClient()
    )
    client = _make_client(monkeypatch, tmp_path, config_overrides=None)

    response = client.get(
        "/api/v1/tiles/vector/0/0/0.pbf?redirect=false",
        headers={"Accept-Encoding": "identity"},
    )
    assert response.status_code == 500
    payload = response.json()
    assert payload["error_code"] == 50000
