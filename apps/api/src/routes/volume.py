from __future__ import annotations

import logging
import math
import os
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final

import numpy as np
from fastapi import APIRouter, HTTPException, Query
from fastapi.responses import Response

from datacube.storage import open_datacube
from volume.cloud_density import DEFAULT_CLOUD_DENSITY_LAYER
from volume.pack import encode_volume_pack

logger = logging.getLogger("api.error")

router = APIRouter(tags=["volume"])

VOLUME_DATA_DIR_ENV: Final[str] = "DIGITAL_EARTH_VOLUME_DATA_DIR"

MAX_BBOX_AREA_DEG2: Final[float] = 100.0
MIN_RES_METERS: Final[float] = 100.0
MAX_OUTPUT_BYTES: Final[int] = 64 * 1024 * 1024

METERS_PER_DEG_LAT: Final[float] = 111_320.0

_TIME_KEY_FORMAT: Final[str] = "%Y%m%dT%H%M%SZ"
_ISO_Z_FORMAT: Final[str] = "%Y-%m-%dT%H:%M:%SZ"


@dataclass(frozen=True)
class BBox:
    west: float
    south: float
    east: float
    north: float
    bottom: float
    top: float

    def area_deg2(self) -> float:
        return (self.east - self.west) * (self.north - self.south)

    def to_header(self) -> dict[str, float]:
        return {
            "west": float(self.west),
            "south": float(self.south),
            "east": float(self.east),
            "north": float(self.north),
            "bottom": float(self.bottom),
            "top": float(self.top),
        }


def _parse_bbox(value: str) -> BBox:
    raw = (value or "").strip()
    if raw == "":
        raise ValueError("bbox must not be empty")

    parts = [part.strip() for part in raw.split(",")]
    if len(parts) != 6:
        raise ValueError("bbox must have 6 comma-separated numbers")

    try:
        west, south, east, north, bottom, top = (float(part) for part in parts)
    except ValueError as exc:
        raise ValueError("bbox values must be valid numbers") from exc

    floats = (west, south, east, north, bottom, top)
    if not all(math.isfinite(item) for item in floats):
        raise ValueError("bbox values must be finite numbers")

    if east <= west:
        raise ValueError("bbox east must be > west")
    if north <= south:
        raise ValueError("bbox north must be > south")

    bbox = BBox(
        west=float(west),
        south=float(south),
        east=float(east),
        north=float(north),
        bottom=float(bottom),
        top=float(top),
    )
    if bbox.area_deg2() > MAX_BBOX_AREA_DEG2:
        raise ValueError("bbox area exceeds maximum")
    return bbox


def _parse_levels(value: str) -> tuple[str, ...]:
    raw = (value or "").strip()
    if raw == "":
        raise ValueError("levels must not be empty")

    items = [part.strip() for part in raw.split(",") if part.strip()]
    if not items:
        raise ValueError("levels must not be empty")

    normalized: list[str] = []
    for item in items:
        try:
            numeric = float(item)
        except ValueError as exc:
            raise ValueError("levels must be comma-separated numbers") from exc
        if not math.isfinite(numeric):
            raise ValueError("levels must be finite numbers")
        if abs(numeric - round(numeric)) < 1e-6:
            normalized.append(str(int(round(numeric))))
        else:
            normalized.append(str(float(numeric)))

    deduped = list(dict.fromkeys(normalized))
    return tuple(deduped)


def _parse_valid_time(value: str) -> datetime:
    raw = (value or "").strip()
    if raw == "":
        raise ValueError("valid_time must not be empty")

    candidate = raw
    if candidate.endswith("Z"):
        candidate = candidate[:-1] + "+00:00"

    try:
        parsed = datetime.fromisoformat(candidate)
    except ValueError as exc:
        raise ValueError("valid_time must be an ISO8601 timestamp") from exc

    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).replace(microsecond=0)


def _time_key(dt: datetime) -> str:
    parsed = dt
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime(_TIME_KEY_FORMAT)


def _iso_z(dt: datetime) -> str:
    parsed = dt
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc).strftime(_ISO_Z_FORMAT)


