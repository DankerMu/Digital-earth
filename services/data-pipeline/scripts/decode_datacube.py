from __future__ import annotations

import argparse
import sys
from pathlib import Path

PIPELINE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PIPELINE_SRC))

from datacube.decoder import decode_datacube
from datacube.storage import DataCubeWriteOptions


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Decode a GRIB/NetCDF source into a unified DataCube (NetCDF/Zarr)."
    )
    parser.add_argument("source", type=Path, help="Path to .grib2/.grib or .nc file")
    parser.add_argument(
        "output",
        type=Path,
        help="Output path (.nc file or .zarr directory).",
    )
    parser.add_argument(
        "--source-format",
        choices=["grib", "netcdf"],
        default=None,
        help="Force source format instead of inferring from extension",
    )
    parser.add_argument(
        "--output-format",
        choices=["netcdf", "zarr"],
        default=None,
        help="Force output format instead of inferring from output path",
    )
    parser.add_argument(
        "--engine",
        default=None,
        help="Optional xarray engine (NetCDF: h5netcdf/netcdf4; GRIB: cfgrib)",
    )
    parser.add_argument("--compression-level", type=int, default=4)
    parser.add_argument("--chunk-lat", type=int, default=256)
    parser.add_argument("--chunk-lon", type=int, default=256)
    args = parser.parse_args()

    cube = decode_datacube(
        args.source,
        source_format=args.source_format,
        engine=args.engine,
    )
    cube.write(
        args.output,
        format=args.output_format,
        engine=args.engine,
        options=DataCubeWriteOptions(
            compression_level=int(args.compression_level),
            chunk_lat=int(args.chunk_lat),
            chunk_lon=int(args.chunk_lon),
        ),
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
