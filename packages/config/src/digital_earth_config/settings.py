from __future__ import annotations

import json
import math
import os
from copy import deepcopy
from pathlib import Path
from typing import Any, Mapping, Optional, Type

from pydantic import BaseModel, Field, SecretStr, field_validator, model_validator
from pydantic_settings import BaseSettings, SettingsConfigDict
from pydantic_settings.sources import PydanticBaseSettingsSource

_DIGITAL_EARTH_PREFIX = "DIGITAL_EARTH_"


def _canonical_env(value: Optional[str]) -> str:
    if value is None or value.strip() == "":
        return "dev"

    normalized = value.strip().lower()
    aliases = {
        "dev": "dev",
        "development": "dev",
        "staging": "staging",
        "stage": "staging",
        "prod": "prod",
        "production": "prod",
    }
    if normalized in aliases:
        return aliases[normalized]
    raise ValueError(
        f"Invalid DIGITAL_EARTH_ENV={value!r}; expected one of: dev, staging, prod"
    )


def _deep_update(base: dict[str, Any], updates: Mapping[str, Any]) -> dict[str, Any]:
    for key, value in updates.items():
        if (
            key in base
            and isinstance(base[key], dict)
            and isinstance(value, Mapping)
            and isinstance(value, dict)
        ):
            _deep_update(base[key], value)
        else:
            base[key] = value
    return base


def _resolve_config_dir(environ: Optional[Mapping[str, str]] = None) -> Path:
    environ = environ or os.environ
    explicit = environ.get(f"{_DIGITAL_EARTH_PREFIX}CONFIG_DIR")
    if explicit:
        explicit_path = Path(explicit).expanduser()
        if not explicit_path.is_absolute():
            explicit_path = (Path.cwd() / explicit_path).resolve()
        return explicit_path

    cwd = Path.cwd()
    for candidate_root in (cwd, *cwd.parents):
        config_dir = candidate_root / "config"
        if (
            (config_dir / "dev.json").is_file()
            and (config_dir / "staging.json").is_file()
            and (config_dir / "prod.json").is_file()
        ):
            return config_dir

    return cwd / "config"


def _validate_no_secrets_in_json(data: Any, *, source: Optional[Path] = None) -> None:
    if not isinstance(data, dict):
        raise ValueError(
            f"Config JSON must be an object at top-level{f' ({source})' if source else ''}"
        )

    forbidden_paths = {
        ("database", "user"),
        ("database", "password"),
        ("redis", "password"),
        ("pipeline", "ecmwf_api_key"),
        ("web", "cesium_ion_access_token"),
        ("storage", "access_key_id"),
        ("storage", "secret_access_key"),
    }

    present: list[str] = []
    for path in forbidden_paths:
        cursor: Any = data
        for key in path:
            if not isinstance(cursor, dict) or key not in cursor:
                cursor = None
                break
            cursor = cursor[key]
        if cursor is not None:
            present.append(".".join(path))

    if present:
        location = f" in {source}" if source else ""
        raise ValueError(
            "Secrets must not be stored in config JSON"
            f"{location}: {', '.join(sorted(present))}"
        )


def _env_overrides(environ: Mapping[str, str]) -> dict[str, Any]:
    category_to_section = {
        "API": "api",
        "PIPELINE": "pipeline",
        "WEB": "web",
        "DB": "database",
        "DATABASE": "database",
        "REDIS": "redis",
        "STORAGE": "storage",
        "S3": "storage",
    }

    legacy_map = {
        "ECMWF_API_KEY": ("pipeline", "ecmwf_api_key"),
        "CESIUM_ION_ACCESS_TOKEN": ("web", "cesium_ion_access_token"),
        "S3_ACCESS_KEY": ("storage", "access_key_id"),
        "S3_SECRET_KEY": ("storage", "secret_access_key"),
    }

    result: dict[str, Any] = {}
    for key, value in environ.items():
        if not key.startswith(_DIGITAL_EARTH_PREFIX):
            continue
        suffix = key[len(_DIGITAL_EARTH_PREFIX) :]
        if suffix in {"ENV", "CONFIG_DIR"}:
            continue

        if suffix in legacy_map:
            section, field_name = legacy_map[suffix]
            result.setdefault(section, {})[field_name] = value
            continue

        if "_" not in suffix:
            continue
        category, rest = suffix.split("_", 1)
        section = category_to_section.get(category)
        if section is None:
            continue
        field_name = rest.lower()
        result.setdefault(section, {})[field_name] = value

    return result


class DatabaseSettings(BaseModel):
    host: str
    port: int = 5432
    name: str
    user: Optional[str] = Field(default=None, repr=False)
    password: Optional[SecretStr] = Field(default=None, repr=False)

    @model_validator(mode="after")
    def _require_credentials(self) -> "DatabaseSettings":
        if self.user is None or self.user.strip() == "":
            raise ValueError("DIGITAL_EARTH_DB_USER is required")
        if self.password is None or self.password.get_secret_value().strip() == "":
            raise ValueError("DIGITAL_EARTH_DB_PASSWORD is required")
        return self

    @property
    def dsn(self) -> str:
        if self.user is None or self.password is None:
            raise ValueError("Database credentials are required to build DSN")
        return (
            "postgresql://"
            f"{self.user}:{self.password.get_secret_value()}@{self.host}:{self.port}/{self.name}"
        )


