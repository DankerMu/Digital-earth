from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import xarray as xr

from datacube.storage import open_datacube


def _as_iso(dt: np.datetime64) -> str:
    text = np.datetime_as_string(dt.astype("datetime64[s]"), unit="s")
    if text.endswith("Z"):
        return text
    return f"{text}Z"


def inspect_datacube(
    path: Union[str, Path],
    *,
    format: Optional[str] = None,
    engine: Optional[str] = None,
) -> dict[str, Any]:
    ds = open_datacube(path, format=format, engine=engine)
    try:
        dims = {name: int(size) for name, size in ds.sizes.items()}
        vars_summary: dict[str, dict[str, Any]] = {}
        for name in ds.data_vars:
            da = ds[name]
            values = np.asarray(da.values)
            vars_summary[name] = {
                "dims": list(da.dims),
                "dtype": str(values.dtype),
                "nan_count": int(np.isnan(values).sum())
                if np.issubdtype(values.dtype, np.floating)
                else 0,
                "min": float(np.nanmin(values))
                if np.issubdtype(values.dtype, np.number) and np.isfinite(values).any()
                else None,
                "max": float(np.nanmax(values))
                if np.issubdtype(values.dtype, np.number) and np.isfinite(values).any()
                else None,
            }

        times: list[str] = []
        if "time" in ds.coords:
            raw = np.asarray(ds["time"].values)
            if raw.size:
                times = [_as_iso(value) for value in raw.astype("datetime64[s]")]

        return {
            "dims": dims,
            "coords": {name: list(ds[name].values.tolist()) for name in ("level",) if name in ds.coords},
            "times": times,
            "variables": vars_summary,
        }
    finally:
        try:
            ds.close()
        except Exception:  # noqa: BLE001
            pass

