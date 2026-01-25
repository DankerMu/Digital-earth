from __future__ import annotations

from pathlib import Path
from typing import Any, Optional, Union

import numpy as np
import xarray as xr

from datacube.core import DataCube
from datacube.errors import DataCubeDecodeError


def _infer_source_format(path: Path) -> str:
    suffix = path.suffix.lower()
    if suffix in {".nc", ".netcdf"}:
        return "netcdf"
    if suffix in {".grib", ".grb", ".grib2", ".grb2"}:
        return "grib"
    raise DataCubeDecodeError(f"Unsupported source file type: {path.name}")


def _load_dataset(ds: xr.Dataset) -> xr.Dataset:
    # Ensure the returned dataset is independent from any file handles.
    ds.load()
    try:
        ds.close()
    except Exception:  # noqa: BLE001
        pass
    return ds


def decode_netcdf(
    source_path: Union[str, Path],
    *,
    engine: Optional[str] = None,
) -> DataCube:
    path = Path(source_path)
    try:
        ds = xr.open_dataset(
            path,
            engine=engine,
            decode_cf=True,
            mask_and_scale=True,
        )
    except FileNotFoundError as exc:
        raise DataCubeDecodeError(f"NetCDF file not found: {path}") from exc
    except Exception as exc:  # noqa: BLE001
        raise DataCubeDecodeError(f"Failed to open NetCDF: {path}") from exc

    return DataCube.from_dataset(_load_dataset(ds))


