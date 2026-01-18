from __future__ import annotations

from typing import Optional

import numpy as np
import xarray as xr


class WindDerivationError(RuntimeError):
    pass


def _normalize_units(value: object) -> str:
    return str(value or "").strip()


def derive_wind_speed(
    u: xr.DataArray, v: xr.DataArray, *, name: str = "wind_speed"
) -> xr.DataArray:
    """Derive wind speed from wind components.

    Parameters
    ----------
    u:
        Eastward wind component.
    v:
        Northward wind component.

    Returns
    -------
    xr.DataArray
        Wind speed = sqrt(u^2 + v^2).
    """

    try:
        u_aligned, v_aligned = xr.align(u, v, join="exact")
    except ValueError as exc:
        raise WindDerivationError("u and v must share identical coordinates") from exc

    u_f = u_aligned.astype(np.float32, copy=False)
    v_f = v_aligned.astype(np.float32, copy=False)
    speed = np.hypot(u_f, v_f).astype(np.float32, copy=False)

    units_u = _normalize_units(u_f.attrs.get("units"))
    units_v = _normalize_units(v_f.attrs.get("units"))
    units: Optional[str] = units_u if units_u and units_u == units_v else None

    attrs: dict[str, object] = {}
    if units is not None:
        attrs["units"] = units
    attrs["long_name"] = "Wind speed"
    attrs["standard_name"] = "wind_speed"

    speed = speed.rename(name)
    speed.attrs = attrs
    return speed


def derive_wind_dir(
    u: xr.DataArray, v: xr.DataArray, *, name: str = "wind_dir"
) -> xr.DataArray:
    """Derive wind direction from wind components.

    Definition
    ----------
    `wind_dir` is the bearing of the wind vector, measured from geographic North and
    increasing clockwise:

    - 0°  = blowing toward North (u=0, v>0)
    - 90° = blowing toward East  (u>0, v=0)

    Calculation follows the provided spec:
        wind_dir = atan2(u, v)  (converted to degrees and wrapped to [0, 360))
    """

    try:
        u_aligned, v_aligned = xr.align(u, v, join="exact")
    except ValueError as exc:
        raise WindDerivationError("u and v must share identical coordinates") from exc

    u_f = u_aligned.astype(np.float32, copy=False)
    v_f = v_aligned.astype(np.float32, copy=False)

    angle_rad = np.arctan2(u_f, v_f)
    angle_deg = np.degrees(angle_rad)
    direction = ((angle_deg + 360.0) % 360.0).astype(np.float32, copy=False)

    attrs: dict[str, object] = {
        "units": "degree",
        "long_name": "Wind direction",
        "comment": "Bearing from North, clockwise; computed as degrees(atan2(u, v)) wrapped to [0, 360).",
    }

    direction = direction.rename(name)
    direction.attrs = attrs
    return direction


def maybe_add_wind_speed_dir(
    ds: xr.Dataset,
    *,
    u_name: str,
    v_name: str,
    speed_name: str = "wind_speed",
    dir_name: str = "wind_dir",
    overwrite: bool = False,
) -> xr.Dataset:
    """Attach derived wind speed/direction variables to a dataset.

    If either `u_name` or `v_name` is missing, the dataset is returned unchanged.
    """

    if u_name not in ds.data_vars or v_name not in ds.data_vars:
        return ds

    if not overwrite and (speed_name in ds.data_vars or dir_name in ds.data_vars):
        return ds

    speed = derive_wind_speed(ds[u_name], ds[v_name], name=speed_name)
    direction = derive_wind_dir(ds[u_name], ds[v_name], name=dir_name)

    out = ds.copy()
    out[speed_name] = speed
    out[dir_name] = direction
    return out
