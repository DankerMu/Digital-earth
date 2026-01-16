from __future__ import annotations

import hashlib
import os
from dataclasses import dataclass
from functools import lru_cache
from pathlib import Path
from typing import Optional, Union

from pydantic import ValidationError

from schemas.effect_preset import DEFAULT_EFFECT_PRESETS_CONFIG_PATH, EffectPreset
from schemas.effect_preset import EffectType
from schemas.effect_preset import load_effect_presets

DEFAULT_EFFECT_PRESETS_CONFIG_ENV: str = "DIGITAL_EARTH_EFFECT_PRESETS_CONFIG"


class EffectPresetItem(EffectPreset):
    id: str


@dataclass(frozen=True)
class EffectPresetsPayload:
    etag: str
    presets: tuple[EffectPresetItem, ...]


def _resolve_config_path(path: Optional[Union[str, Path]]) -> Path:
    if path is not None:
        candidate = Path(path).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    explicit = os.environ.get(DEFAULT_EFFECT_PRESETS_CONFIG_ENV)
    if explicit:
        candidate = Path(explicit).expanduser()
        if not candidate.is_absolute():
            candidate = (Path.cwd() / candidate).resolve()
        return candidate

    return DEFAULT_EFFECT_PRESETS_CONFIG_PATH


@lru_cache(maxsize=4)
def _get_effect_presets_payload_cached(
    path: str, mtime_ns: int, size: int
) -> EffectPresetsPayload:
    config_path = Path(path)
    if not config_path.is_file():
        raise FileNotFoundError(f"Effect presets config file not found: {config_path}")

    raw_bytes = config_path.read_bytes()
    etag = f"\"sha256-{hashlib.sha256(raw_bytes).hexdigest()}\""

    try:
        parsed = load_effect_presets(config_path)
    except ValidationError as exc:
        raise ValueError(f"Invalid effect presets config: {config_path}") from exc

    items: list[EffectPresetItem] = []
    for preset_id in sorted(parsed.presets):
        preset = parsed.presets[preset_id]
        payload = preset.model_dump(exclude={"risk_level"})
        payload["id"] = preset_id
        items.append(EffectPresetItem.model_validate(payload))

    return EffectPresetsPayload(etag=etag, presets=tuple(items))


def get_effect_presets_payload(
    path: Optional[Union[str, Path]] = None,
) -> EffectPresetsPayload:
    resolved = _resolve_config_path(path)
    if not resolved.is_file():
        raise FileNotFoundError(f"Effect presets config file not found: {resolved}")
    stat = resolved.stat()
    return _get_effect_presets_payload_cached(
        str(resolved), stat.st_mtime_ns, stat.st_size
    )


get_effect_presets_payload.cache_clear = _get_effect_presets_payload_cached.cache_clear  # type: ignore[attr-defined]
