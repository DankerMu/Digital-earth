from __future__ import annotations

from typing import Any, Iterable, Optional

import numpy as np
import xarray as xr


def _iter_missing_sentinels(value: Any) -> Iterable[float]:
    if value is None:
        return
    if isinstance(value, np.ndarray):
        if value.size == 0:
            return
        value = value.tolist()
    if isinstance(value, (list, tuple)):
        for item in value:
            yield from _iter_missing_sentinels(item)
        return

    if isinstance(value, (int, float, np.integer, np.floating)):
        parsed = float(value)
        if np.isfinite(parsed):
            yield parsed


def missing_mask(
    da: xr.DataArray,
    *,
    extra_sentinels: Optional[Iterable[float]] = None,
) -> xr.DataArray:
    mask = da.isnull()

    candidates = []
    for container in (getattr(da, "encoding", {}), getattr(da, "attrs", {})):
        candidates.extend([container.get("_FillValue"), container.get("missing_value")])
    if extra_sentinels is not None:
        candidates.extend(list(extra_sentinels))

    for candidate in candidates:
        for sentinel in _iter_missing_sentinels(candidate):
            mask = mask | (da == sentinel)
    return mask


def standardize_missing(
    da: xr.DataArray,
    *,
    extra_sentinels: Optional[Iterable[float]] = None,
    drop_attrs: bool = True,
) -> xr.DataArray:
    mask = missing_mask(da, extra_sentinels=extra_sentinels)
    out = da.where(~mask)

    out = out.astype(np.float32)
    out.attrs = dict(out.attrs)
    out.encoding = dict(getattr(out, "encoding", {}))

    if drop_attrs:
        for key in ("_FillValue", "missing_value"):
            out.attrs.pop(key, None)
            out.encoding.pop(key, None)

    return out
