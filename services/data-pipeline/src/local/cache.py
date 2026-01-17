from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Optional

from digital_earth_config.local_data import LocalDataPaths

from .indexer import LocalFileIndex, build_local_file_index
from .scanner import discover_local_files

DEFAULT_CACHE_PATH = Path(".cache/local-data-index.json")


def _load_index(path: Path) -> Optional[LocalFileIndex]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return LocalFileIndex.model_validate(data)
    except Exception:  # noqa: BLE001
        return None


def _is_cache_valid(index: LocalFileIndex) -> bool:
    root = Path(index.root_dir)
    for item in index.items:
        path = Path(item.path)
        if not path.is_file():
            return False
        try:
            stat = path.stat()
        except FileNotFoundError:
            return False
        if int(stat.st_mtime_ns) != item.mtime_ns or int(stat.st_size) != item.size:
            return False
        try:
            _ = path.resolve().relative_to(root.resolve())
        except ValueError:
            return False
    return True


def _parse_cache_time(value: str) -> Optional[datetime]:
    if not isinstance(value, str):
        return None
    text = value.strip()
    if not text:
        return None
    if text.endswith("Z"):
        text = text[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _is_cache_fresh(index: LocalFileIndex, *, ttl_seconds: int) -> bool:
    if ttl_seconds <= 0:
        return False
    generated_at = _parse_cache_time(index.generated_at)
    if generated_at is None:
        return False
    now = datetime.now(timezone.utc)
    return now - generated_at <= timedelta(seconds=ttl_seconds)


def save_local_file_index(path: Path, index: LocalFileIndex) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    payload = index.model_dump()
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n", encoding="utf-8"
    )


def get_local_file_index(
    paths: LocalDataPaths,
    *,
    cache_path: Path = DEFAULT_CACHE_PATH,
) -> LocalFileIndex:
    cache_path = cache_path
    cached = _load_index(cache_path)
    if cached is not None and cached.root_dir == str(paths.root_dir.resolve()):
        if _is_cache_fresh(cached, ttl_seconds=paths.index_cache_ttl_seconds):
            if _is_cache_valid(cached):
                return cached

    discovered = [(item.kind, item.path) for item in discover_local_files(paths)]
    index = build_local_file_index(discovered, root_dir=paths.root_dir)
    save_local_file_index(cache_path, index)
    return index
