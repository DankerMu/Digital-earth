from __future__ import annotations

import json
import os
from typing import Final, Mapping, Optional, Sequence

import numpy as np
import xarray as xr

from digital_earth_config.settings import _canonical_env, _resolve_config_dir

PRECIP_TYPE_RAIN: Final[np.float32] = np.float32(0.0)
PRECIP_TYPE_SNOW: Final[np.float32] = np.float32(1.0)
PRECIP_TYPE_MIX: Final[np.float32] = np.float32(2.0)

PRECIP_TYPE_FLAG_VALUES: Final[list[int]] = [0, 1, 2]
PRECIP_TYPE_FLAG_MEANINGS: Final[str] = "rain snow mix"

PRECIP_TYPE_THRESHOLD_ENV: Final[str] = (
    "DIGITAL_EARTH_PIPELINE_PRECIP_TYPE_TEMP_THRESHOLD_C"
)
DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C: Final[float] = 0.0


def resolve_precip_type_temp_threshold_c(
    environ: Optional[Mapping[str, str]] = None,
) -> float:
    environ = environ or os.environ

    raw = environ.get(PRECIP_TYPE_THRESHOLD_ENV)
    if raw is not None and raw.strip() != "":
        try:
            return float(raw)
        except ValueError:
            pass

    env = _canonical_env(environ.get("DIGITAL_EARTH_ENV"))
    config_dir = _resolve_config_dir(environ)
    config_path = config_dir / f"{env}.json"
    if not config_path.is_file():
        return DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C

    try:
        data = json.loads(config_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C

    if not isinstance(data, dict):
        return DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C
    pipeline = data.get("pipeline")
    if not isinstance(pipeline, dict):
        return DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C

    value = pipeline.get("precip_type_temp_threshold_c")
    try:
        return float(value)
    except (TypeError, ValueError):
        return DEFAULT_PRECIP_TYPE_TEMP_THRESHOLD_C


def _find_variable(ds: xr.Dataset, candidates: Sequence[str]) -> Optional[str]:
    if not candidates:
        return None
    present = {name.lower(): name for name in ds.data_vars}
    for candidate in candidates:
        found = present.get(candidate.lower())
        if found is not None:
            return found
    return None


def _coerce_temperature_to_celsius(values: np.ndarray, *, units: str) -> np.ndarray:
    normalized = (units or "").strip().lower()
    if normalized in {"c", "°c", "degc", "deg_c", "degreec", "degrees_celsius"}:
        return values
    if normalized in {"k", "kelvin", "kelvins"}:
        return values - 273.15
    if normalized == "":
        finite = values[np.isfinite(values)]
        if finite.size:
            median = float(np.nanmedian(finite))
            if median > 100.0:
                return values - 273.15
        return values
    return values


def _precip_type_attrs(*, temp_threshold_c: float) -> dict[str, object]:
    return {
        "long_name": "Precipitation type",
        "flag_values": PRECIP_TYPE_FLAG_VALUES,
        "flag_meanings": PRECIP_TYPE_FLAG_MEANINGS,
        "temperature_threshold_c": float(temp_threshold_c),
    }


def derive_precip_type(
    ds: xr.Dataset,
    *,
    temp_threshold_c: float,
    ptype_names: Sequence[str] = ("ptype",),
    temperature_names: Sequence[str] = ("2t", "t2m", "air_temperature"),
) -> Optional[xr.DataArray]:
    ptype_name = _find_variable(ds, ptype_names)
    temp_name = _find_variable(ds, temperature_names)

    if ptype_name is None and temp_name is None:
        return None

    if all(dim in ds.dims for dim in ("time", "level", "lat", "lon")):
        dims = ("time", "level", "lat", "lon")
        shape = (
            int(ds.sizes["time"]),
            int(ds.sizes["level"]),
            int(ds.sizes["lat"]),
            int(ds.sizes["lon"]),
        )
    elif all(dim in ds.dims for dim in ("time", "lat", "lon")):
        dims = ("time", "lat", "lon")
        shape = (int(ds.sizes["time"]), int(ds.sizes["lat"]), int(ds.sizes["lon"]))
    else:
        return None

    out = np.full(shape, np.nan, dtype=np.float32)
    fallback_mask = np.ones(shape, dtype=bool)

    if ptype_name is not None:
        ptype = np.asarray(ds[ptype_name].values, dtype=np.float32)
        if ptype.shape != shape:
            return None
        valid = np.isfinite(ptype)
        codes = np.where(valid, np.rint(ptype), 0.0).astype(np.int32, copy=False)
        is_none = valid & (codes == 0)
        is_rain = valid & (codes == 1)
        is_snow = valid & (codes == 2)
        is_mix = valid & ((codes == 3) | (codes == 4))

        out = np.where(is_rain, PRECIP_TYPE_RAIN, out)
        out = np.where(is_snow, PRECIP_TYPE_SNOW, out)
        out = np.where(is_mix, PRECIP_TYPE_MIX, out)

        known = is_none | is_rain | is_snow | is_mix
        fallback_mask = ~known

    if temp_name is not None and np.any(fallback_mask):
        temp = np.asarray(ds[temp_name].values, dtype=np.float32)
        if temp.shape != shape:
            return None
        units = str(ds[temp_name].attrs.get("units") or "")
        temp_c = _coerce_temperature_to_celsius(temp.astype(np.float64), units=units)
        temp_ok = np.isfinite(temp_c)
        use = fallback_mask & temp_ok
        snow = use & (temp_c < temp_threshold_c)
        rain = use & ~snow
        out = np.where(snow, PRECIP_TYPE_SNOW, out)
        out = np.where(rain, PRECIP_TYPE_RAIN, out)

    return xr.DataArray(
        out.astype(np.float32, copy=False),
        dims=dims,
        name="precip_type",
        attrs=_precip_type_attrs(temp_threshold_c=temp_threshold_c),
    )


def ensure_precip_type(
    ds: xr.Dataset, *, temp_threshold_c: float, overwrite: bool = False
) -> xr.Dataset:
    if not overwrite and "precip_type" in ds.data_vars:
        return ds
    derived = derive_precip_type(ds, temp_threshold_c=float(temp_threshold_c))
    if derived is None:
        return ds
    return ds.assign(precip_type=derived)
