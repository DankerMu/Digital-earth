from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

PIPELINE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PIPELINE_SRC))

from datacube.inspect import inspect_datacube


def main() -> int:
    parser = argparse.ArgumentParser(description="Inspect a DataCube (NetCDF/Zarr).")
    parser.add_argument("path", type=Path, help="Path to .nc file or .zarr directory")
    parser.add_argument(
        "--format",
        choices=["netcdf", "zarr"],
        default=None,
        help="Force format instead of inferring from path",
    )
    parser.add_argument(
        "--engine",
        default=None,
        help="Optional xarray engine (e.g. h5netcdf, netcdf4)",
    )
    args = parser.parse_args()

    summary = inspect_datacube(args.path, format=args.format, engine=args.engine)
    print(json.dumps(summary, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
