from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Iterable, Iterator, Literal, Optional

from digital_earth_config.local_data import LocalDataPaths

LocalDataKind = Literal["cldas", "ecmwf", "town_forecast"]


@dataclass(frozen=True)
class DiscoveredFile:
    kind: LocalDataKind
    path: Path


def _iter_files(root: Path, *, patterns: Iterable[str]) -> Iterator[Path]:
    if not root.exists():
        return
    if not root.is_dir():
        return
    for pattern in patterns:
        yield from root.rglob(pattern)


def discover_local_files(
    paths: LocalDataPaths,
    *,
    kinds: Optional[set[LocalDataKind]] = None,
) -> list[DiscoveredFile]:
    selected = kinds or {"cldas", "ecmwf", "town_forecast"}

    discovered: list[DiscoveredFile] = []

    if "cldas" in selected:
        for path in _iter_files(paths.cldas_dir, patterns=("*.nc", "*.NC")):
            discovered.append(DiscoveredFile(kind="cldas", path=path))

    if "ecmwf" in selected:
        for path in _iter_files(
            paths.ecmwf_dir, patterns=("*.grib", "*.grib2", "*.GRIB", "*.GRIB2")
        ):
            discovered.append(DiscoveredFile(kind="ecmwf", path=path))

    if "town_forecast" in selected:
        for path in _iter_files(paths.town_forecast_dir, patterns=("*.TXT", "*.txt")):
            discovered.append(DiscoveredFile(kind="town_forecast", path=path))

    discovered.sort(key=lambda item: (item.kind, str(item.path)))
    return discovered