def decode_grib(
    source_path: Union[str, Path],
    *,
    engine: str = "cfgrib",
    subset: str = "surface",
) -> DataCube:
    """Decode a GRIB file into a normalized DataCube.

    Notes
    -----
    ECMWF forecast GRIBs in this repository commonly bundle multiple grids:

    - Surface fields on a global grid (e.g. t2m/tcc/tp/10u/10v)
    - Pressure-level fields on a regional grid (e.g. t/u/v on isobaricInhPa)

    A single DataCube must have a single lat/lon grid, so callers may request a
    specific subset to decode.
    """

    def _open_cfgrib_subset(*, filter_by_keys: dict[str, Any]) -> Optional[xr.Dataset]:
        """Open a GRIB subset using cfgrib filter_by_keys.

        Returns None when the filter matches no messages.
        """

        try:
            ds = xr.open_dataset(
                path,
                engine="cfgrib",
                decode_cf=True,
                backend_kwargs={
                    "filter_by_keys": filter_by_keys,
                    # Avoid leaving *.idx files next to the GRIB when running locally.
                    "indexpath": "",
                    # Prefer a single valid_time axis instead of time+step.
                    "time_dims": ("valid_time",),
                },
            )
        except Exception:  # noqa: BLE001
            raise

        if not ds.data_vars:
            try:
                ds.close()
            except Exception:  # noqa: BLE001
                pass
            return None
        return ds

    def _extract_valid_time_value(ds: xr.Dataset) -> np.datetime64:
        if "valid_time" in ds.coords:
            value = np.asarray(ds["valid_time"].values)
            if value.ndim == 0:
                return np.datetime64(value)

        if "time" in ds.coords and "step" in ds.coords:
            value = np.asarray((ds["time"] + ds["step"]).values)
            if value.ndim == 0:
                return np.datetime64(value)

        if "time" in ds.coords:
            value = np.asarray(ds["time"].values)
            if value.ndim == 0:
                return np.datetime64(value)

        raise DataCubeDecodeError(
            "Failed to decode GRIB: missing valid_time/time coordinate"
        )

    def _ensure_time_dim(ds: xr.Dataset) -> xr.Dataset:
        """Ensure the dataset has a 1D time dimension for DataCube normalization."""

        if "valid_time" in ds.dims:
            out = ds.rename_dims({"valid_time": "time"})
            if "valid_time" in out.coords:
                out = out.rename_vars({"valid_time": "time"})
            return out

        if "time" in ds.dims and "step" not in ds.dims:
            return ds

        if (
            "step" in ds.dims
            and "time" in ds.dims
            and int(ds.sizes.get("time", 0)) == 1
        ):
            ds = ds.isel(time=0, drop=True)

        if "step" in ds.dims:
            # cfgrib uses step for forecast lead time; convert to time=valid_time.
            time_values = np.asarray(_extract_valid_time_value(ds))
            if time_values.ndim == 0:
                time_values = np.asarray([time_values])
            out = ds.rename_dims({"step": "time"})
            out = out.drop_vars("step", errors="ignore")
            return out.assign_coords(time=time_values)

        # Scalar forecast files often expose valid_time as a scalar coordinate.
        time_value = _extract_valid_time_value(ds)
        return ds.expand_dims(time=[time_value]).assign_coords(time=[time_value])

    def _keep_single_var(ds: xr.Dataset, *, preferred: str | None = None) -> xr.Dataset:
        if preferred is not None and preferred in ds.data_vars:
            return ds[[preferred]]
        if len(ds.data_vars) == 1:
            return ds[[next(iter(ds.data_vars))]]
        available = ", ".join(sorted(ds.data_vars))
        raise DataCubeDecodeError(
            "Failed to decode GRIB: filter returned multiple variables "
            f"(preferred={preferred!r}, available=[{available}])"
        )

    def _close_quietly(ds: xr.Dataset) -> None:
        try:
            ds.close()
        except Exception:  # noqa: BLE001
            pass

    subset_key = str(subset or "").strip().lower()
    if subset_key in {"sfc"}:
        subset_key = "surface"
    if subset_key in {"rh", "humidity", "isobaric_rh", "isobaric-humidity"}:
        subset_key = "isobaric_rh"
    if subset_key not in {"surface", "isobaric", "isobaric_rh"}:
        raise ValueError(
            f"subset must be one of: surface, isobaric, humidity (got {subset!r})"
        )

    path = Path(source_path)
    try:
        if engine != "cfgrib":
            ds = xr.open_dataset(path, engine=engine, decode_cf=True)
            return DataCube.from_dataset(_load_dataset(ds))

        subsets: list[xr.Dataset] = []

        if subset_key == "surface":
            temperature: Optional[xr.Dataset] = None
            for keys in ({"shortName": "2t"}, {"shortName": "t2m"}):
                candidate = _open_cfgrib_subset(filter_by_keys=keys)
                if candidate is None:
                    continue
                temperature = _keep_single_var(candidate, preferred="t2m")
                break
            if temperature is not None:
                subsets.append(_ensure_time_dim(temperature))

            cloud = _open_cfgrib_subset(filter_by_keys={"shortName": "tcc"})
            if cloud is not None:
                subsets.append(
                    _ensure_time_dim(_keep_single_var(cloud, preferred="tcc"))
                )

            precip = _open_cfgrib_subset(filter_by_keys={"shortName": "tp"})
            if precip is not None:
                subsets.append(
                    _ensure_time_dim(_keep_single_var(precip, preferred="tp"))
                )

            precip_type = _open_cfgrib_subset(filter_by_keys={"shortName": "ptype"})
            if precip_type is not None:
                subsets.append(
                    _ensure_time_dim(_keep_single_var(precip_type, preferred="ptype"))
                )

            wind_u10 = _open_cfgrib_subset(filter_by_keys={"shortName": "10u"})
            wind_v10 = _open_cfgrib_subset(filter_by_keys={"shortName": "10v"})
            if wind_u10 is not None and wind_v10 is not None:
                u10 = _ensure_time_dim(_keep_single_var(wind_u10, preferred="u10"))
                v10 = _ensure_time_dim(_keep_single_var(wind_v10, preferred="v10"))
                u10 = u10.rename_vars({"u10": "eastward_wind_10m"})
                v10 = v10.rename_vars({"v10": "northward_wind_10m"})
                subsets.extend([u10, v10])
            else:
                if wind_u10 is not None:
                    _close_quietly(wind_u10)
                if wind_v10 is not None:
                    _close_quietly(wind_v10)

                wind_u = _open_cfgrib_subset(
                    filter_by_keys={
                        "shortName": "u",
                        "typeOfLevel": "heightAboveGround",
                        "level": 10,
                    }
                )
                wind_v = _open_cfgrib_subset(
                    filter_by_keys={
                        "shortName": "v",
                        "typeOfLevel": "heightAboveGround",
                        "level": 10,
                    }
                )
                if wind_u is not None and wind_v is not None:
                    subsets.append(
                        _ensure_time_dim(_keep_single_var(wind_u, preferred="u"))
                    )
                    subsets.append(
                        _ensure_time_dim(_keep_single_var(wind_v, preferred="v"))
                    )
                else:
                    if wind_u is not None:
                        _close_quietly(wind_u)
                    if wind_v is not None:
                        _close_quietly(wind_v)
        elif subset_key == "isobaric":
            temperature_pl = _open_cfgrib_subset(
                filter_by_keys={
                    "shortName": "t",
                    "typeOfLevel": "isobaricInhPa",
                }
            )
            if temperature_pl is not None:
                subsets.append(
                    _ensure_time_dim(_keep_single_var(temperature_pl, preferred="t"))
                )

            wind_u = _open_cfgrib_subset(
                filter_by_keys={
                    "shortName": "u",
                    "typeOfLevel": "isobaricInhPa",
                }
            )
            wind_v = _open_cfgrib_subset(
                filter_by_keys={
                    "shortName": "v",
                    "typeOfLevel": "isobaricInhPa",
                }
            )
            if wind_u is not None and wind_v is not None:
                subsets.append(
                    _ensure_time_dim(_keep_single_var(wind_u, preferred="u"))
                )
                subsets.append(
                    _ensure_time_dim(_keep_single_var(wind_v, preferred="v"))
                )
            else:
                if wind_u is not None:
                    _close_quietly(wind_u)
                if wind_v is not None:
                    _close_quietly(wind_v)
        else:
            rh_pl = _open_cfgrib_subset(
                filter_by_keys={
                    "shortName": "r",
                    "typeOfLevel": "isobaricInhPa",
                }
            )
            if rh_pl is not None:
                subsets.append(_ensure_time_dim(_keep_single_var(rh_pl, preferred="r")))

        if not subsets:
            if subset_key == "surface":
                raise DataCubeDecodeError(
                    "Failed to decode GRIB: no supported surface variables found "
                    "(expected t2m/2t, tcc, tp, ptype, 10u/10v or u/v)"
                )
            if subset_key == "isobaric":
                raise DataCubeDecodeError(
                    "Failed to decode GRIB: no supported isobaric variables found "
                    "(expected t/u/v on isobaricInhPa)"
                )
            raise DataCubeDecodeError(
                "Failed to decode GRIB: no supported humidity variables found "
                "(expected r on isobaricInhPa)"
            )

        merged = xr.merge(
            subsets,
            join="exact",
            compat="override",
            # Preserve variable attrs (e.g. units) for downstream normalization.
            combine_attrs="override",
        )
        try:
            merged.load()
        finally:
            for item in subsets:
                _close_quietly(item)

        return DataCube.from_dataset(merged)
    except FileNotFoundError as exc:
        raise DataCubeDecodeError(f"GRIB file not found: {path}") from exc
    except (ModuleNotFoundError, ImportError) as exc:
        missing_name = getattr(exc, "name", "") or ""
        message = str(exc).lower()
        if engine == "cfgrib" and (
            missing_name in {"cfgrib", "eccodes"} or "eccodes" in message
        ):
            raise DataCubeDecodeError(
                "GRIB decoding requires the optional dependency `cfgrib` "
                "(and `eccodes` system library)."
            ) from exc
        raise DataCubeDecodeError(f"Failed to open GRIB: {path}") from exc
    except ValueError as exc:
        message = str(exc).lower()
        if "unrecognized engine" in message and engine.lower() in message:
            raise DataCubeDecodeError(
                "GRIB decoding requires the optional dependency `cfgrib` "
                "(and `eccodes` system library)."
            ) from exc
        raise DataCubeDecodeError(f"Failed to open GRIB: {path}") from exc
    except DataCubeDecodeError:
        raise
    except Exception as exc:  # noqa: BLE001
        raise DataCubeDecodeError(f"Failed to open GRIB: {path}") from exc


def decode_datacube(
    source_path: Union[str, Path],
    *,
    source_format: Optional[str] = None,
    engine: Optional[str] = None,
) -> DataCube:
    path = Path(source_path)
    fmt = (source_format or _infer_source_format(path)).lower()
    if fmt == "netcdf":
        return decode_netcdf(path, engine=engine)
    if fmt == "grib":
        return decode_grib(path, engine=engine or "cfgrib")
    raise DataCubeDecodeError(f"Unsupported source_format={fmt!r}")
