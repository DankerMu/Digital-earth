from __future__ import annotations

from functools import lru_cache
from pathlib import Path
from typing import Any, Literal, Mapping, Optional, Union

import yaml
from pydantic import BaseModel, ConfigDict, Field, ValidationError, model_validator


class MissingSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    strategy: Literal["fill_value", "interpolate"]
    fill_value: Optional[float] = None

    @model_validator(mode="after")
    def _validate_strategy(self) -> "MissingSpec":
        if self.strategy == "fill_value" and self.fill_value is None:
            raise ValueError("missing.fill_value is required when strategy=fill_value")
        if self.strategy == "interpolate" and self.fill_value is not None:
            raise ValueError(
                "missing.fill_value must be omitted when strategy=interpolate"
            )
        return self


class DefaultsSpec(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scale: float = 1.0
    offset: float = 0.0
    missing: MissingSpec = Field(
        default_factory=lambda: MissingSpec(strategy="fill_value", fill_value=-9999.0)
    )


class VariableMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_var: str
    internal_var: str
    unit: str
    scale: Optional[float] = None
    offset: Optional[float] = None
    missing: Optional[MissingSpec] = None


class ResolutionMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    variables: list[VariableMapping] = Field(default_factory=list)

    def by_source_var(self) -> dict[str, VariableMapping]:
        return {mapping.source_var: mapping for mapping in self.variables}


class ProductMapping(BaseModel):
    model_config = ConfigDict(extra="forbid")

    resolutions: dict[str, ResolutionMapping] = Field(default_factory=dict)


class CldasMappingConfig(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    defaults: DefaultsSpec = Field(default_factory=DefaultsSpec)
    products: dict[str, ProductMapping] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _validate_and_apply_defaults(self) -> "CldasMappingConfig":
        if self.schema_version != 1:
            raise ValueError(f"Unsupported schema_version={self.schema_version}")

        default_scale = self.defaults.scale
        default_offset = self.defaults.offset
        default_missing = self.defaults.missing

        for product in self.products.values():
            for resolution in product.resolutions.values():
                seen_source: set[str] = set()
                seen_internal: set[str] = set()
                for mapping in resolution.variables:
                    if mapping.scale is None:
                        mapping.scale = default_scale
                    if mapping.offset is None:
                        mapping.offset = default_offset
                    if mapping.missing is None:
                        mapping.missing = default_missing.model_copy(deep=True)

                    if mapping.source_var in seen_source:
                        raise ValueError(
                            f"Duplicate source_var={mapping.source_var!r} within the same resolution"
                        )
                    if mapping.internal_var in seen_internal:
                        raise ValueError(
                            f"Duplicate internal_var={mapping.internal_var!r} within the same resolution"
                        )
                    seen_source.add(mapping.source_var)
                    seen_internal.add(mapping.internal_var)

        return self

    def variables_for(
        self, *, product: str, resolution: str
    ) -> dict[str, VariableMapping]:
        try:
            product_mapping = self.products[product]
        except KeyError as exc:
            raise KeyError(f"Unknown product: {product!r}") from exc

        try:
            resolution_mapping = product_mapping.resolutions[resolution]
        except KeyError as exc:
            raise KeyError(
                f"Unknown resolution: {resolution!r} for product={product!r}"
            ) from exc

        return resolution_mapping.by_source_var()


DEFAULT_CLDAS_MAPPING_PATH = (
    Path(__file__).resolve().parents[2] / "config" / "cldas_mapping.yaml"
)


def _canonical_path(path: Union[str, Path, None]) -> Path:
    if path is None:
        path = DEFAULT_CLDAS_MAPPING_PATH
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = (Path.cwd() / candidate).resolve()
    else:
        candidate = candidate.resolve()
    return candidate


def _load_yaml(path: Path) -> Mapping[str, Any]:
    try:
        content = path.read_text(encoding="utf-8")
    except FileNotFoundError as exc:
        raise FileNotFoundError(f"CLDAS mapping config not found: {path}") from exc

    try:
        data = yaml.safe_load(content)
    except yaml.YAMLError as exc:
        raise ValueError(f"Invalid YAML in {path}: {exc}") from exc

    if not isinstance(data, Mapping):
        raise ValueError(f"CLDAS mapping config must be a mapping at top-level: {path}")
    return data


class CldasMappingLoader:
    def __init__(self, path: Union[str, Path, None] = None) -> None:
        self._path = _canonical_path(path)
        self._cached_config: Optional[CldasMappingConfig] = None
        self._cached_mtime_ns: Optional[int] = None

    @property
    def path(self) -> Path:
        return self._path

    def load(self) -> CldasMappingConfig:
        data = _load_yaml(self._path)
        try:
            config = CldasMappingConfig.model_validate(data)
        except ValidationError as exc:
            raise ValueError(
                f"Invalid CLDAS mapping config in {self._path}: {exc}"
            ) from exc

        self._cached_config = config
        self._cached_mtime_ns = self._path.stat().st_mtime_ns
        return config

    def reload(self) -> CldasMappingConfig:
        return self.load()

    def get(self, *, reload: bool = False) -> CldasMappingConfig:
        if reload or self._cached_config is None:
            return self.load()

        current_mtime_ns = self._path.stat().st_mtime_ns
        if self._cached_mtime_ns != current_mtime_ns:
            return self.load()
        return self._cached_config


@lru_cache(maxsize=None)
def _get_loader_for_path(path_str: str) -> CldasMappingLoader:
    return CldasMappingLoader(path_str)


def get_cldas_mapping_loader(path: Union[str, Path, None] = None) -> CldasMappingLoader:
    return _get_loader_for_path(str(_canonical_path(path)))


def get_cldas_mapping_config(*, reload: bool = False) -> CldasMappingConfig:
    return get_cldas_mapping_loader().get(reload=reload)
