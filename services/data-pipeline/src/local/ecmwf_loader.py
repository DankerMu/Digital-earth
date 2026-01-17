from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union


class EcmwfLocalLoadError(RuntimeError):
    pass


@dataclass(frozen=True)
class EcmwfFileSummary:
    path: Path
    size: int


def summarize_ecmwf_grib(source_path: Union[str, Path]) -> EcmwfFileSummary:
    path = Path(source_path)
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise EcmwfLocalLoadError(f"ECMWF GRIB file not found: {path}") from exc
    return EcmwfFileSummary(path=path.resolve(), size=int(stat.st_size))


def read_ecmwf_grib_bytes(
    source_path: Union[str, Path], *, max_bytes: Optional[int] = None
) -> bytes:
    path = Path(source_path)
    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise EcmwfLocalLoadError(f"ECMWF GRIB file not found: {path}") from exc
    if max_bytes is not None and int(stat.st_size) > max_bytes:
        raise EcmwfLocalLoadError(
            f"ECMWF GRIB file too large to read into memory: {path}"
        )
    try:
        return path.read_bytes()
    except FileNotFoundError as exc:
        raise EcmwfLocalLoadError(f"ECMWF GRIB file not found: {path}") from exc
