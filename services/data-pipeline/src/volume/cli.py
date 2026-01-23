from __future__ import annotations

import argparse
import json
from pathlib import Path
from typing import Sequence

from datacube.storage import open_datacube
from volume.cloud_density import (
    DEFAULT_CLOUD_DENSITY_LAYER,
    export_cloud_density_slices,
)


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="python -m volume",
        description="Export cloud density slices for Volume API consumption.",
    )
    parser.add_argument(
        "--datacube", required=True, help="Path to a NetCDF/Zarr DataCube containing RH"
    )
    parser.add_argument(
        "--output-dir", required=True, help="Directory to write intermediate files into"
    )
    parser.add_argument("--valid-time", default=None, help="ISO8601 timestamp")
    parser.add_argument(
        "--layer",
        default=DEFAULT_CLOUD_DENSITY_LAYER,
        help=f"Output layer path (default: {DEFAULT_CLOUD_DENSITY_LAYER})",
    )
    parser.add_argument(
        "--rh-var",
        default=None,
        help="RH variable name in DataCube (default: infer from dataset)",
    )
    parser.add_argument(
        "--rh0",
        type=float,
        default=None,
        help="Lower RH threshold (fraction [0,1] or percent [0,100])",
    )
    parser.add_argument(
        "--rh1",
        type=float,
        default=None,
        help="Upper RH threshold (fraction [0,1] or percent [0,100])",
    )
    parser.add_argument(
        "--format",
        choices=("netcdf", "zarr"),
        default="netcdf",
        help="Output format (default: netcdf)",
    )
    parser.add_argument(
        "--manifest",
        action=argparse.BooleanOptionalAction,
        default=True,
        help="Write a manifest.json next to slice files (default: enabled)",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    parser = _build_parser()
    args = parser.parse_args(argv)

    cube_path = Path(args.datacube)
    output_dir = Path(args.output_dir)

    ds = open_datacube(cube_path)
    try:
        result = export_cloud_density_slices(
            ds,
            output_dir,
            valid_time=args.valid_time,
            layer=args.layer,
            rh_variable=args.rh_var,
            rh0=args.rh0,
            rh1=args.rh1,
            output_format=args.format,
            write_manifest=bool(args.manifest),
        )
    finally:
        ds.close()

    payload = {
        "schema_version": 1,
        "layer": result.layer,
        "time": result.time,
        "rh0": result.rh0,
        "rh1": result.rh1,
        "levels": result.levels,
        "files": [str(path) for path in result.files],
        "manifest": str(result.manifest) if result.manifest is not None else None,
    }
    print(json.dumps(payload, ensure_ascii=True, separators=(",", ":"), sort_keys=True))
    return 0
