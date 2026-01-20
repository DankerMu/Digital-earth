from __future__ import annotations

import argparse
import json
import sys
from dataclasses import asdict
from pathlib import Path

PIPELINE_SRC = Path(__file__).resolve().parents[1] / "src"
sys.path.insert(0, str(PIPELINE_SRC))

from terrain.dem_downloader import (  # noqa: E402
    CopernicusStacClient,
    DemMosaic,
    iter_copernicus_tiles_for_rectangle,
)
from terrain.poc_pipeline import build_layer_json, generate_tileset, write_layer_json  # noqa: E402
from terrain.tile_pyramid import GeoRect, tiles_for_rectangle  # noqa: E402


def _build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="PoC: Copernicus DEM -> Cesium quantized-mesh terrain tiles (EPSG:4326/TMS)."
    )

    parser.add_argument(
        "--dataset",
        choices=["glo30", "glo90"],
        default="glo30",
        help="Copernicus DEM dataset (default: glo30)",
    )
    parser.add_argument(
        "--bbox",
        type=float,
        nargs=4,
        metavar=("WEST", "SOUTH", "EAST", "NORTH"),
        default=(116.0, 39.0, 117.0, 40.0),
        help="Sample region bounds in degrees (default: Beijing 116-117E,39-40N)",
    )
    parser.add_argument("--min-zoom", type=int, default=0, help="Min zoom (default: 0)")
    parser.add_argument(
        "--max-zoom", type=int, default=12, help="Max zoom (default: 12)"
    )
    parser.add_argument(
        "--grid-size",
        type=int,
        default=65,
        help="Regular grid size per tile edge (default: 65)",
    )
    parser.add_argument(
        "--gzip",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Write gzipped .terrain payloads (default: false)",
    )
    parser.add_argument(
        "--cache-dir",
        type=Path,
        default=Path(__file__).resolve().parents[1] / ".cache" / "copernicus-dem",
        help="DEM download cache directory",
    )
    parser.add_argument(
        "--dem-path",
        type=Path,
        default=None,
        help="Use a local DEM GeoTIFF instead of downloading (EPSG:4326).",
    )
    parser.add_argument(
        "--out-dir",
        type=Path,
        required=True,
        help="Output directory for layer.json + {z}/{x}/{y}.terrain",
    )
    parser.add_argument(
        "--dry-run",
        action=argparse.BooleanOptionalAction,
        default=False,
        help="Print planned tile counts without generating files",
    )
    return parser


def _load_dem(args: argparse.Namespace, rect: GeoRect) -> DemMosaic:
    if args.dem_path is not None:
        return DemMosaic.from_geotiffs([args.dem_path])

    client = CopernicusStacClient(dataset=str(args.dataset))  # type: ignore[arg-type]
    tiles = list(iter_copernicus_tiles_for_rectangle(rect))
    geotiffs: list[Path] = []
    for tile in tiles:
        geotiffs.append(client.download_elevation_geotiff(tile, out_dir=args.cache_dir))
    return DemMosaic.from_geotiffs(geotiffs)


def main() -> int:
    args = _build_parser().parse_args()

    rect = GeoRect(
        west=float(args.bbox[0]),
        south=float(args.bbox[1]),
        east=float(args.bbox[2]),
        north=float(args.bbox[3]),
    )
    if args.min_zoom < 0 or args.max_zoom < 0:
        raise SystemExit("min_zoom/max_zoom must be >= 0")
    if args.min_zoom > args.max_zoom:
        raise SystemExit("min_zoom must be <= max_zoom")
    if args.grid_size < 2:
        raise SystemExit("grid_size must be >= 2")

    args.out_dir.mkdir(parents=True, exist_ok=True)

    planned_tiles = 0
    for z in range(args.min_zoom, args.max_zoom + 1):
        planned_tiles += sum(1 for _ in tiles_for_rectangle(rect, z))
    if args.dry_run:
        print(
            json.dumps(
                {
                    "bbox": list(args.bbox),
                    "min_zoom": args.min_zoom,
                    "max_zoom": args.max_zoom,
                    "grid_size": args.grid_size,
                    "tile_count": planned_tiles,
                },
                ensure_ascii=False,
                indent=2,
                sort_keys=True,
            )
        )
        return 0

    dem = _load_dem(args, rect)
    stats = generate_tileset(
        dem=dem,
        rect=rect,
        out_dir=args.out_dir,
        min_zoom=int(args.min_zoom),
        max_zoom=int(args.max_zoom),
        grid_size=int(args.grid_size),
        gzip_payload=bool(args.gzip),
    )
    layer = build_layer_json(
        rect=rect,
        min_zoom=int(args.min_zoom),
        max_zoom=int(args.max_zoom),
        dataset=str(args.dataset),
        gzip_payload=bool(args.gzip),
    )
    write_layer_json(args.out_dir / "layer.json", layer=layer)

    print(
        json.dumps(
            {
                "bbox": [rect.west, rect.south, rect.east, rect.north],
                "dataset": str(args.dataset),
                "min_zoom": int(args.min_zoom),
                "max_zoom": int(args.max_zoom),
                "grid_size": int(args.grid_size),
                "gzip": bool(args.gzip),
                **asdict(stats),
                "avg_bytes_per_tile": stats.avg_bytes_per_tile,
                "avg_tiles_per_s": stats.avg_tiles_per_s,
            },
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
