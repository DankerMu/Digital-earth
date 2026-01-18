from __future__ import annotations

from dataclasses import dataclass
from typing import Mapping, Optional, Sequence

import numpy as np
import xarray as xr

from datacube.errors import DataCubeValidationError
from datacube.missing import standardize_missing

_DIM_ALIASES: Mapping[str, Sequence[str]] = {
    "time": ("time", "Time", "TIME", "valid_time"),
    "lat": ("lat", "latitude", "LAT", "Latitude", "nav_lat", "y"),
    "lon": ("lon", "longitude", "LON", "Longitude", "nav_lon", "x"),
    "level": (
        "level",
        "lev",
        "LEV",
        "isobaricInhPa",
        "isobaricInPa",
        "pressure",
        "plev",
    ),
}


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


@dataclass(frozen=True)
class _AxisSpec:
    axis: str
    coord_name: str
    dim_name: str


def _resolve_axis(ds: xr.Dataset, axis: str, aliases: Sequence[str]) -> Optional[_AxisSpec]:
    dims = list(ds.dims)
    coords = list(ds.coords)

    found_dim = _find_axis_name(dims, aliases)
    found_coord = _find_axis_name(coords, aliases)

    if found_coord is not None:
        coord = ds[found_coord]
        if coord.ndim != 1:
            raise DataCubeValidationError(
                f"{axis} coordinate must be 1D; got {found_coord}.ndim={coord.ndim}"
            )
        dim_name = coord.dims[0]
        return _AxisSpec(axis=axis, coord_name=found_coord, dim_name=dim_name)

    if found_dim is not None:
        return _AxisSpec(axis=axis, coord_name=found_dim, dim_name=found_dim)

    return None


def _rename_dimension(ds: xr.Dataset, *, current: str, target: str) -> xr.Dataset:
    if current == target:
        return ds
    if target in ds.dims and current != target:
        raise DataCubeValidationError(
            f"Cannot rename dimension {current!r} to {target!r}; target already exists"
        )
    return ds.rename_dims({current: target})


def _rename_coord(ds: xr.Dataset, *, current: str, target: str) -> xr.Dataset:
    if current == target:
        return ds
    if target in ds.coords and current != target:
        raise DataCubeValidationError(
            f"Cannot rename coordinate {current!r} to {target!r}; target already exists"
        )
    return ds.rename_vars({current: target})


def _ensure_datetime64_time(ds: xr.Dataset) -> xr.Dataset:
    values = ds["time"].values
    if values.size == 0:
        raise DataCubeValidationError("time coordinate is empty")
    if not np.issubdtype(values.dtype, np.datetime64):
        raise DataCubeValidationError(
            f"time coordinate must be datetime64 after decoding; got dtype={values.dtype}"
        )
    ds = ds.assign_coords(time=np.asarray(values).astype("datetime64[s]"))
    return ds


def _normalize_level_units(level: xr.DataArray) -> xr.DataArray:
    units = str(level.attrs.get("units") or "").strip()
    values = np.asarray(level.values)
    if values.size == 0:
        return level
    if not np.issubdtype(values.dtype, np.number):
        return level

    values_f = values.astype(np.float64, copy=False)

    if units.lower() in {"pa", "pascal", "pascals"}:
        attrs = dict(level.attrs)
        attrs["units"] = "hPa"
        return xr.DataArray(
            (values_f / 100.0).astype(np.float32),
            dims=level.dims,
            name=level.name,
            attrs=attrs,
        )

    if units == "" and np.nanmax(values_f) > 2000.0:
        attrs = dict(level.attrs)
        attrs["units"] = "hPa"
        return xr.DataArray(
            (values_f / 100.0).astype(np.float32),
            dims=level.dims,
            name=level.name,
            attrs=attrs,
        )

    attrs = dict(level.attrs)
    if units:
        attrs.setdefault("units", units)
    return xr.DataArray(
        values_f.astype(np.float32),
        dims=level.dims,
        name=level.name,
        attrs=attrs,
    )


def normalize_datacube_dataset(ds: xr.Dataset) -> xr.Dataset:
    """Normalize a dataset into canonical DataCube form."""

    ds = ds.copy()

    required_axes = ("time", "lat", "lon")
    resolved: dict[str, _AxisSpec] = {}
    for axis in required_axes:
        spec = _resolve_axis(ds, axis, _DIM_ALIASES[axis])
        if spec is None:
            raise DataCubeValidationError(
                f"Missing required {axis!r} dimension/coordinate; "
                f"expected one of {list(_DIM_ALIASES[axis])}"
            )
        resolved[axis] = spec

    level_spec = _resolve_axis(ds, "level", _DIM_ALIASES["level"])

    # Rename dimensions first to avoid coord+dim collisions.
    for axis, spec in resolved.items():
        ds = _rename_dimension(ds, current=spec.dim_name, target=axis)

    if level_spec is not None:
        ds = _rename_dimension(ds, current=level_spec.dim_name, target="level")

    # Rename coordinates/variables after dimension normalization.
    for axis, spec in resolved.items():
        ds = _rename_coord(ds, current=spec.coord_name, target=axis)

    if level_spec is not None:
        ds = _rename_coord(ds, current=level_spec.coord_name, target="level")

    if "level" not in ds.dims:
        ds = ds.expand_dims({"level": [0.0]})
        ds["level"].attrs = {"long_name": "surface", "units": "1"}

    if ds["lat"].ndim != 1 or ds["lon"].ndim != 1 or ds["level"].ndim != 1:
        raise DataCubeValidationError("Only 1D lat/lon/level coordinates are supported")

    ds = _ensure_datetime64_time(ds)

    ds = ds.assign_coords(
        lat=np.asarray(ds["lat"].values, dtype=np.float32),
        lon=np.asarray(ds["lon"].values, dtype=np.float32),
    )
    ds = ds.assign_coords(level=_normalize_level_units(ds["level"]))

    allowed_dims = {"time", "level", "lat", "lon"}
    for name in list(ds.data_vars):
        da = ds[name]
        extra = [dim for dim in da.dims if dim not in allowed_dims]
        if extra:
            raise DataCubeValidationError(
                f"Variable {name!r} has unsupported dims={list(da.dims)}; extra={extra}"
            )

        expanded = da
        if "time" not in expanded.dims:
            expanded = expanded.expand_dims({"time": ds["time"].values})
        if "level" not in expanded.dims:
            expanded = expanded.expand_dims({"level": ds["level"].values})
        expanded = expanded.transpose("time", "level", "lat", "lon")
        expanded = standardize_missing(expanded, drop_attrs=True)
        attrs = dict(da.attrs)
        attrs.pop("_FillValue", None)
        attrs.pop("missing_value", None)
        expanded.attrs = attrs
        ds[name] = expanded

    ds.attrs = dict(ds.attrs)
    ds.attrs.setdefault("datacube_schema_version", 1)
    ds.attrs.setdefault("datacube_missing", "NaN")

    return ds
