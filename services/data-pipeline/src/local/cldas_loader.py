from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Final, Optional, Sequence, Union

import numpy as np
import xarray as xr


class CldasLocalLoadError(RuntimeError):
    pass


_CLDAS_FILENAME_RE: Final[re.Pattern[str]] = re.compile(
    r"^CHINA_WEST_(?P<resolution>[0-9]+P[0-9]+)_HOR-(?P<var>[A-Za-z0-9]+)-(?P<ts>\d{10})\.nc$",
    re.IGNORECASE,
)

_LAT_ALIASES: Final[Sequence[str]] = ("lat", "latitude", "LAT", "Latitude", "nav_lat")
_LON_ALIASES: Final[Sequence[str]] = ("lon", "longitude", "LON", "Longitude", "nav_lon")

DEFAULT_CLDAS_MAX_FILE_SIZE_BYTES: Final[int] = 512 * 1024 * 1024
DEFAULT_CLDAS_MAX_TOTAL_CELLS: Final[int] = 50_000_000
DEFAULT_CLDAS_STATS_CHUNK_TARGET_ELEMENTS: Final[int] = 1_000_000


def _find_axis_name(present: Sequence[str], aliases: Sequence[str]) -> Optional[str]:
    for name in aliases:
        if name in present:
            return name
    lowered = {name.lower(): name for name in present}
    for alias in aliases:
        candidate = lowered.get(alias.lower())
        if candidate:
            return candidate
    return None


def _format_time_iso(dt: datetime) -> str:
    value = dt.astimezone(timezone.utc).isoformat()
    if value.endswith("+00:00"):
        value = value[:-6] + "Z"
    return value