class RedisSettings(BaseModel):
    host: str
    port: int = 6379
    password: Optional[SecretStr] = Field(default=None, repr=False)

    @model_validator(mode="after")
    def _reject_empty_password(self) -> "RedisSettings":
        if self.password is not None and self.password.get_secret_value().strip() == "":
            raise ValueError("DIGITAL_EARTH_REDIS_PASSWORD must not be empty")
        return self

    @property
    def url(self) -> str:
        if self.password is None:
            return f"redis://{self.host}:{self.port}/0"
        return f"redis://:{self.password.get_secret_value()}@{self.host}:{self.port}/0"


class ApiRateLimitRule(BaseModel):
    path_prefix: str
    requests_per_minute: int
    window_seconds: int = 60

    @field_validator("path_prefix")
    @classmethod
    def _normalize_path_prefix(cls, value: str) -> str:
        normalized = (value or "").strip()
        if not normalized.startswith("/"):
            normalized = "/" + normalized
        return normalized.rstrip("/") or "/"

    @model_validator(mode="after")
    def _validate_values(self) -> "ApiRateLimitRule":
        if self.requests_per_minute <= 0:
            raise ValueError("requests_per_minute must be > 0")
        if self.window_seconds <= 0:
            raise ValueError("window_seconds must be > 0")
        return self


def _default_api_rate_limit_rules() -> list[ApiRateLimitRule]:
    return [
        ApiRateLimitRule(path_prefix="/api/v1/catalog", requests_per_minute=100),
        ApiRateLimitRule(path_prefix="/api/v1/vector", requests_per_minute=60),
        ApiRateLimitRule(path_prefix="/api/v1/tiles", requests_per_minute=300),
        ApiRateLimitRule(path_prefix="/api/v1/volume", requests_per_minute=10),
        ApiRateLimitRule(path_prefix="/api/v1/errors", requests_per_minute=10),
    ]


class ApiRateLimitSettings(BaseModel):
    enabled: bool = True
    trust_proxy_headers: bool = True
    trusted_proxies: list[str] = Field(
        default_factory=lambda: [
            "127.0.0.0/8",
            "10.0.0.0/8",
            "172.16.0.0/12",
            "192.168.0.0/16",
        ]
    )
    ip_allowlist: list[str] = Field(default_factory=list)
    ip_blocklist: list[str] = Field(default_factory=list)
    rules: list[ApiRateLimitRule] = Field(default_factory=_default_api_rate_limit_rules)


class ApiEffectTriggerLoggingSettings(BaseModel):
    enabled: bool = True
    sample_rate: float = Field(
        default=0.1,
        ge=0.0,
        le=1.0,
        description="Probability of persisting a received effect trigger event.",
    )
    max_events_per_request: int = Field(
        default=100, ge=1, le=1000, description="Maximum events accepted per request."
    )


class ApiSettings(BaseModel):
    host: str
    port: int
    debug: bool = False
    cors_origins: list[str] = Field(default_factory=list)
    volume_cache_ttl_seconds: int = Field(
        default=3600,
        ge=0,
        description="TTL for cached /api/v1/volume responses stored in Redis.",
    )
    rate_limit: ApiRateLimitSettings = Field(default_factory=ApiRateLimitSettings)
    effect_trigger_logging: ApiEffectTriggerLoggingSettings = Field(
        default_factory=ApiEffectTriggerLoggingSettings
    )

    @field_validator("cors_origins", mode="before")
    @classmethod
    def _parse_cors_origins(cls, value: Any) -> Any:
        if isinstance(value, str):
            stripped = value.strip()
            if stripped == "":
                return []
            if stripped.startswith("["):
                return json.loads(stripped)
            return [item.strip() for item in stripped.split(",") if item.strip()]
        return value