def _parse_time_key(value: str) -> datetime | None:
    try:
        parsed = datetime.strptime(value, _TIME_KEY_FORMAT).replace(tzinfo=timezone.utc)
    except ValueError:
        return None
    return parsed


def _resolve_volume_base_dir() -> Path:
    raw = os.environ.get(VOLUME_DATA_DIR_ENV, "").strip()
    if raw == "":
        raise HTTPException(
            status_code=503,
            detail=f"Volume data directory is not configured ({VOLUME_DATA_DIR_ENV})",
        )
    path = Path(raw).expanduser()
    if not path.is_absolute():
        path = (Path.cwd() / path).resolve()
    if not path.exists():
        raise HTTPException(status_code=404, detail="Volume data directory not found")
    if not path.is_dir():
        raise HTTPException(status_code=400, detail="Volume data path is not a directory")
    return path


def _resolve_time_dir(
    base_dir: Path, *, layer: str, valid_time: datetime | None
) -> tuple[str, datetime, Path]:
    layer_dir = (base_dir / layer).resolve()
    if not layer_dir.exists() or not layer_dir.is_dir():
        raise HTTPException(status_code=404, detail="Volume layer not found")

    if valid_time is not None:
        key = _time_key(valid_time)
        target = layer_dir / key
        if not target.exists() or not target.is_dir():
            raise HTTPException(status_code=404, detail="valid_time not found")
        return key, valid_time, target

    candidates: list[tuple[str, datetime]] = []
    for entry in layer_dir.iterdir():
        if not entry.is_dir():
            continue
        dt = _parse_time_key(entry.name)
        if dt is None:
            continue
        candidates.append((entry.name, dt))
    if not candidates:
        raise HTTPException(status_code=404, detail="No volume times available")

    key, dt = max(candidates, key=lambda item: item[0])
    return key, dt, layer_dir / key


def _resolve_slice_path(time_dir: Path, *, level_key: str) -> Path:
    netcdf_path = time_dir / f"{level_key}.nc"
    if netcdf_path.is_file():
        return netcdf_path
    zarr_path = time_dir / f"{level_key}.zarr"
    if zarr_path.exists() and zarr_path.is_dir():
        return zarr_path
    raise HTTPException(status_code=404, detail=f"level not found: {level_key}")


def _normalize_lon(value: float, lon_coord: np.ndarray) -> float:
    coord = np.asarray(lon_coord, dtype=np.float64)
    if coord.size == 0:
        return float(value)
    lon_min = float(np.nanmin(coord))
    lon_max = float(np.nanmax(coord))

    lon = float(value)
    if lon_min >= 0.0 and lon_max > 180.0:
        return lon % 360.0
    return ((lon + 180.0) % 360.0) - 180.0


def _monotonic_1d(coord: np.ndarray) -> bool:
    if coord.ndim != 1:
        return False
    if coord.size < 2:
        return True
    diffs = np.diff(coord.astype(np.float64, copy=False))
    return bool(np.all(diffs > 0) or np.all(diffs < 0))


def _sorted_axis(coord: np.ndarray) -> tuple[np.ndarray, np.ndarray]:
    order = np.argsort(coord.astype(np.float64, copy=False))
    return coord[order], order


def _bounding_slice(coord_sorted: np.ndarray, vmin: float, vmax: float) -> slice:
    if coord_sorted.size == 0:
        return slice(0, 0)
    start = max(0, int(np.searchsorted(coord_sorted, vmin, side="left")) - 1)
    end = min(
        int(coord_sorted.size - 1),
        int(np.searchsorted(coord_sorted, vmax, side="right")),
    )
    if end < start:
        return slice(0, 0)
    return slice(start, end + 1)


def _interp_1d(x: np.ndarray, y: np.ndarray, x_new: np.ndarray) -> np.ndarray:
    x_f = np.asarray(x, dtype=np.float64)
    y_f = np.asarray(y, dtype=np.float32)
    xq = np.asarray(x_new, dtype=np.float64)
    if x_f.size == 0:
        raise ValueError("source coordinate is empty")
    if x_f.size == 1:
        return np.full(xq.shape, float(y_f[0]), dtype=np.float32)
    return np.interp(xq, x_f, y_f).astype(np.float32, copy=False)


