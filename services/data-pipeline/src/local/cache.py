from __future__ import annotations

import json
from pathlib import Path
from typing import Optional

from digital_earth_config.local_data import LocalDataPaths

from .indexer import LocalFileIndex, LocalDataKind, build_local_file_index
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
    refresh: bool = False,
    kinds: Optional[set[LocalDataKind]] = None,
) -> LocalFileIndex:
    cache_path = cache_path
    if not refresh:
        cached = _load_index(cache_path)
        if cached is not None and cached.root_dir == str(paths.root_dir.resolve()):
            if _is_cache_valid(cached):
                return cached

    discovered = [
        (item.kind, item.path) for item in discover_local_files(paths, kinds=kinds)
    ]
    index = build_local_file_index(discovered, root_dir=paths.root_dir)
    save_local_file_index(cache_path, index)
    return index
