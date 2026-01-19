from __future__ import annotations

import hashlib
import json
import logging
from asyncio import to_thread
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Optional

import numpy as np
import xarray as xr
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

import db
from catalog_cache import RedisLike, get_or_compute_cached_bytes
from data_source import DataNotFoundError, DataSourceError
from datacube.storage import open_datacube
from local_data_service import get_data_source
from models import EcmwfAsset, EcmwfRun, EcmwfTime

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/vector", tags=["vector"])

SHORT_CACHE_CONTROL_HEADER = "public, max-age=60"
CACHE_FRESH_TTL_SECONDS = 60
CACHE_STALE_TTL_SECONDS = 60 * 60
CACHE_LOCK_TTL_MS = 30_000
CACHE_WAIT_TIMEOUT_MS = 200
CACHE_COOLDOWN_TTL_SECONDS: tuple[int, int] = (5, 30)
MAX_VECTOR_POINTS = 10_000


class WindVectorResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    u: list[float | None] = Field(default_factory=list)
    v: list[float | None] = Field(default_factory=list)
    lat: list[float] = Field(default_factory=list)
    lon: list[float] = Field(default_factory=list)


_SURFACE_LEVEL_ALIASES = {"sfc", "surface"}


def _parse_time(value: str, *, label: str) -> datetime:
    raw = (value or "").strip()
    if raw == "":
        raise ValueError(f"{label} must not be empty")

    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"
    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError:
        try:
            parsed = datetime.strptime(raw, "%Y%m%dT%H%M%SZ")
        except ValueError as exc:
            raise ValueError(
                f"{label} must be an ISO8601 timestamp or YYYYMMDDTHHMMSSZ"
            ) from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _time_key(dt: datetime) -> str:
    normalized = dt
    if normalized.tzinfo is None:
        normalized = normalized.replace(tzinfo=timezone.utc)
    return normalized.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")


def _normalize_level(value: str) -> tuple[str, float | None]:
    raw = (value or "").strip()
    if raw == "":
        raise ValueError("level must not be empty")
    lowered = raw.lower()
    if lowered in _SURFACE_LEVEL_ALIASES:
        return "sfc", None

    try:
        stripped = lowered.removesuffix("hpa").strip()
        numeric = float(stripped)
    except ValueError as exc:
        raise ValueError("level must be 'sfc' or a numeric pressure level") from exc

    if not np.isfinite(numeric):
        raise ValueError("level must be a finite number")
    if float(numeric).is_integer():
        return str(int(float(numeric))), float(numeric)
    return str(float(numeric)).replace(".", "p"), float(numeric)


def _resolve_surface_level_index(levels: np.ndarray, attrs: dict[str, Any]) -> int:
    units = str(attrs.get("units") or "").strip().lower()
    long_name = str(attrs.get("long_name") or "").strip().lower()
    if "surface" in long_name or units in {"1", ""}:
        return 0
    matches = np.where(
        np.isclose(levels.astype(np.float64, copy=False), 0.0, atol=1e-3)
    )[0]
    if matches.size:
        return int(matches[0])
    raise HTTPException(
        status_code=404, detail="surface level requested but dataset has no surface"
    )


def _resolve_level_index(
    ds: xr.Dataset, *, level_key: str, numeric: float | None
) -> int:
    if "level" not in ds.coords:
        raise HTTPException(status_code=500, detail="DataCube missing level coordinate")

    levels = np.asarray(ds["level"].values)
    if levels.size == 0:
        raise HTTPException(
            status_code=500, detail="DataCube level coordinate is empty"
        )

    if level_key == "sfc":
        return _resolve_surface_level_index(levels, dict(ds["level"].attrs))

    if numeric is None or not np.isfinite(numeric):
        raise HTTPException(status_code=400, detail="level must be a finite number")

    numeric_f = float(numeric)
    matches = np.where(
        np.isclose(levels.astype(np.float64, copy=False), numeric_f, atol=1e-3)
    )[0]
    if matches.size == 0:
        raise HTTPException(status_code=404, detail="level not found in DataCube")
    return int(matches[0])


