from __future__ import annotations

import json
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Optional

import numpy as np
import xarray as xr

from datacube.storage import write_datacube
from derived.cloud_density import CloudDensityThresholds, derive_cloud_density_from_rh


class CloudDensityExportError(RuntimeError):
    pass


DEFAULT_CLOUD_DENSITY_LAYER: Final[str] = "ecmwf/cloud_density"

_LAYER_SEGMENT_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_]+$")
_TIME_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9TZ-]+$")
_LEVEL_KEY_RE: Final[re.Pattern[str]] = re.compile(r"^[A-Za-z0-9_.-]+$")

_SURFACE_LEVEL_ALIASES: Final[set[str]] = {"sfc", "surface"}


def _validate_layer(value: str) -> str:
    normalized = (value or "").strip().strip("/")
    if normalized == "":
        raise ValueError("layer must not be empty")

    segments = normalized.split("/")
    invalid_segments = [
        segment
        for segment in segments
        if not segment or _LAYER_SEGMENT_RE.fullmatch(segment) is None
    ]
    if invalid_segments:
        raise ValueError("layer contains unsafe characters")
    return "/".join(segments)


def _validate_time_key(value: str) -> str:
    normalized = (value or "").strip()
    if normalized == "":
        raise ValueError("time_key must not be empty")
    if _TIME_KEY_RE.fullmatch(normalized) is None:
        raise ValueError("time_key contains unsafe characters")
    return normalized


def _validate_level_key(value: str) -> str:
    normalized = (value or "").strip()
    if normalized == "":
        raise ValueError("level_key must not be empty")
    if _LEVEL_KEY_RE.fullmatch(normalized) is None:
        raise ValueError("level_key contains unsafe characters")
    return normalized


def _ensure_relative_to_base(*, base_dir: Path, path: Path, label: str) -> None:
    if not path.is_relative_to(base_dir):
        raise ValueError(f"{label} escapes output_dir")


def _normalize_time_key(dt: datetime) -> str:
    return dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _parse_time(value: object) -> datetime:
    if isinstance(value, np.datetime64):
        # DataCube stores time as UTC-naive datetime64; treat as UTC.
        text = np.datetime_as_string(value.astype("datetime64[s]"), unit="s")
        return datetime.fromisoformat(text).replace(tzinfo=timezone.utc)

    if isinstance(value, datetime):
        dt = value
        if dt.tzinfo is None:
            return dt.replace(tzinfo=timezone.utc)
        return dt.astimezone(timezone.utc)

    raw = str(value or "").strip()
    if raw == "":
        raise ValueError("valid_time must not be empty")

    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(timezone.utc)
    except ValueError:
        try:
            return datetime.strptime(raw, "%Y%m%dT%H%M%SZ").replace(tzinfo=timezone.utc)
        except ValueError as exc:
            raise ValueError("valid_time must be an ISO8601 timestamp") from exc


def _resolve_time_index(ds: xr.Dataset, valid_time: object | None) -> tuple[int, str]:
    if "time" not in ds.coords:
        raise CloudDensityExportError("Dataset missing required coordinate: time")

    values = np.asarray(ds["time"].values)
    if values.size == 0:
        raise CloudDensityExportError("time coordinate is empty")

    dt = _parse_time(values[0] if valid_time is None else valid_time)
    key = _validate_time_key(_normalize_time_key(dt))

    target = np.datetime64(dt.strftime("%Y-%m-%dT%H:%M:%S"))
    matches = np.where(values.astype("datetime64[s]") == target)[0]
    if matches.size == 0:
        sample = [_normalize_time_key(_parse_time(item)) for item in values[:3]]
        raise CloudDensityExportError(
            f"valid_time not found in dataset: {dt.isoformat()} (sample={sample})"
        )
    return int(matches[0]), key


def _level_key(value: object) -> str:
    if isinstance(value, str):
        normalized = value.strip().lower()
        if normalized in _SURFACE_LEVEL_ALIASES:
            return "sfc"
        return _validate_level_key(normalized)

    if isinstance(value, (int, float, np.number)):
        numeric = float(value)
        if not np.isfinite(numeric):
            raise CloudDensityExportError("level coordinate contains non-finite values")
        if abs(numeric - round(numeric)) < 1e-6:
            return _validate_level_key(str(int(round(numeric))))
        return _validate_level_key(str(numeric))

    return _validate_level_key(str(value))


