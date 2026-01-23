from __future__ import annotations

import json
from pathlib import Path

import pytest

from digital_earth_config.settings import Settings, _canonical_env


def _write_config(dir_path: Path, env: str, data: dict) -> None:
    dir_path.mkdir(parents=True, exist_ok=True)
    (dir_path / f"{env}.json").write_text(json.dumps(data), encoding="utf-8")


def _base_config() -> dict:
    return {
        "api": {"host": "0.0.0.0", "port": 8000, "debug": True, "cors_origins": []},
        "pipeline": {"workers": 2, "batch_size": 100},
        "web": {"api_base_url": "http://localhost:8000"},
        "database": {"host": "localhost", "port": 5432, "name": "digital_earth"},
        "redis": {"host": "localhost", "port": 6379},
        "storage": {"tiles_bucket": "tiles", "raw_bucket": "raw"},
    }


def test_canonical_env_defaults_and_aliases() -> None:
    assert _canonical_env(None) == "dev"
    assert _canonical_env("") == "dev"
    assert _canonical_env("development") == "dev"
    assert _canonical_env("stage") == "staging"
    assert _canonical_env("production") == "prod"
    with pytest.raises(ValueError, match="Invalid DIGITAL_EARTH_ENV"):
        _canonical_env("nope")


def test_loads_json_and_requires_db_secrets(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    settings = Settings()
    assert settings.api.port == 8000
    assert settings.database.host == "localhost"
    assert settings.database.dsn.startswith("postgresql://app:secret@")
    assert settings.api.rate_limit.enabled is True
    assert settings.api.rate_limit.ip_allowlist == []
    assert settings.api.rate_limit.ip_blocklist == []
    rules = {
        rule.path_prefix: rule.requests_per_minute
        for rule in settings.api.rate_limit.rules
    }
    assert rules["/api/v1/catalog"] == 100
    assert rules["/api/v1/vector"] == 60
    assert rules["/api/v1/tiles"] == 300
    assert rules["/api/v1/volume"] == 10
    assert rules["/api/v1/errors"] == 10
    assert settings.api.volume_cache_ttl_seconds == 3600


def test_rate_limit_rules_normalize_path_prefix(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    base = _base_config()
    base["api"]["rate_limit"] = {
        "rules": [
            {
                "path_prefix": "api/v1/catalog/",
                "requests_per_minute": 10,
                "window_seconds": 60,
            }
        ]
    }
    _write_config(config_dir, "dev", base)

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    settings = Settings()
    assert settings.api.rate_limit.rules[0].path_prefix == "/api/v1/catalog"


def test_env_overrides_deep_merge(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")
    monkeypatch.setenv("DIGITAL_EARTH_API_PORT", "9000")
    monkeypatch.setenv("DIGITAL_EARTH_API_VOLUME_CACHE_TTL_SECONDS", "120")

    settings = Settings()
    assert settings.api.port == 9000
    assert settings.api.host == "0.0.0.0"
    assert settings.api.volume_cache_ttl_seconds == 120


def test_pipeline_precip_type_threshold_loads_and_env_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    base = _base_config()
    base["pipeline"]["precip_type_temp_threshold_c"] = 1.5
    _write_config(config_dir, "dev", base)

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    settings = Settings()
    assert settings.pipeline.precip_type_temp_threshold_c == pytest.approx(1.5)

    monkeypatch.setenv("DIGITAL_EARTH_PIPELINE_PRECIP_TYPE_TEMP_THRESHOLD_C", "2.25")
    settings = Settings()
    assert settings.pipeline.precip_type_temp_threshold_c == pytest.approx(2.25)


def test_pipeline_cloud_density_thresholds_load_and_env_overrides(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    base = _base_config()
    base["pipeline"]["cloud_density_rh0"] = 80.0
    base["pipeline"]["cloud_density_rh1"] = 95.0
    _write_config(config_dir, "dev", base)

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    settings = Settings()
    assert settings.pipeline.cloud_density_rh0 == pytest.approx(80.0)
    assert settings.pipeline.cloud_density_rh1 == pytest.approx(95.0)

    monkeypatch.setenv("DIGITAL_EARTH_PIPELINE_CLOUD_DENSITY_RH0", "0.75")
    monkeypatch.setenv("DIGITAL_EARTH_PIPELINE_CLOUD_DENSITY_RH1", "0.9")
    settings = Settings()
    assert settings.pipeline.cloud_density_rh0 == pytest.approx(0.75)
    assert settings.pipeline.cloud_density_rh1 == pytest.approx(0.9)

    monkeypatch.setenv("DIGITAL_EARTH_PIPELINE_CLOUD_DENSITY_RH0", "0.8")
    monkeypatch.setenv("DIGITAL_EARTH_PIPELINE_CLOUD_DENSITY_RH1", "95")
    with pytest.raises(ValueError, match="consistent units"):
        Settings()


def test_cors_origins_parses_string(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    base = _base_config()
    base["api"]["cors_origins"] = ["http://example.com"]
    _write_config(config_dir, "dev", base)

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")
    monkeypatch.setenv(
        "DIGITAL_EARTH_API_CORS_ORIGINS", "http://a.example, http://b.example"
    )

    settings = Settings()
    assert settings.api.cors_origins == ["http://a.example", "http://b.example"]


def test_cors_origins_parses_json_list(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")
    monkeypatch.setenv(
        "DIGITAL_EARTH_API_CORS_ORIGINS", '["http://a.example","http://b.example"]'
    )

    settings = Settings()
    assert settings.api.cors_origins == ["http://a.example", "http://b.example"]


def test_rejects_secrets_in_json(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    base = _base_config()
    base["database"]["password"] = "nope"
    _write_config(config_dir, "dev", base)

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    with pytest.raises(ValueError, match="Secrets must not be stored in config JSON"):
        Settings()


def test_missing_config_file_has_clear_error(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "staging")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    with pytest.raises(FileNotFoundError, match="Config file not found"):
        Settings()


def test_find_config_dir_by_walking_up(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    root = tmp_path / "repo"
    config_dir = root / "config"
    _write_config(config_dir, "dev", _base_config())
    _write_config(config_dir, "staging", _base_config())
    _write_config(config_dir, "prod", _base_config())

    nested = root / "apps" / "api"
    nested.mkdir(parents=True, exist_ok=True)

    monkeypatch.chdir(nested)
    monkeypatch.delenv("DIGITAL_EARTH_CONFIG_DIR", raising=False)
    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")

    settings = Settings()
    assert settings.storage.tiles_bucket == "tiles"


def test_legacy_env_var_names_are_supported(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")
    monkeypatch.setenv("DIGITAL_EARTH_ECMWF_API_KEY", "k")
    monkeypatch.setenv("DIGITAL_EARTH_S3_ACCESS_KEY", "a")
    monkeypatch.setenv("DIGITAL_EARTH_S3_SECRET_KEY", "b")
    monkeypatch.setenv("DIGITAL_EARTH_CESIUM_ION_ACCESS_TOKEN", "t")

    settings = Settings()
    assert settings.pipeline.ecmwf_api_key is not None
    assert settings.pipeline.ecmwf_api_key.get_secret_value() == "k"
    assert settings.storage.access_key_id is not None
    assert settings.storage.access_key_id.get_secret_value() == "a"
    assert settings.web.cesium_ion_access_token is not None
    assert settings.web.cesium_ion_access_token.get_secret_value() == "t"


def test_storage_credentials_must_be_paired(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    config_dir = tmp_path / "config"
    _write_config(config_dir, "dev", _base_config())

    monkeypatch.setenv("DIGITAL_EARTH_ENV", "dev")
    monkeypatch.setenv("DIGITAL_EARTH_CONFIG_DIR", str(config_dir))
    monkeypatch.setenv("DIGITAL_EARTH_DB_USER", "app")
    monkeypatch.setenv("DIGITAL_EARTH_DB_PASSWORD", "secret")
    monkeypatch.setenv("DIGITAL_EARTH_STORAGE_ACCESS_KEY_ID", "only-one")

    with pytest.raises(ValueError, match="must be set together"):
        Settings()
