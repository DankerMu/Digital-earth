from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path
from typing import Any, Mapping, Optional, Sequence, Union

import numpy as np
import xarray as xr
from pydantic import BaseModel, ConfigDict, Field

from cldas.config import CldasMappingConfig, VariableMapping, get_cldas_mapping_config
from cldas.errors import (
    CldasNetcdfMissingDataError,
    CldasNetcdfOpenError,
    CldasNetcdfStructureError,
    CldasNetcdfVariableMissingError,
    CldasNetcdfWriteError,
)


class AxisIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    count: int
    min: float
    max: float


class VariableIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_var: str
    unit: str
    dtype: str


class CldasInternalFileIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    product: str
    resolution: str
    source_path: str
    dataset_path: str
    times: list[str]
    dims: dict[str, int]
    lat: AxisIndex
    lon: AxisIndex
    variables: dict[str, VariableIndex]


class CollectionItem(BaseModel):
    model_config = ConfigDict(extra="forbid")

    time: str
    dataset_path: str
    index_path: str


class CldasInternalCollectionIndex(BaseModel):
    model_config = ConfigDict(extra="forbid")

    schema_version: int = 1
    product: str
    resolution: str
    items: list[CollectionItem] = Field(default_factory=list)

    def upsert(self, item: CollectionItem) -> None:
        existing = {it.time: it for it in self.items}
        existing[item.time] = item
        self.items = [existing[key] for key in sorted(existing)]


@dataclass(frozen=True)
class CldasImportResult:
    dataset_path: Path
    file_index_path: Path
    collection_index_path: Path
    times: list[str]
    variables: list[str]


