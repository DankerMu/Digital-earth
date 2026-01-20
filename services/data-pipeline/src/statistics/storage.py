from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Final, Mapping, Optional

import xarray as xr


class StatisticsStorageError(RuntimeError):
    pass


_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.-]+$")


def _validate_segment(value: str, *, name: str) -> str:
    normalized = (value or "").strip()
    if normalized == "":
        raise ValueError(f"{name} must not be empty")
    if "/" in normalized or "\\" in normalized:
        raise ValueError(f"{name} must be a single path segment")
    if normalized in {".", ".."}:
        raise ValueError(f"{name} must not be '.' or '..'")
    if _SEGMENT_RE.fullmatch(normalized) is None:
        raise ValueError(f"{name} contains unsafe characters")
    return normalized


def _utc_now_iso() -> str:
    return datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _ensure_relative_to_base(*, base_dir: Path, path: Path, label: str) -> None:
    if not path.is_relative_to(base_dir):
        raise ValueError(f"{label} escapes output_dir")


@dataclass(frozen=True)
class StatisticsArtifact:
    dataset_path: Path
    metadata_path: Path


class StatisticsStore:
    def __init__(self, root_dir: str | Path) -> None:
        self._root_dir = Path(root_dir).expanduser().resolve()

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def resolve_paths(
        self,
        *,
        source: str,
        variable: str,
        window_kind: str,
        window_key: str,
        version: str,
        filename: str = "statistics.nc",
    ) -> StatisticsArtifact:
        src = _validate_segment(source, name="source")
        var = _validate_segment(variable, name="variable")
        kind = _validate_segment(window_kind, name="window_kind")
        key = _validate_segment(window_key, name="window_key")
        ver = _validate_segment(version, name="version")

        base = self._root_dir
        dir_path = (base / src / var / kind / ver / key).resolve()
        _ensure_relative_to_base(base_dir=base, path=dir_path, label="artifact_dir")
        dir_path.mkdir(parents=True, exist_ok=True)

        name = _validate_segment(filename, name="filename")
        dataset_path = (dir_path / name).resolve()
        _ensure_relative_to_base(base_dir=base, path=dataset_path, label="dataset_path")

        metadata_path = dataset_path.with_suffix(dataset_path.suffix + ".meta.json")
        _ensure_relative_to_base(
            base_dir=base, path=metadata_path, label="metadata_path"
        )

        return StatisticsArtifact(
            dataset_path=dataset_path, metadata_path=metadata_path
        )

    def write_dataset(
        self,
        ds: xr.Dataset,
        *,
        artifact: StatisticsArtifact,
        metadata: Optional[Mapping[str, Any]] = None,
        engine: str = "h5netcdf",
    ) -> StatisticsArtifact:
        payload: dict[str, Any] = {"created_at": _utc_now_iso()}
        if metadata:
            payload.update(dict(metadata))

        try:
            ds.to_netcdf(artifact.dataset_path, engine=engine)
        except Exception as exc:  # noqa: BLE001
            raise StatisticsStorageError(
                f"Failed to write NetCDF: {artifact.dataset_path}"
            ) from exc

        artifact.metadata_path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
        return artifact
