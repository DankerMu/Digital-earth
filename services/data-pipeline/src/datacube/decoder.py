from __future__ import annotations

from pathlib import Path
from typing import Optional, Union

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
) -> DataCube:
    path = Path(source_path)
    try:
        ds = xr.open_dataset(path, engine=engine, decode_cf=True)
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
    except Exception as exc:  # noqa: BLE001
        raise DataCubeDecodeError(f"Failed to open GRIB: {path}") from exc

    return DataCube.from_dataset(_load_dataset(ds))


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