def _interp2d(
    *,
    lat: np.ndarray,
    lon: np.ndarray,
    values: np.ndarray,
    target_lat: np.ndarray,
    target_lon: np.ndarray,
) -> np.ndarray:
    if lat.ndim != 1 or lon.ndim != 1:
        raise ValueError("lat/lon must be 1D coordinates")
    if values.shape != (lat.size, lon.size):
        raise ValueError("values must have shape (lat, lon)")

    lon_intermediate = np.empty((lat.size, target_lon.size), dtype=np.float32)
    for i in range(lat.size):
        lon_intermediate[i, :] = _interp_1d(lon, values[i, :], target_lon)

    out = np.empty((target_lat.size, target_lon.size), dtype=np.float32)
    for j in range(target_lon.size):
        out[:, j] = _interp_1d(lat, lon_intermediate[:, j], target_lat)

    return out


def _read_cloud_density_grid(path: Path) -> tuple[np.ndarray, np.ndarray, np.ndarray]:
    ds = open_datacube(path)
    try:
        if "cloud_density" not in ds.data_vars:
            raise HTTPException(status_code=500, detail="Slice missing cloud_density")
        da = ds["cloud_density"].squeeze(drop=True)
        if set(da.dims) != {"lat", "lon"}:
            raise HTTPException(
                status_code=500, detail="Slice must have lat/lon dimensions"
            )
        lat = np.asarray(da["lat"].values, dtype=np.float64)
        lon = np.asarray(da["lon"].values, dtype=np.float64)
        values = np.asarray(da.values, dtype=np.float32)
    finally:
        ds.close()

    if not (_monotonic_1d(lat) and _monotonic_1d(lon)):
        raise HTTPException(status_code=500, detail="Slice coordinates are not monotonic")
    if values.ndim != 2 or values.shape != (lat.size, lon.size):
        raise HTTPException(status_code=500, detail="Slice has invalid data shape")
    return lat, lon, values


def _target_grid(bbox: BBox, *, res_m: float) -> tuple[np.ndarray, np.ndarray]:
    lat_dist_m = (bbox.north - bbox.south) * METERS_PER_DEG_LAT
    mean_lat_rad = math.radians((bbox.south + bbox.north) / 2.0)
    lon_dist_m = (
        (bbox.east - bbox.west)
        * METERS_PER_DEG_LAT
        * max(0.0, abs(math.cos(mean_lat_rad)))
    )

    n_lat = max(2, int(math.ceil(lat_dist_m / res_m)) + 1)
    n_lon = max(2, int(math.ceil(lon_dist_m / res_m)) + 1)

    target_lat = np.linspace(bbox.south, bbox.north, n_lat, dtype=np.float64)
    target_lon = np.linspace(bbox.west, bbox.east, n_lon, dtype=np.float64)
    return target_lat, target_lon


