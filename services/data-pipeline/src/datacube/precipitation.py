from __future__ import annotations

from typing import Optional

import numpy as np
import xarray as xr


def _infer_time_dim(da: xr.DataArray) -> str:
    for candidate in ("time", "valid_time"):
        if candidate in da.dims:
            return candidate
    raise ValueError(
        "Unable to infer time dimension for precipitation differencing; "
        f"expected one of ('time', 'valid_time'), got dims={list(da.dims)}"
    )


def precipitation_amount_from_accumulation(
    accumulated: xr.DataArray,
    *,
    time_dim: Optional[str] = None,
    initial: Optional[float] = 0.0,
    clamp_negative: bool = True,
) -> xr.DataArray:
    """Convert accumulated precipitation to per-interval amounts via differencing.

    The amount at each timestamp is computed as the difference between adjacent
    valid times. The first element (t=0) has no previous value, so it is filled
    by subtracting `initial` (default: 0.0), i.e. `accumulated[0] - initial`.
    Negative differences are clipped to 0 when `clamp_negative` is True.
    """

    dim = time_dim or _infer_time_dim(accumulated)
    if dim not in accumulated.dims:
        raise ValueError(
            f"precipitation accumulation missing time_dim={dim!r}; dims={list(accumulated.dims)}"
        )

    count = int(accumulated.sizes.get(dim, 0))
    if count == 0:
        out = accumulated.copy()
        out.attrs = dict(accumulated.attrs)
        return out.astype(np.float32, copy=False)

    diff = accumulated.diff(dim)

    first_slice = accumulated.isel({dim: slice(0, 1)})
    if initial is None:
        first = xr.full_like(first_slice, np.nan)
    else:
        first = first_slice - float(initial)

    out = xr.concat([first, diff], dim=dim)
    out.attrs = dict(accumulated.attrs)

    if clamp_negative:
        out = out.clip(min=0.0)

    return out.astype(np.float32, copy=False)


def add_precipitation_amount_from_tp(
    ds: xr.Dataset,
    *,
    tp_var: str = "tp",
    out_var: str = "precipitation_amount",
    time_dim: Optional[str] = None,
    initial: Optional[float] = 0.0,
    clamp_negative: bool = True,
    overwrite: bool = False,
) -> xr.Dataset:
    """Add a derived precipitation amount variable by differencing cumulative `tp`."""

    if tp_var not in ds.data_vars:
        return ds
    if out_var in ds.data_vars and not overwrite:
        return ds

    tp = ds[tp_var]
    precip = precipitation_amount_from_accumulation(
        tp,
        time_dim=time_dim,
        initial=initial,
        clamp_negative=clamp_negative,
    )

    precip = precip.rename(out_var)
    attrs = dict(precip.attrs)
    attrs.setdefault("long_name", "precipitation amount over the previous interval")
    precip.attrs = attrs

    out = ds.copy()
    out[out_var] = precip
    return out