def _parse_timestamp_from_name(name: str) -> tuple[str, datetime]:
    match = _CLDAS_FILENAME_RE.match(name)
    if not match:
        raise CldasLocalLoadError(f"Unrecognized CLDAS filename: {name}")
    ts = match.group("ts")
    try:
        dt = datetime.strptime(ts, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise CldasLocalLoadError(
            f"Invalid CLDAS timestamp in filename: {name}"
        ) from exc
    return ts, dt


@dataclass(frozen=True)
class CldasGridSummary:
    variable: str
    time: str
    resolution: Optional[str]
    dims: dict[str, int]
    lat_min: float
    lat_max: float
    lon_min: float
    lon_max: float
    value_min: Optional[float]
    value_max: Optional[float]


def load_cldas_dataset(
    source_path: Union[str, Path],
    *,
    engine: Optional[str] = None,
    max_file_size_bytes: Optional[int] = DEFAULT_CLDAS_MAX_FILE_SIZE_BYTES,
    max_total_cells: Optional[int] = DEFAULT_CLDAS_MAX_TOTAL_CELLS,
) -> xr.Dataset:
    path = Path(source_path)
    _, dt = _parse_timestamp_from_name(path.name)
    match = _CLDAS_FILENAME_RE.match(path.name)
    assert match is not None
    variable_code = match.group("var").upper()

    try:
        stat = path.stat()
    except FileNotFoundError as exc:
        raise CldasLocalLoadError(f"CLDAS NetCDF file not found: {path}") from exc
    if max_file_size_bytes is not None and int(stat.st_size) > max_file_size_bytes:
        raise CldasLocalLoadError(f"CLDAS NetCDF file too large: {path}")

    try:
        ds = xr.open_dataset(path, engine=engine, decode_cf=True, mask_and_scale=True)
    except CldasLocalLoadError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise CldasLocalLoadError(f"Failed to load CLDAS NetCDF: {path}") from exc

    try:
        dim_names = list(ds.dims)
        coord_names = list(ds.coords)

        lat_name = _find_axis_name(dim_names, _LAT_ALIASES) or _find_axis_name(
            coord_names, _LAT_ALIASES
        )
        lon_name = _find_axis_name(dim_names, _LON_ALIASES) or _find_axis_name(
            coord_names, _LON_ALIASES
        )

        if lat_name is None or lon_name is None:
            raise CldasLocalLoadError(
                f"Missing LAT/LON axes in {path.name}; dims={dim_names}, coords={coord_names}"
            )

        rename_map: dict[str, str] = {}
        if lat_name != "lat":
            rename_map[lat_name] = "lat"
        if lon_name != "lon":
            rename_map[lon_name] = "lon"
        if rename_map:
            ds = ds.rename(rename_map)

        if "lat" not in ds.coords or "lon" not in ds.coords:
            raise CldasLocalLoadError(
                f"Failed to normalize LAT/LON coordinates in {path.name}"
            )

        if ds["lat"].ndim != 1 or ds["lon"].ndim != 1:
            raise CldasLocalLoadError(
                f"Only 1D lat/lon coordinates are supported; got lat.ndim={ds['lat'].ndim}, lon.ndim={ds['lon'].ndim}"
            )

        if "time" not in ds.dims:
            ds = ds.expand_dims({"time": [np.datetime64(dt, "s")]})

        data_vars = list(ds.data_vars)
        if len(data_vars) == 1 and data_vars[0] != variable_code:
            ds = ds.rename({data_vars[0]: variable_code})

        if max_total_cells is not None and data_vars:
            primary_var = (
                variable_code if variable_code in ds.data_vars else data_vars[0]
            )
            total_cells = 1
            for size in ds[primary_var].sizes.values():
                total_cells *= int(size)
            if total_cells > max_total_cells:
                raise CldasLocalLoadError(
                    f"CLDAS NetCDF dataset too large to process safely: {path}"
                )

        ds.attrs = dict(ds.attrs)
        ds.attrs.update(
            {
                "source_path": str(path.resolve()),
                "variable_code": variable_code,
                "time": _format_time_iso(dt),
            }
        )

        return ds
    except CldasLocalLoadError:
        ds.close()
        raise
    except Exception as exc:  # noqa: BLE001
        ds.close()
        raise CldasLocalLoadError(f"Failed to load CLDAS NetCDF: {path}") from exc


def summarize_cldas_dataset(ds: xr.Dataset) -> CldasGridSummary:
    data_vars = list(ds.data_vars)
    variable = data_vars[0] if data_vars else "<none>"
    resolution = None
    source_name = Path(ds.attrs.get("source_path", "")).name
    match = _CLDAS_FILENAME_RE.match(source_name)
    if match:
        resolution = match.group("resolution").upper()

    lat = ds["lat"].values.astype(np.float64)
    lon = ds["lon"].values.astype(np.float64)

    value_min: Optional[float] = None
    value_max: Optional[float] = None
    if data_vars:
        data = ds[data_vars[0]]
        chunk_dim = "lat" if "lat" in data.sizes else next(iter(data.sizes), None)
        if chunk_dim is not None:
            other_elements = 1
            for name, size in data.sizes.items():
                if name != chunk_dim:
                    other_elements *= int(size)
            chunk_len = max(
                1,
                int(
                    DEFAULT_CLDAS_STATS_CHUNK_TARGET_ELEMENTS // max(1, other_elements)
                ),
            )
            chunk_len = min(chunk_len, int(data.sizes[chunk_dim]))

            for start in range(0, int(data.sizes[chunk_dim]), chunk_len):
                chunk = np.asarray(
                    data.isel({chunk_dim: slice(start, start + chunk_len)}).values
                )
                chunk = chunk.astype(np.float64, copy=False)
                finite = np.isfinite(chunk)
                if not finite.any():
                    continue
                chunk[~finite] = np.nan
                chunk_min = float(np.nanmin(chunk))
                chunk_max = float(np.nanmax(chunk))
                value_min = (
                    chunk_min if value_min is None else min(value_min, chunk_min)
                )
                value_max = (
                    chunk_max if value_max is None else max(value_max, chunk_max)
                )

    time_str = ds.attrs.get("time")
    if not isinstance(time_str, str) or not time_str.strip():
        time_str = None
    if time_str is None and "time" in ds.coords and ds["time"].size:
        raw = ds["time"].values[0]
        try:
            parsed = np.datetime64(raw, "s").astype("datetime64[s]")
            time_str = _format_time_iso(
                datetime.fromtimestamp(
                    int(parsed.astype("datetime64[s]").astype(int)),
                    tz=timezone.utc,
                )
            )
        except Exception:  # noqa: BLE001
            time_str = None

    return CldasGridSummary(
        variable=str(variable),
        time=str(time_str or ""),
        resolution=resolution,
        dims={k: int(v) for k, v in ds.sizes.items()},
        lat_min=float(np.nanmin(lat)),
        lat_max=float(np.nanmax(lat)),
        lon_min=float(np.nanmin(lon)),
        lon_max=float(np.nanmax(lon)),
        value_min=value_min,
        value_max=value_max,
    )