class PipelineSettings(BaseModel):
    workers: int
    batch_size: int
    ecmwf_api_key: Optional[SecretStr] = Field(default=None, repr=False)
    data_source: str = Field(default="remote", description="remote|local")
    precip_type_temp_threshold_c: float = Field(
        default=0.0,
        description="Temperature threshold (°C) used as a fallback for precipitation type; below => snow.",
    )
    cloud_density_rh0: float = Field(
        default=0.8,
        ge=0.0,
        le=100.0,
        description=(
            "Lower RH threshold for cloud density smoothstep. "
            "Accepts either fraction [0, 1] or percent [0, 100]."
        ),
    )
    cloud_density_rh1: float = Field(
        default=0.95,
        ge=0.0,
        le=100.0,
        description=(
            "Upper RH threshold for cloud density smoothstep. "
            "Accepts either fraction [0, 1] or percent [0, 100]."
        ),
    )

    @model_validator(mode="after")
    def _reject_empty_ecmwf_key(self) -> "PipelineSettings":
        if (
            self.ecmwf_api_key is not None
            and self.ecmwf_api_key.get_secret_value().strip() == ""
        ):
            raise ValueError("DIGITAL_EARTH_PIPELINE_ECMWF_API_KEY must not be empty")
        normalized = (self.data_source or "").strip().lower()
        if normalized == "":
            normalized = "remote"
        if normalized not in {"remote", "local"}:
            raise ValueError("pipeline.data_source must be either 'remote' or 'local'")
        self.data_source = normalized

        rh0 = float(self.cloud_density_rh0)
        rh1 = float(self.cloud_density_rh1)
        if not (math.isfinite(rh0) and math.isfinite(rh1)):
            raise ValueError("pipeline.cloud_density_rh0/rh1 must be finite numbers")
        if (rh0 > 1.0) != (rh1 > 1.0):
            raise ValueError(
                "pipeline.cloud_density_rh0 and pipeline.cloud_density_rh1 must use "
                "consistent units (both fraction ≤ 1 or both percent > 1)"
            )
        if rh0 >= rh1:
            raise ValueError(
                "pipeline.cloud_density_rh0 must be < pipeline.cloud_density_rh1"
            )
        if rh0 <= 1.0 and rh1 <= 1.0 and (rh0 < 0.0 or rh1 > 1.0):
            raise ValueError(
                "pipeline.cloud_density_rh0/rh1 fraction must be within [0, 1]"
            )
        if rh0 > 1.0 and rh1 > 1.0 and (rh0 < 0.0 or rh1 > 100.0):
            raise ValueError(
                "pipeline.cloud_density_rh0/rh1 percent must be within [0, 100]"
            )
        return self


class WebSettings(BaseModel):
    api_base_url: str
    cesium_ion_access_token: Optional[SecretStr] = Field(default=None, repr=False)

    @model_validator(mode="after")
    def _reject_empty_cesium_token(self) -> "WebSettings":
        if (
            self.cesium_ion_access_token is not None
            and self.cesium_ion_access_token.get_secret_value().strip() == ""
        ):
            raise ValueError(
                "DIGITAL_EARTH_WEB_CESIUM_ION_ACCESS_TOKEN must not be empty"
            )
        return self


class StorageSettings(BaseModel):
    tiles_bucket: str
    raw_bucket: str
    endpoint_url: Optional[str] = None
    region_name: Optional[str] = None
    tiles_base_url: Optional[str] = None
    tiles_dir: Optional[Path] = None
    access_key_id: Optional[SecretStr] = Field(default=None, repr=False)
    secret_access_key: Optional[SecretStr] = Field(default=None, repr=False)

    @model_validator(mode="after")
    def _validate_credentials_pair(self) -> "StorageSettings":
        access = (
            self.access_key_id.get_secret_value().strip() if self.access_key_id else ""
        )
        secret = (
            self.secret_access_key.get_secret_value().strip()
            if self.secret_access_key
            else ""
        )

        if (access and not secret) or (secret and not access):
            raise ValueError(
                "Both DIGITAL_EARTH_STORAGE_ACCESS_KEY_ID and "
                "DIGITAL_EARTH_STORAGE_SECRET_ACCESS_KEY must be set together"
            )
        if self.access_key_id is not None and access == "":
            raise ValueError("DIGITAL_EARTH_STORAGE_ACCESS_KEY_ID must not be empty")
        if self.secret_access_key is not None and secret == "":
            raise ValueError(
                "DIGITAL_EARTH_STORAGE_SECRET_ACCESS_KEY must not be empty"
            )
        return self


class _DigitalEarthSettingsSource:
    def __call__(self) -> dict[str, Any]:
        environ = os.environ
        env = _canonical_env(environ.get(f"{_DIGITAL_EARTH_PREFIX}ENV"))
        config_dir = _resolve_config_dir(environ)
        config_path = config_dir / f"{env}.json"
        if not config_path.is_file():
            raise FileNotFoundError(
                f"Config file not found: {config_path} (DIGITAL_EARTH_ENV={env!r}, "
                f"DIGITAL_EARTH_CONFIG_DIR={str(config_dir)!r})"
            )

        raw = json.loads(config_path.read_text(encoding="utf-8"))
        _validate_no_secrets_in_json(raw, source=config_path)

        merged = deepcopy(raw)
        overrides = _env_overrides(environ)
        _deep_update(merged, overrides)
        return merged


class Settings(BaseSettings):
    api: ApiSettings
    pipeline: PipelineSettings
    web: WebSettings
    database: DatabaseSettings
    redis: RedisSettings
    storage: StorageSettings

    model_config = SettingsConfigDict(extra="forbid")

    @classmethod
    def settings_customise_sources(
        cls,
        settings_cls: Type[BaseSettings],
        init_settings: PydanticBaseSettingsSource,
        env_settings: PydanticBaseSettingsSource,
        dotenv_settings: PydanticBaseSettingsSource,
        file_secret_settings: PydanticBaseSettingsSource,
    ) -> tuple[PydanticBaseSettingsSource, ...]:
        return (init_settings, _DigitalEarthSettingsSource())
