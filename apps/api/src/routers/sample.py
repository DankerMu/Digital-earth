from __future__ import annotations

import hashlib
import json
import logging
from asyncio import to_thread
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import numpy as np
import xarray as xr
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import Response
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import desc, func, select
from sqlalchemy.exc import SQLAlchemyError
from sqlalchemy.orm import Session

from catalog_cache import RedisLike, get_or_compute_cached_bytes
import db
from data_source import DataNotFoundError, DataSourceError
from datacube.storage import open_datacube
from local_data_service import get_data_source
from models import EcmwfAsset, EcmwfRun, EcmwfTime

logger = logging.getLogger("api.error")

router = APIRouter(prefix="/sample", tags=["sample"])

SHORT_CACHE_CONTROL_HEADER = "public, max-age=60"
CACHE_FRESH_TTL_SECONDS = 60
CACHE_STALE_TTL_SECONDS = 60 * 60
CACHE_LOCK_TTL_MS = 30_000
CACHE_WAIT_TIMEOUT_MS = 200
CACHE_COOLDOWN_TTL_SECONDS: tuple[int, int] = (5, 30)

SampleQC = Literal["ok", "missing"]


class SampleResponse(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: float | None = None
    unit: str = ""
    qc: SampleQC = Field(default="missing")


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


_SURFACE_LEVEL_ALIASES = {"sfc", "surface"}


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


def _resolve_variable_name(ds: xr.Dataset, requested: str) -> str:
    if requested in ds.data_vars:
        return requested

    lowered = requested.lower()
    lookup = {name.lower(): name for name in ds.data_vars}
    resolved = lookup.get(lowered)
    if resolved is None:
        raise HTTPException(status_code=404, detail="var not found in DataCube")
    return resolved


def _normalize_query_lon(lon: float, lon_coord: np.ndarray) -> float:
    lon_f = np.asarray(lon_coord, dtype=np.float64)
    if lon_f.size == 0:
        return float(lon)
    try:
        lon_min = float(np.nanmin(lon_f))
        lon_max = float(np.nanmax(lon_f))
    except ValueError:
        return float(lon)

    # If the dataset looks like [0, 360) longitudes, normalize query to that range.
    if lon_min >= 0.0 and lon_max > 180.0:
        return float(lon) % 360.0
    # Otherwise normalize to [-180, 180).
    return float(((float(lon) + 180.0) % 360.0) - 180.0)


def _interp_1d(coord: np.ndarray, query: float) -> tuple[list[int], float, bool]:
    coord_f = np.asarray(coord, dtype=np.float64)
    if coord_f.ndim != 1 or coord_f.size == 0:
        raise HTTPException(status_code=500, detail="DataCube has invalid coordinates")

    order = np.argsort(coord_f)
    sorted_coord = coord_f[order]

    q = float(query)
    valid = bool(q >= float(sorted_coord[0]) and q <= float(sorted_coord[-1]))

    right = int(np.searchsorted(sorted_coord, q, side="right"))
    left = right - 1
    count = int(sorted_coord.size)

    left = int(np.clip(left, 0, count - 1))
    right = int(np.clip(right, 0, count - 1))

    denom = float(sorted_coord[right] - sorted_coord[left])
    if denom == 0.0:
        frac = 0.0
    else:
        frac = (q - float(sorted_coord[left])) / denom
        frac = float(np.clip(frac, 0.0, 1.0))

    return [int(order[left]), int(order[right])], frac, valid


def _bilinear_point_sample(da: xr.DataArray, *, lat: float, lon: float) -> float | None:
    if set(da.dims) != {"lat", "lon"}:
        raise HTTPException(status_code=500, detail="DataCube variable is not lat/lon")

    lat_coord = np.asarray(da["lat"].values)
    lon_coord = np.asarray(da["lon"].values)
    lon_q = _normalize_query_lon(lon, lon_coord)

    lat_idx, lat_f, lat_ok = _interp_1d(lat_coord, float(lat))
    lon_idx, lon_f, lon_ok = _interp_1d(lon_coord, lon_q)

    if not (lat_ok and lon_ok):
        return None

    # Advanced indexing keeps the index order we pass in.
    corners = da.isel(lat=lat_idx, lon=lon_idx).transpose("lat", "lon").values
    corner_values = np.asarray(corners, dtype=np.float64)
    if corner_values.shape != (2, 2):
        raise HTTPException(status_code=500, detail="Failed to load 2x2 neighborhood")

    if not np.all(np.isfinite(corner_values)):
        return None

    v00 = float(corner_values[0, 0])
    v01 = float(corner_values[0, 1])
    v10 = float(corner_values[1, 0])
    v11 = float(corner_values[1, 1])

    wy = float(lat_f)
    wx = float(lon_f)

    out = (
        (1.0 - wy) * (1.0 - wx) * v00
        + (1.0 - wy) * wx * v01
        + wy * (1.0 - wx) * v10
        + wy * wx * v11
    )
    if not np.isfinite(out):
        return None
    return float(out)


def _query_asset_path(
    *, run_time: datetime, valid_time: datetime, variable: str, level: str
) -> str:
    stmt = (
        select(EcmwfAsset.path)
        .join(EcmwfRun, EcmwfAsset.run_id == EcmwfRun.id)
        .join(EcmwfTime, EcmwfAsset.time_id == EcmwfTime.id)
        .where(
            EcmwfRun.run_time == run_time,
            EcmwfTime.valid_time == valid_time,
            func.lower(EcmwfAsset.variable) == variable.lower(),
            func.lower(EcmwfAsset.level) == level.lower(),
        )
        .order_by(desc(EcmwfAsset.version))
        .limit(1)
    )

    try:
        with Session(db.get_engine()) as session:
            row = session.execute(stmt).first()
    except SQLAlchemyError as exc:
        logger.error("sample_db_error", extra={"error": str(exc)})
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


def _sample_from_datacube(
    cube_path: Path,
    *,
    var: str,
    valid_time: datetime,
    level_key: str,
    level_numeric: float | None,
    lon: float,
    lat: float,
) -> SampleResponse:
    ds = open_datacube(cube_path)
    try:
        resolved_var = _resolve_variable_name(ds, var)
        da = ds[resolved_var]
        unit = str(da.attrs.get("units") or "")

        time_index = _resolve_time_index(ds, valid_time=valid_time)
        level_index = _resolve_level_index(
            ds, level_key=level_key, numeric=level_numeric
        )

        if "time" not in da.dims or "level" not in da.dims:
            raise HTTPException(
                status_code=500, detail="DataCube variable missing time/level dims"
            )

        slice_da = da.isel(time=int(time_index), level=int(level_index))
        slice_da = slice_da.transpose("lat", "lon")

        sampled = _bilinear_point_sample(slice_da, lat=float(lat), lon=float(lon))
        if sampled is None:
            return SampleResponse(value=None, unit=unit, qc="missing")

        return SampleResponse(value=float(sampled), unit=unit, qc="ok")
    finally:
        ds.close()


def _cache_identity(payload: dict[str, object]) -> str:
    return json.dumps(payload, separators=(",", ":"), sort_keys=True, ensure_ascii=True)


@router.get("", response_model=SampleResponse)
async def sample_point(
    request: Request,
    run: str = Query(..., min_length=1, description="ECMWF run time"),
    valid_time: str = Query(..., min_length=1, description="Valid time"),
    level: str = Query(..., min_length=1, description="Pressure level (hPa) or sfc"),
    var: str = Query(..., min_length=1, description="Variable name"),
    lon: float = Query(..., ge=-360.0, le=360.0),
    lat: float = Query(..., ge=-90.0, le=90.0),
) -> Response:
    try:
        run_dt = _parse_time(run, label="run")
        valid_dt = _parse_time(valid_time, label="valid_time")
        level_key, level_numeric = _normalize_level(level)
        var_key = (var or "").strip()
        if var_key == "":
            raise ValueError("var must not be empty")
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    identity_payload = {
        "run": _time_key(run_dt),
        "valid_time": _time_key(valid_dt),
        "level": level_key,
        "var": var_key.lower(),
        "lon": float(lon),
        "lat": float(lat),
    }
    identity = _cache_identity(identity_payload)
    digest = hashlib.sha256(identity.encode("utf-8")).hexdigest()

    redis: RedisLike | None = getattr(request.app.state, "redis_client", None)

    async def _compute() -> bytes:
        def _sync() -> bytes:
            asset_path = _query_asset_path(
                run_time=run_dt,
                valid_time=valid_dt,
                variable=var_key,
                level=level_key,
            )
            cube_path = _resolve_asset_path(asset_path)
            response = _sample_from_datacube(
                cube_path,
                var=var_key,
                valid_time=valid_dt,
                level_key=level_key,
                level_numeric=level_numeric,
                lon=float(lon),
                lat=float(lat),
            )
            return response.model_dump_json().encode("utf-8")

        return await to_thread(_sync)

    if redis is None:
        body = await _compute()
    else:
        fresh_key = f"sample:fresh:{digest}"
        stale_key = f"sample:stale:{digest}"
        lock_key = f"sample:lock:{digest}"
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
                status_code=503, detail="Sample cache warming timed out"
            ) from exc
        except Exception as exc:  # noqa: BLE001
            logger.warning("sample_cache_unavailable", extra={"error": str(exc)})
            body = await _compute()

    etag = f'"sha256-{hashlib.sha256(body).hexdigest()}"'
    headers = {"Cache-Control": SHORT_CACHE_CONTROL_HEADER, "ETag": etag}
    return Response(content=body, media_type="application/json", headers=headers)