_DIM_ALIASES: Mapping[str, Sequence[str]] = {
    "time": ("time", "Time", "TIME"),
    "lat": ("lat", "latitude", "LAT", "Latitude", "nav_lat"),
    "lon": ("lon", "longitude", "LON", "Longitude", "nav_lon"),
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


def _normalize_dims(ds: xr.Dataset) -> xr.Dataset:
    dim_names = list(ds.dims)
    coord_names = list(ds.coords)
    rename_map: dict[str, str] = {}

    for target, aliases in _DIM_ALIASES.items():
        found = _find_axis_name(dim_names, aliases) or _find_axis_name(
            coord_names, aliases
        )
        if found is None:
            raise CldasNetcdfStructureError(
                f"Missing required dimension/coordinate {target!r}; "
                f"expected one of {list(aliases)}"
            )
        if found != target:
            rename_map[found] = target

    if rename_map:
        ds = ds.rename(rename_map)

    for dim in ("time", "lat", "lon"):
        if dim not in ds.dims:
            raise CldasNetcdfStructureError(
                f"Required dimension {dim!r} must exist after normalization; "
                f"found dims={list(ds.dims)}"
            )

    if ds["lat"].ndim != 1 or ds["lon"].ndim != 1:
        raise CldasNetcdfStructureError("Only 1D lat/lon coordinates are supported")

    return ds


def _format_time_iso(value: np.datetime64) -> str:
    text = np.datetime_as_string(value, unit="s")
    if text.endswith("Z"):
        return text
    return f"{text}Z"


def _format_time_filename(value: np.datetime64) -> str:
    text = np.datetime_as_string(value, unit="s")
    cleaned = text.replace("-", "").replace(":", "")
    return f"{cleaned}Z"


def _extract_times(ds: xr.Dataset) -> list[np.datetime64]:
    raw = ds["time"].values
    if raw.size == 0:
        raise CldasNetcdfStructureError("time coordinate is empty")
    if not np.issubdtype(raw.dtype, np.datetime64):
        raise CldasNetcdfStructureError(
            f"time coordinate must be datetime64 after decoding; got dtype={raw.dtype}"
        )
    raw_s = np.asarray(raw).astype("datetime64[s]")
    return [np.datetime64(value, "s") for value in raw_s]


def _missing_mask(da: xr.DataArray) -> xr.DataArray:
    mask = da.isnull()
    for key in ("_FillValue", "missing_value"):
        raw_value = da.attrs.get(key)
        if raw_value is None:
            continue
        if isinstance(raw_value, (list, tuple, np.ndarray)):
            values = list(raw_value)
        else:
            values = [raw_value]
        for value in values:
            if isinstance(value, (int, float, np.integer, np.floating)) and np.isfinite(
                float(value)
            ):
                mask = mask | (da == value)
    return mask


def _fill_nan_edges_along_axis(values: np.ndarray, *, axis: int) -> np.ndarray:
    if values.size == 0:
        return values
    if not np.issubdtype(values.dtype, np.floating):
        return values
    if not np.isnan(values).any():
        return values

    moved = np.moveaxis(values, axis, -1)
    length = moved.shape[-1]
    flat = moved.reshape(-1, length)
    mask = np.isfinite(flat)
    any_valid = mask.any(axis=1)
    if not any_valid.any():
        return values

    first = mask.argmax(axis=1)
    last = length - 1 - mask[:, ::-1].argmax(axis=1)

    rows = np.arange(flat.shape[0])
    left_vals = flat[rows, first]
    right_vals = flat[rows, last]

    x = np.arange(length)[None, :]
    first_b = first[:, None]
    last_b = last[:, None]
    any_valid_b = any_valid[:, None]

    fill_left = (x < first_b) & any_valid_b
    fill_right = (x > last_b) & any_valid_b

    filled = flat.copy()
    left_matrix = np.broadcast_to(left_vals[:, None], filled.shape)
    right_matrix = np.broadcast_to(right_vals[:, None], filled.shape)

    filled[fill_left] = left_matrix[fill_left]
    filled[fill_right] = right_matrix[fill_right]

    reshaped = filled.reshape(moved.shape)
    return np.moveaxis(reshaped, -1, axis)


def _interpolate_missing(da: xr.DataArray) -> xr.DataArray:
    if not da.isnull().any().item():
        return da

    result = da
    for dim in ("lon", "lat", "time"):
        if dim not in result.dims or result.sizes.get(dim, 0) <= 1:
            continue
        result = result.interpolate_na(
            dim=dim, method="linear", use_coordinate=False, keep_attrs=True
        )
        axis = result.get_axis_num(dim)
        result = xr.DataArray(
            _fill_nan_edges_along_axis(result.values, axis=axis),
            coords=result.coords,
            dims=result.dims,
            attrs=result.attrs,
            name=result.name,
        )

    if result.isnull().any().item():
        raise CldasNetcdfMissingDataError(
            "Missing values remain after interpolate strategy"
        )
    return result


def _apply_mapping(da: xr.DataArray, mapping: VariableMapping) -> xr.DataArray:
    expected_dims = {"time", "lat", "lon"}
    if set(da.dims) != expected_dims:
        raise CldasNetcdfStructureError(
            f"Variable {mapping.source_var!r} must have dims {sorted(expected_dims)}; "
            f"got dims={list(da.dims)}"
        )

    da = da.transpose("time", "lat", "lon")
    mask = _missing_mask(da)

    scale = float(mapping.scale or 1.0)
    offset = float(mapping.offset or 0.0)
    converted = xr.where(mask, np.nan, da.astype(np.float64) * scale + offset)

    if mapping.missing is None:
        raise CldasNetcdfStructureError(
            f"Variable mapping for {mapping.source_var!r} is missing 'missing' spec"
        )

    if mapping.missing.strategy == "fill_value":
        if mapping.missing.fill_value is None:
            raise CldasNetcdfStructureError(
                f"missing.fill_value is required for {mapping.source_var!r}"
            )
        converted = converted.fillna(float(mapping.missing.fill_value))
    elif mapping.missing.strategy == "interpolate":
        converted = _interpolate_missing(converted)
    else:
        raise CldasNetcdfStructureError(
            f"Unsupported missing.strategy={mapping.missing.strategy!r}"
        )

    converted = converted.astype(np.float32)
    converted.attrs = dict(converted.attrs)
    converted.attrs["units"] = mapping.unit
    converted.name = mapping.internal_var
    return converted


def parse_cldas_netcdf_hourly(
    source_path: Union[str, Path],
    *,
    product: str,
    resolution: str,
    mapping_config: Optional[CldasMappingConfig] = None,
    engine: Optional[str] = None,
) -> xr.Dataset:
    path = Path(source_path)
    try:
        with xr.open_dataset(
            path, engine=engine, decode_cf=True, mask_and_scale=False
        ) as ds:
            ds = ds.load()
    except Exception as exc:  # noqa: BLE001
        raise CldasNetcdfOpenError(f"Failed to open NetCDF: {path}") from exc

    ds = _normalize_dims(ds)

    mapping_config = mapping_config or get_cldas_mapping_config()
    source_to_mapping = mapping_config.variables_for(
        product=product, resolution=resolution
    )

    internal_vars: dict[str, xr.DataArray] = {}
    for source_var, mapping in source_to_mapping.items():
        if source_var not in ds.data_vars:
            raise CldasNetcdfVariableMissingError(
                f"Missing variable {source_var!r} in {path.name}; "
                f"available={sorted(ds.data_vars)}"
            )
        internal_vars[mapping.internal_var] = _apply_mapping(ds[source_var], mapping)

    times = _extract_times(ds)
    output = xr.Dataset(
        internal_vars,
        coords={
            "time": ("time", times),
            "lat": ("lat", ds["lat"].values),
            "lon": ("lon", ds["lon"].values),
        },
        attrs={
            "product": product,
            "resolution": resolution,
            "source_path": str(path.resolve()),
        },
    )
    return output


def _axis_index(coord: xr.DataArray, *, name: str) -> AxisIndex:
    values = coord.values.astype(np.float64)
    return AxisIndex(
        name=name,
        count=int(values.size),
        min=float(np.nanmin(values)),
        max=float(np.nanmax(values)),
    )


def _build_file_index(
    *,
    ds: xr.Dataset,
    product: str,
    resolution: str,
    source_path: Path,
    dataset_path: Path,
    source_to_mapping: Mapping[str, VariableMapping],
) -> CldasInternalFileIndex:
    times_raw = np.asarray(ds["time"].values).astype("datetime64[s]")
    times = [_format_time_iso(np.datetime64(t, "s")) for t in times_raw]

    variables: dict[str, VariableIndex] = {}
    for source_var, mapping in source_to_mapping.items():
        internal = mapping.internal_var
        variables[internal] = VariableIndex(
            source_var=source_var, unit=mapping.unit, dtype=str(ds[internal].dtype)
        )

    return CldasInternalFileIndex(
        product=product,
        resolution=resolution,
        source_path=str(source_path.resolve()),
        dataset_path=str(dataset_path.name),
        times=times,
        dims={k: int(v) for k, v in ds.sizes.items()},
        lat=_axis_index(ds["lat"], name="lat"),
        lon=_axis_index(ds["lon"], name="lon"),
        variables=variables,
    )


def _load_collection_index(path: Path) -> Optional[CldasInternalCollectionIndex]:
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return CldasInternalCollectionIndex.model_validate(data)
    except Exception as exc:  # noqa: BLE001
        raise CldasNetcdfWriteError(f"Failed to read collection index: {path}") from exc


def _write_json(path: Path, payload: Any) -> None:
    try:
        path.write_text(
            json.dumps(payload, ensure_ascii=False, indent=2, sort_keys=True) + "\n",
            encoding="utf-8",
        )
    except Exception as exc:  # noqa: BLE001
        raise CldasNetcdfWriteError(f"Failed to write JSON: {path}") from exc


def write_cldas_internal_files(
    ds: xr.Dataset,
    *,
    output_dir: Union[str, Path],
    product: str,
    resolution: str,
    source_path: Union[str, Path],
    mapping_config: Optional[CldasMappingConfig] = None,
    engine: Optional[str] = None,
) -> CldasImportResult:
    out_root = Path(output_dir) / product / resolution
    out_root.mkdir(parents=True, exist_ok=True)

    mapping_config = mapping_config or get_cldas_mapping_config()
    source_to_mapping = mapping_config.variables_for(
        product=product, resolution=resolution
    )

    times = _extract_times(ds)
    if len(times) == 1:
        stem = _format_time_filename(times[0])
    else:
        stem = f"{_format_time_filename(times[0])}_{_format_time_filename(times[-1])}"

    dataset_path = out_root / f"{stem}.nc"
    file_index_path = out_root / f"{stem}.index.json"
    collection_index_path = out_root / "index.json"

    try:
        ds.to_netcdf(dataset_path, engine=engine)
    except Exception as exc:  # noqa: BLE001
        raise CldasNetcdfWriteError(
            f"Failed to write internal dataset: {dataset_path}"
        ) from exc

    source_path_p = Path(source_path)
    file_index = _build_file_index(
        ds=ds,
        product=product,
        resolution=resolution,
        source_path=source_path_p,
        dataset_path=dataset_path,
        source_to_mapping=source_to_mapping,
    )
    _write_json(file_index_path, file_index.model_dump())

    collection = _load_collection_index(
        collection_index_path
    ) or CldasInternalCollectionIndex(product=product, resolution=resolution)
    collection.upsert(
        CollectionItem(
            time=file_index.times[0],
            dataset_path=dataset_path.name,
            index_path=file_index_path.name,
        )
    )
    _write_json(collection_index_path, collection.model_dump())

    return CldasImportResult(
        dataset_path=dataset_path,
        file_index_path=file_index_path,
        collection_index_path=collection_index_path,
        times=file_index.times,
        variables=sorted(ds.data_vars),
    )


def import_cldas_netcdf_hourly(
    source_path: Union[str, Path],
    *,
    output_dir: Union[str, Path],
    product: str,
    resolution: str,
    mapping_config: Optional[CldasMappingConfig] = None,
    engine: Optional[str] = None,
) -> CldasImportResult:
    ds = parse_cldas_netcdf_hourly(
        source_path,
        product=product,
        resolution=resolution,
        mapping_config=mapping_config,
        engine=engine,
    )
    return write_cldas_internal_files(
        ds,
        output_dir=output_dir,
        product=product,
        resolution=resolution,
        source_path=source_path,
        mapping_config=mapping_config,
        engine=engine,
    )