@dataclass(frozen=True)
class CloudDensityExportResult:
    layer: str
    time: str
    rh0: float
    rh1: float
    levels: tuple[str, ...]
    files: tuple[Path, ...]
    manifest: Optional[Path] = None


def export_cloud_density_slices(
    ds: xr.Dataset,
    output_dir: str | Path,
    *,
    valid_time: object | None = None,
    layer: str = DEFAULT_CLOUD_DENSITY_LAYER,
    rh_variable: str | None = None,
    rh0: float | None = None,
    rh1: float | None = None,
    output_format: str = "netcdf",
    write_manifest: bool = True,
) -> CloudDensityExportResult:
    """Export per-pressure-level cloud density files for Volume API.

    Output layout:
      <output_dir>/<layer>/<time_key>/<level_key>.nc  (or .zarr)
    """

    if output_format not in {"netcdf", "zarr"}:
        raise ValueError("output_format must be either 'netcdf' or 'zarr'")

    thresholds = CloudDensityThresholds.resolve(rh0=rh0, rh1=rh1)
    layer_norm = _validate_layer(layer)

    if "level" not in ds.coords:
        raise CloudDensityExportError("Dataset missing required coordinate: level")
    levels = np.asarray(ds["level"].values)
    if levels.size == 0:
        raise CloudDensityExportError("level coordinate is empty")

    time_index, time_key = _resolve_time_index(ds, valid_time)

    base = Path(output_dir).resolve()
    layer_dir = (base / layer_norm).resolve()
    _ensure_relative_to_base(base_dir=base, path=layer_dir, label="layer")
    time_dir = (layer_dir / time_key).resolve()
    _ensure_relative_to_base(base_dir=base, path=time_dir, label="time_key")
    time_dir.mkdir(parents=True, exist_ok=True)

    if rh_variable is None:
        # Late import so volume exporter doesn't own RH var inference logic.
        from derived.cloud_density import resolve_rh_variable_name

        rh_variable = resolve_rh_variable_name(ds)

    if rh_variable not in ds.data_vars:
        raise CloudDensityExportError(
            f"RH variable {rh_variable!r} not found; available={list(ds.data_vars)}"
        )
    rh = ds[rh_variable]
    required_dims = {"time", "level", "lat", "lon"}
    if not required_dims.issubset(set(rh.dims)):
        raise CloudDensityExportError(
            f"RH variable missing required dims={sorted(required_dims)}; got dims={list(rh.dims)}"
        )

    files: list[Path] = []
    level_keys: list[str] = []
    ext = "nc" if output_format == "netcdf" else "zarr"
    for level_index, level_value in enumerate(levels.tolist()):
        level_key = _level_key(level_value)
        level_keys.append(level_key)

        target = (time_dir / f"{level_key}.{ext}").resolve()
        _ensure_relative_to_base(base_dir=base, path=target, label="slice")

        rh_slice = rh.isel(time=[int(time_index)], level=[int(level_index)])
        density = derive_cloud_density_from_rh(rh_slice, thresholds=thresholds)
        out = xr.Dataset({"cloud_density": density})
        out.attrs = {
            "schema": "digital-earth.volume-slice",
            "schema_version": 1,
            "variable": "cloud_density",
            "source_variable": str(rh_variable),
            "rh0": float(thresholds.rh0),
            "rh1": float(thresholds.rh1),
        }
        write_datacube(out, target, format=output_format)
        files.append(target)

    manifest_path: Optional[Path] = None
    if write_manifest:
        manifest_path = (time_dir / "manifest.json").resolve()
        _ensure_relative_to_base(base_dir=base, path=manifest_path, label="manifest")
        manifest_payload = {
            "schema": "digital-earth.volume-slices",
            "schema_version": 1,
            "layer": layer_norm,
            "time": time_key,
            "variable": "cloud_density",
            "source_variable": str(rh_variable),
            "rh0": float(thresholds.rh0),
            "rh1": float(thresholds.rh1),
            "levels": level_keys,
            "files": [path.name for path in files],
        }
        manifest_path.write_text(
            json.dumps(
                manifest_payload,
                ensure_ascii=True,
                separators=(",", ":"),
                sort_keys=True,
            )
            + "\n",
            encoding="utf-8",
        )

    return CloudDensityExportResult(
        layer=layer_norm,
        time=time_key,
        rh0=float(thresholds.rh0),
        rh1=float(thresholds.rh1),
        levels=tuple(level_keys),
        files=tuple(files),
        manifest=manifest_path,
    )