def _resolve_time_index(ds: xr.Dataset, *, valid_time: datetime) -> int:
    if "time" not in ds.coords:
        raise HTTPException(status_code=500, detail="DataCube missing time coordinate")
    values = np.asarray(ds["time"].values)
    if values.size == 0:
        raise HTTPException(status_code=500, detail="DataCube time coordinate is empty")

    dt = valid_time.astimezone(timezone.utc)
    target = np.datetime64(dt.strftime("%Y-%m-%dT%H:%M:%S"))
    matches = np.where(values.astype("datetime64[s]") == target)[0]
    if matches.size == 0:
        raise HTTPException(status_code=404, detail="valid_time not found in DataCube")
    return int(matches[0])


def _cache_identity(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


def _query_asset_path(*, run_time: datetime, valid_time: datetime, level: str) -> str:
    stmt = (
        select(EcmwfAsset.path)
        .join(EcmwfRun, EcmwfAsset.run_id == EcmwfRun.id)
        .join(EcmwfTime, EcmwfAsset.time_id == EcmwfTime.id)
        .where(
            EcmwfRun.run_time == run_time,
            EcmwfTime.valid_time == valid_time,
            func.lower(EcmwfAsset.variable) == "wind",
            func.lower(EcmwfAsset.level) == level.lower(),
        )
        .order_by(desc(EcmwfAsset.version))
        .limit(1)
    )

    try:
        with Session(db.get_engine()) as session:
            row = session.execute(stmt).first()
    except SQLAlchemyError as exc:
        logger.error("vector_wind_db_error", extra={"error": str(exc)})
        raise HTTPException(
            status_code=503, detail="Catalog database unavailable"
        ) from exc

    if row is None or not isinstance(row[0], str) or row[0].strip() == "":
        raise HTTPException(status_code=404, detail="DataCube asset not found")
    return row[0]


def _resolve_asset_path(path_value: str) -> Path:
    raw = (path_value or "").strip()
    if raw == "":
        raise HTTPException(status_code=500, detail="Empty asset path")

    candidate = Path(raw)
    if candidate.is_absolute():
        if not candidate.is_file():
            raise HTTPException(status_code=404, detail="DataCube file not found")
        return candidate

    ds = get_data_source()
    try:
        return ds.open_path(raw)
    except Exception as exc:  # noqa: BLE001
        if isinstance(exc, DataNotFoundError):
            raise HTTPException(status_code=404, detail=str(exc)) from exc
        if isinstance(exc, DataSourceError):
            raise HTTPException(status_code=400, detail=str(exc)) from exc
        raise HTTPException(status_code=500, detail="Internal Server Error") from exc


def _dataset_lon_uses_360(lon_coord: np.ndarray) -> bool:
    lon_f = np.asarray(lon_coord, dtype=np.float64)
    if lon_f.size == 0:
        return False
    try:
        lon_min = float(np.nanmin(lon_f))
        lon_max = float(np.nanmax(lon_f))
    except ValueError:
        return False
    return lon_min >= 0.0 and lon_max > 180.0


def _normalize_lon(lon: float, lon_coord: np.ndarray) -> float:
    if _dataset_lon_uses_360(lon_coord):
        return float(lon) % 360.0
    return float(((float(lon) + 180.0) % 360.0) - 180.0)


def _parse_bbox(value: Optional[str]) -> tuple[float, float, float, float] | None:
    if value is None:
        return None
    raw = value.strip()
    if raw == "":
        return None

    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 4:
        raise ValueError(
            "bbox must have 4 comma-separated numbers: minLon,minLat,maxLon,maxLat"
        )

    try:
        min_lon, min_lat, max_lon, max_lat = (float(part) for part in parts)
    except ValueError as exc:
        raise ValueError(
            "bbox must have 4 comma-separated numbers: minLon,minLat,maxLon,maxLat"
        ) from exc

    if not (np.isfinite(min_lon) and np.isfinite(max_lon)):
        raise ValueError("bbox longitude values must be finite numbers")
    if not (np.isfinite(min_lat) and np.isfinite(max_lat)):
        raise ValueError("bbox latitude values must be finite numbers")

    if min_lat < -90.0 or min_lat > 90.0 or max_lat < -90.0 or max_lat > 90.0:
        raise ValueError("bbox latitude values must be within [-90, 90]")
    if min_lon < -360.0 or min_lon > 360.0 or max_lon < -360.0 or max_lon > 360.0:
        raise ValueError("bbox longitude values must be within [-360, 360]")

    return float(min_lon), float(min_lat), float(max_lon), float(max_lat)


def _select_indices(
    coord: np.ndarray, *, min_value: float, max_value: float, stride: int
) -> np.ndarray:
    values = np.asarray(coord, dtype=np.float64)
    lower = float(min(min_value, max_value))
    upper = float(max(min_value, max_value))
    mask = (values >= lower) & (values <= upper)
    indices = np.where(mask)[0]
    if stride <= 1:
        return indices
    return indices[:: int(stride)]


def _select_lon_indices(
    lon_coord: np.ndarray, *, min_lon: float, max_lon: float, stride: int
) -> np.ndarray:
    lon_values = np.asarray(lon_coord, dtype=np.float64)
    if abs(float(max_lon) - float(min_lon)) >= 360.0:
        indices = np.arange(lon_values.size, dtype=int)
        if stride <= 1:
            return indices
        return indices[:: int(stride)]

    lon_min = _normalize_lon(min_lon, lon_coord)
    lon_max = _normalize_lon(max_lon, lon_coord)

    if lon_min <= lon_max:
        mask = (lon_values >= lon_min) & (lon_values <= lon_max)
    else:
        mask = (lon_values >= lon_min) | (lon_values <= lon_max)

    indices = np.where(mask)[0]
    if stride <= 1:
        return indices
    return indices[:: int(stride)]


def _resolve_wind_components(ds: xr.Dataset) -> tuple[str, str]:
    available = {name.lower(): name for name in ds.data_vars}
    candidates: list[tuple[str, str]] = [
        ("u", "v"),
        ("eastward_wind_10m", "northward_wind_10m"),
        ("10u", "10v"),
        ("u10", "v10"),
    ]
    for u_name, v_name in candidates:
        resolved_u = available.get(u_name.lower())
        resolved_v = available.get(v_name.lower())
        if resolved_u is not None and resolved_v is not None:
            return resolved_u, resolved_v
    raise HTTPException(status_code=404, detail="wind components not found in DataCube")


def _flatten_values(values: np.ndarray) -> list[float | None]:
    flat = np.asarray(values, dtype=np.float64).ravel()
    finite = np.isfinite(flat)
    return [float(v) if bool(ok) else None for v, ok in zip(flat, finite, strict=False)]


def _wind_vectors_from_datacube(
    cube_path: Path,
    *,
    valid_time: datetime,
    level_key: str,
    level_numeric: float | None,
    bbox: tuple[float, float, float, float] | None,
    stride: int,
) -> WindVectorResponse:
    ds = open_datacube(cube_path)
    try:
        time_index = _resolve_time_index(ds, valid_time=valid_time)
        level_index = _resolve_level_index(
            ds, level_key=level_key, numeric=level_numeric
        )

        u_name, v_name = _resolve_wind_components(ds)
        u_da = ds[u_name]
        v_da = ds[v_name]

        if "time" not in u_da.dims or "level" not in u_da.dims:
            raise HTTPException(
                status_code=500, detail="DataCube wind variable missing time/level dims"
            )
        if "time" not in v_da.dims or "level" not in v_da.dims:
            raise HTTPException(
                status_code=500, detail="DataCube wind variable missing time/level dims"
            )

        u_slice = u_da.isel(time=int(time_index), level=int(level_index)).transpose(
            "lat", "lon"
        )
        v_slice = v_da.isel(time=int(time_index), level=int(level_index)).transpose(
            "lat", "lon"
        )

        lat_coord = np.asarray(u_slice["lat"].values)
        lon_coord = np.asarray(u_slice["lon"].values)

        if bbox is None:
            lat_indices = np.arange(lat_coord.size, dtype=int)[:: int(stride)]
            lon_indices = np.arange(lon_coord.size, dtype=int)[:: int(stride)]
        else:
            min_lon, min_lat, max_lon, max_lat = bbox
            lat_indices = _select_indices(
                lat_coord, min_value=min_lat, max_value=max_lat, stride=stride
            )
            lon_indices = _select_lon_indices(
                lon_coord, min_lon=min_lon, max_lon=max_lon, stride=stride
            )

        if lat_indices.size == 0 or lon_indices.size == 0:
            return WindVectorResponse()

        point_count = int(lat_indices.size) * int(lon_indices.size)
        if point_count > MAX_VECTOR_POINTS:
            raise HTTPException(
                status_code=400, detail="reduce bbox or increase stride"
            )

        u_sub = u_slice.isel(lat=lat_indices, lon=lon_indices)
        v_sub = v_slice.isel(lat=lat_indices, lon=lon_indices)

        lat_vals = np.asarray(u_sub["lat"].values, dtype=np.float64)
        lon_vals = np.asarray(u_sub["lon"].values, dtype=np.float64)

        lon_grid, lat_grid = np.meshgrid(lon_vals, lat_vals)

        return WindVectorResponse(
            u=_flatten_values(np.asarray(u_sub.values)),
            v=_flatten_values(np.asarray(v_sub.values)),
            lat=_flatten_values(np.asarray(lat_grid)),
            lon=_flatten_values(np.asarray(lon_grid)),
        )
    finally:
        ds.close()


@router.get("/ecmwf/{run}/wind/{level}/{time}", response_model=WindVectorResponse)
async def get_ecmwf_wind_vectors(
    request: Request,
    run: str,
    level: str,
    time: str,
    bbox: Optional[str] = Query(
        default=None,
        description="Bounding box: minLon,minLat,maxLon,maxLat",
    ),
    stride: int = Query(default=1, ge=1, le=256),
) -> Response:
    try:
        run_dt = _parse_time(run, label="run")
        valid_dt = _parse_time(time, label="time")
        level_key, level_numeric = _normalize_level(level)
        parsed_bbox = _parse_bbox(bbox)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    identity_payload: dict[str, object] = {
        "run": _time_key(run_dt),
        "time": _time_key(valid_dt),
        "level": level_key,
        "bbox": list(parsed_bbox) if parsed_bbox is not None else None,
        "stride": int(stride),
    }
    identity = _cache_identity(identity_payload)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        def _sync() -> bytes:
            asset_path = _query_asset_path(
                run_time=run_dt, valid_time=valid_dt, level=level_key
            )
            cube_path = _resolve_asset_path(asset_path)
            response = _wind_vectors_from_datacube(
                cube_path,
                valid_time=valid_dt,
                level_key=level_key,
                level_numeric=level_numeric,
                bbox=parsed_bbox,
                stride=int(stride),
            )
            return response.model_dump_json().encode("utf-8")

        return await to_thread(_sync)

    if redis is None:
        body = await _compute()
    else:
        fresh_key = f"vector:ecmwf:wind:fresh:{digest}"
        stale_key = f"vector:ecmwf:wind:stale:{digest}"
        lock_key = f"vector:ecmwf:wind:lock:{digest}"
        try:
            result = await get_or_compute_cached_bytes(
                redis,
                fresh_key=fresh_key,
                stale_key=stale_key,
                lock_key=lock_key,
                fresh_ttl_seconds=CACHE_FRESH_TTL_SECONDS,
                stale_ttl_seconds=CACHE_STALE_TTL_SECONDS,
                lock_ttl_ms=CACHE_LOCK_TTL_MS,
                wait_timeout_ms=CACHE_WAIT_TIMEOUT_MS,
                compute=_compute,
                cooldown_ttl_seconds=CACHE_COOLDOWN_TTL_SECONDS,
            )
            body = result.body
        except TimeoutError as exc:
            raise HTTPException(
                status_code=503, detail="Vector cache warming timed out"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("vector_cache_unavailable", extra={"error": str(exc)})
            body = await _compute()

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": etag}
    return Response(content=body, media_type="application/json", headers=headers)
