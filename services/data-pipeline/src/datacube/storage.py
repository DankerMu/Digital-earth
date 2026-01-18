from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path
from typing import Optional, Union

import numpy as np
import xarray as xr

from datacube.types import DataCubeFormat
from datacube.errors import DataCubeStorageError


@dataclass(frozen=True)
class DataCubeWriteOptions:
    compression_level: int = 4
    chunk_lat: int = 256
    chunk_lon: int = 256
    chunk_time: int = 1
    chunk_level: int = 1
    zarr_codec: str = "zstd"


def _infer_format(path: Path) -> DataCubeFormat:
    if path.is_dir():
        return "zarr"
    suffix = path.suffix.lower()
    if suffix == ".zarr":
        return "zarr"
    return "netcdf"


def _chunk_shape(
    ds: xr.Dataset, options: DataCubeWriteOptions
) -> tuple[int, int, int, int]:
    return (
        min(int(ds.sizes.get("time", 1)), int(options.chunk_time)),
        min(int(ds.sizes.get("level", 1)), int(options.chunk_level)),
        min(int(ds.sizes.get("lat", 1)), int(options.chunk_lat)),
        min(int(ds.sizes.get("lon", 1)), int(options.chunk_lon)),
    )


def _netcdf_encoding(
    ds: xr.Dataset,
    *,
    options: DataCubeWriteOptions,
    engine: str,
) -> dict[str, dict[str, object]]:
    chunk = _chunk_shape(ds, options)
    resolved_engine = (engine or "").lower()
    encoding: dict[str, dict[str, object]] = {}
    for name in ds.data_vars:
        var_encoding: dict[str, object] = {
            "dtype": np.float32,
            "chunksizes": chunk,
        }
        if resolved_engine == "netcdf4":
            var_encoding.update(
                {
                    "zlib": True,
                    "complevel": int(options.compression_level),
                    "shuffle": True,
                }
            )
        elif resolved_engine == "h5netcdf":
            var_encoding.update(
                {
                    "compression": "gzip",
                    "compression_opts": int(options.compression_level),
                    "shuffle": True,
                }
            )
        encoding[name] = var_encoding
    return encoding


def _zarr_encoding(
    ds: xr.Dataset,
    *,
    options: DataCubeWriteOptions,
) -> dict[str, dict[str, object]]:
    try:
        import numcodecs  # type: ignore[import-not-found]
    except Exception as exc:  # noqa: BLE001
        raise DataCubeStorageError(
            "Zarr writing requires `zarr` and `numcodecs`; install with `pip install zarr`."
        ) from exc

    chunk = _chunk_shape(ds, options)
    codec = str(options.zarr_codec or "zstd").lower()
    if codec not in {"zstd", "lz4", "zlib"}:
        raise DataCubeStorageError(f"Unsupported zarr_codec={options.zarr_codec!r}")

    compressor = numcodecs.Blosc(
        cname=codec,
        clevel=int(options.compression_level),
        shuffle=numcodecs.Blosc.BITSHUFFLE,
    )
    encoding: dict[str, dict[str, object]] = {}
    for name in ds.data_vars:
        encoding[name] = {
            "dtype": np.float32,
            "chunks": chunk,
            "compressor": compressor,
        }
    return encoding


def write_datacube(
    ds: xr.Dataset,
    output_path: Union[str, Path],
    *,
    format: Optional[DataCubeFormat] = None,
    engine: Optional[str] = None,
    options: Optional[DataCubeWriteOptions] = None,
) -> Path:
    path = Path(output_path)
    fmt = format or _infer_format(path)
    opts = options or DataCubeWriteOptions()

    if fmt == "netcdf":
        path.parent.mkdir(parents=True, exist_ok=True)
        resolved_engine = engine or "h5netcdf"
        encoding = _netcdf_encoding(ds, options=opts, engine=resolved_engine)
        try:
            ds.to_netcdf(path, engine=resolved_engine, encoding=encoding)
        except Exception as exc:  # noqa: BLE001
            raise DataCubeStorageError(
                f"Failed to write NetCDF DataCube: {path}"
            ) from exc
        return path

    if fmt == "zarr":
        try:
            import zarr  # noqa: F401  # type: ignore[import-not-found]
        except Exception as exc:  # noqa: BLE001
            raise DataCubeStorageError(
                "Zarr writing requires `zarr`; install with `pip install zarr`."
            ) from exc

        path.mkdir(parents=True, exist_ok=True)
        encoding = _zarr_encoding(ds, options=opts)
        try:
            ds.to_zarr(path, mode="w", encoding=encoding, consolidated=True)
        except Exception as exc:  # noqa: BLE001
            raise DataCubeStorageError(
                f"Failed to write Zarr DataCube: {path}"
            ) from exc
        return path

    raise DataCubeStorageError(f"Unsupported DataCube format: {fmt!r}")


def open_datacube(
    path: Union[str, Path],
    *,
    format: Optional[DataCubeFormat] = None,
    engine: Optional[str] = None,
) -> xr.Dataset:
    p = Path(path)
    fmt = format or _infer_format(p)

    if fmt == "zarr":
        try:
            return xr.open_zarr(p, consolidated=True)
        except Exception as exc:  # noqa: BLE001
            raise DataCubeStorageError(f"Failed to open Zarr DataCube: {p}") from exc

    if fmt == "netcdf":
        try:
            return xr.open_dataset(p, engine=engine or "h5netcdf", decode_cf=True)
        except Exception as exc:  # noqa: BLE001
            raise DataCubeStorageError(f"Failed to open NetCDF DataCube: {p}") from exc

    raise DataCubeStorageError(f"Unsupported DataCube format: {fmt!r}")
