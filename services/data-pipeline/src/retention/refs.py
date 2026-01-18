from __future__ import annotations

import json
from pathlib import Path
from typing import Any, Mapping

import yaml


def _as_str_set(value: Any) -> set[str]:
    if value is None:
        return set()
    if isinstance(value, str):
        normalized = value.strip()
        return {normalized} if normalized else set()
    if isinstance(value, (list, tuple, set)):
        result: set[str] = set()
        for item in value:
            if not isinstance(item, str):
                continue
            normalized = item.strip()
            if normalized:
                result.add(normalized)
        return result
    return set()


def _load_mapping(path: Path) -> Mapping[str, Any]:
    raw = path.read_text(encoding="utf-8")
    suffix = path.suffix.lower()
    if suffix in {".yaml", ".yml"}:
        data = yaml.safe_load(raw)
    else:
        data = json.loads(raw)

    if data is None:
        return {}
    if not isinstance(data, Mapping):
        raise ValueError("references file must be a mapping")
    return data


def load_tiles_references(path: Path) -> dict[str, set[str]]:
    """
    Load tiles references ("pinned" versions) from a YAML/JSON file.

    Supported formats:
      1) {schema_version: 1, layers: {<layer>: [<version>, ...], ...}}
      2) {<layer>: [<version>, ...], ...}
      3) {schema_version: 1, references: [{layer: ..., version: ...}, ...]}
    """
    if not path.exists():
        return {}

    data = _load_mapping(path)

    if "layers" in data and isinstance(data["layers"], Mapping):
        layers = data["layers"]
    else:
        layers = data

    out: dict[str, set[str]] = {}
    if isinstance(layers, Mapping):
        for layer, versions in layers.items():
            if not isinstance(layer, str):
                continue
            normalized_layer = layer.strip()
            if normalized_layer == "":
                continue
            out[normalized_layer] = _as_str_set(versions)

    refs = data.get("references")
    if isinstance(refs, list):
        for item in refs:
            if not isinstance(item, Mapping):
                continue
            layer = item.get("layer")
            version = item.get("version")
            if not isinstance(layer, str) or not isinstance(version, str):
                continue
            normalized_layer = layer.strip()
            normalized_version = version.strip()
            if normalized_layer == "" or normalized_version == "":
                continue
            out.setdefault(normalized_layer, set()).add(normalized_version)

    out = {layer: versions for layer, versions in out.items() if versions}
    return out