@router.get(
    "/volume",
    response_class=Response,
    responses={
        200: {
            "description": "Volume Pack binary payload",
            "content": {
                "application/octet-stream": {
                    "schema": {"type": "string", "format": "binary"}
                }
            },
        },
        400: {"description": "Bad Request"},
        404: {"description": "Not Found"},
        500: {"description": "Internal Server Error"},
        503: {"description": "Service Unavailable"},
    },
)
def get_volume(
    bbox: str = Query(
        ...,
        description="west,south,east,north,bottom,top (degrees/meters)",
        examples=["-10,20,10,40,0,12000"],
    ),
    levels: str = Query(..., description="Comma-separated pressure levels (hPa)"),
    res: float = Query(..., description="Horizontal resolution in meters"),
    valid_time: str | None = Query(default=None, description="ISO8601 timestamp"),
) -> Response:
    try:
        bbox_parsed = _parse_bbox(bbox)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        levels_keys = _parse_levels(levels)
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=str(exc)) from exc

    try:
        res_m = float(res)
    except (TypeError, ValueError) as exc:
        raise HTTPException(status_code=400, detail="res must be a number") from exc
    if not math.isfinite(res_m) or res_m <= 0:
        raise HTTPException(status_code=400, detail="res must be a positive number")
    if res_m < MIN_RES_METERS:
        raise HTTPException(status_code=400, detail="res is below minimum")

    dt: datetime | None = None
    if valid_time is not None:
        try:
            dt = _parse_valid_time(valid_time)
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=str(exc)) from exc

    target_lat, target_lon = _target_grid(bbox_parsed, res_m=res_m)
    decoded_bytes = int(len(levels_keys)) * int(target_lat.size) * int(target_lon.size) * 4
    if decoded_bytes > MAX_OUTPUT_BYTES:
        raise HTTPException(status_code=400, detail="Requested volume exceeds max size")

    base_dir = _resolve_volume_base_dir()
    _time_key, resolved_dt, time_dir = _resolve_time_dir(
        base_dir, layer=DEFAULT_CLOUD_DENSITY_LAYER, valid_time=dt
    )

    slices: list[np.ndarray] = []
    lon_coord: np.ndarray | None = None
    lat_coord: np.ndarray | None = None
    for level_key in levels_keys:
        slice_path = _resolve_slice_path(time_dir, level_key=level_key)
        lat, lon, values = _read_cloud_density_grid(slice_path)

        lon_w = _normalize_lon(bbox_parsed.west, lon)
        lon_e = _normalize_lon(bbox_parsed.east, lon)
        if lon_e <= lon_w:
            raise HTTPException(status_code=400, detail="bbox crosses longitude seam")

        lon_sorted, lon_order = _sorted_axis(lon)
        lat_sorted, lat_order = _sorted_axis(lat)
        values_sorted = values[np.ix_(lat_order, lon_order)]

        lat_slice = _bounding_slice(lat_sorted, bbox_parsed.south, bbox_parsed.north)
        lon_slice = _bounding_slice(lon_sorted, lon_w, lon_e)
        if lat_slice.stop == 0 or lon_slice.stop == 0:
            raise HTTPException(status_code=404, detail="bbox outside dataset")

        lat_sub = lat_sorted[lat_slice]
        lon_sub = lon_sorted[lon_slice]
        values_sub = values_sorted[lat_slice, :][:, lon_slice]

        if lat_coord is None:
            lat_coord = lat_sub
            lon_coord = lon_sub
        else:
            if lat_coord.shape != lat_sub.shape or lon_coord is None or lon_coord.shape != lon_sub.shape:
                raise HTTPException(status_code=500, detail="Slice grids do not match")

        target_lon_norm = np.linspace(lon_w, lon_e, target_lon.size, dtype=np.float64)
        slice_resampled = _interp2d(
            lat=lat_sub,
            lon=lon_sub,
            values=values_sub,
            target_lat=target_lat,
            target_lon=target_lon_norm,
        )
        slices.append(slice_resampled)

    volume = np.stack(slices, axis=0).astype(np.float32, copy=False)

    header = {
        "bbox": bbox_parsed.to_header(),
        "levels": [int(level) if level.isdigit() else float(level) for level in levels_keys],
        "variable": "cloud_density",
        "valid_time": _iso_z(resolved_dt),
        "res_m": float(res_m),
        "layer": DEFAULT_CLOUD_DENSITY_LAYER,
        "scale": 1.0,
        "offset": 0.0,
        "dtype": "float32",
    }

    try:
        payload = encode_volume_pack(volume, header=header, compression_level=3)
    except Exception as exc:  # noqa: BLE001
        logger.error("volume_encode_error", extra={"error": str(exc)})
        raise HTTPException(status_code=500, detail="Failed to encode volume") from exc

    if len(payload) > MAX_OUTPUT_BYTES:
        raise HTTPException(status_code=400, detail="Encoded volume exceeds max size")

    return Response(content=payload, media_type="application/octet-stream")

