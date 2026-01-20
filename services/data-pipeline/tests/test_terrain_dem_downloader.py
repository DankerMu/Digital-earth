from __future__ import annotations

from pathlib import Path

import pytest
import numpy as np

from terrain.dem_downloader import (
    CopernicusDemTile,
    CopernicusStacClient,
    DemGrid,
    DemMosaic,
    iter_copernicus_tiles_for_rectangle,
)
from terrain.tile_pyramid import GeoRect


def test_copernicus_item_url_formats() -> None:
    tile = CopernicusDemTile(lat_deg=39, lon_deg=116)
    client30 = CopernicusStacClient(dataset="glo30")
    assert client30.item_url(tile).endswith(
        "/items/Copernicus_DSM_COG_10_N39_00_E116_00.json"
    )

    client90 = CopernicusStacClient(dataset="glo90")
    assert client90.item_url(tile).endswith(
        "/items/Copernicus_DSM_COG_30_N39_00_E116_00.json"
    )


def test_copernicus_item_url_negative_coords() -> None:
    tile = CopernicusDemTile(lat_deg=-8, lon_deg=-10)
    client = CopernicusStacClient(dataset="glo30")
    assert client.item_url(tile).endswith(
        "/items/Copernicus_DSM_COG_10_S08_00_W010_00.json"
    )


def test_copernicus_tile_validation() -> None:
    with pytest.raises(ValueError, match="Invalid tile lat_deg"):
        CopernicusDemTile(lat_deg=90, lon_deg=0)
    with pytest.raises(ValueError, match="Invalid tile lon_deg"):
        CopernicusDemTile(lat_deg=0, lon_deg=180)


def test_iter_copernicus_tiles_single_degree() -> None:
    rect = GeoRect(west=116.0, south=39.0, east=117.0, north=40.0)
    tiles = list(iter_copernicus_tiles_for_rectangle(rect))
    assert tiles == [CopernicusDemTile(lat_deg=39, lon_deg=116)]


def test_iter_copernicus_tiles_multi_degree() -> None:
    rect = GeoRect(west=115.5, south=39.5, east=116.5, north=40.5)
    tiles = list(iter_copernicus_tiles_for_rectangle(rect))
    assert set(tiles) == {
        CopernicusDemTile(lat_deg=39, lon_deg=115),
        CopernicusDemTile(lat_deg=39, lon_deg=116),
        CopernicusDemTile(lat_deg=40, lon_deg=115),
        CopernicusDemTile(lat_deg=40, lon_deg=116),
    }


def test_demgrid_sample_nearest_and_bilinear() -> None:
    grid = DemGrid(
        west=0.0,
        south=0.0,
        east=1.0,
        north=1.0,
        heights_m=np.array([[0.0, 10.0], [20.0, 30.0]], dtype=np.float32),
    )
    assert grid.sample(0.5, 0.5, method="bilinear") == pytest.approx(15.0)
    assert grid.sample(0.51, 0.49, method="nearest") == pytest.approx(10.0)
    assert grid.sample(2.0, 2.0, fill_value=-999.0) == pytest.approx(-999.0)
    with pytest.raises(ValueError, match="Unknown sampling method"):
        grid.sample(0.5, 0.5, method="cubic")  # type: ignore[arg-type]


def test_demgrid_sample_nan_handling() -> None:
    grid = DemGrid(
        west=0.0,
        south=0.0,
        east=1.0,
        north=1.0,
        heights_m=np.array([[np.nan, 0.0], [0.0, 0.0]], dtype=np.float32),
    )
    assert grid.sample(0.0, 0.0, method="nearest", fill_value=123.0) == pytest.approx(
        123.0
    )
    assert grid.sample(0.5, 0.5, method="bilinear", fill_value=123.0) == pytest.approx(
        123.0
    )


def test_demgrid_sample_grid() -> None:
    grid = DemGrid(
        west=0.0,
        south=0.0,
        east=1.0,
        north=1.0,
        heights_m=np.array([[0.0, 10.0], [20.0, 30.0]], dtype=np.float32),
    )
    out = grid.sample_grid(
        GeoRect(west=0.0, south=0.0, east=1.0, north=1.0), grid_size=3
    )
    assert out.shape == (3, 3)
    assert float(out[0, 0]) == pytest.approx(0.0)
    assert float(out[0, 2]) == pytest.approx(10.0)
    assert float(out[2, 0]) == pytest.approx(20.0)
    assert float(out[2, 2]) == pytest.approx(30.0)
    assert float(out[1, 1]) == pytest.approx(15.0)
    with pytest.raises(ValueError, match="grid_size must be"):
        grid.sample_grid(GeoRect(west=0.0, south=0.0, east=1.0, north=1.0), grid_size=1)


def test_demgrid_from_geotiff_requires_rasterio(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    # Simulate missing rasterio by blocking the import
    def mock_import(name: str, *args: object, **kwargs: object) -> object:
        if name == "rasterio":
            raise ModuleNotFoundError(f"No module named '{name}'")
        return __import__(name, *args, **kwargs)

    import builtins

    monkeypatch.setattr(builtins, "__import__", mock_import)

    dummy = tmp_path / "dummy.tif"
    dummy.write_bytes(b"")
    with pytest.raises(RuntimeError, match="rasterio is required"):
        DemGrid.from_geotiff(dummy)


def test_dem_mosaic_sampling_dispatch() -> None:
    grid = DemGrid(
        west=0.0,
        south=0.0,
        east=1.0,
        north=1.0,
        heights_m=np.array([[0.0, 10.0], [20.0, 30.0]], dtype=np.float32),
    )
    mosaic = DemMosaic(tiles={(0, 0): grid})
    assert mosaic.sample(0.0, 0.0) == pytest.approx(0.0)
    assert mosaic.sample(0.5, 0.5) == pytest.approx(15.0)
    assert mosaic.sample(10.0, 10.0, fill_value=-1.0) == pytest.approx(-1.0)


def test_dem_mosaic_neighbor_and_scan_fallback() -> None:
    grid = DemGrid(
        west=0.0,
        south=0.0,
        east=1.0,
        north=1.0,
        heights_m=np.array([[0.0, 10.0], [20.0, 30.0]], dtype=np.float32),
    )
    mosaic = DemMosaic(tiles={(0, 0): grid})
    # lon_key=1 doesn't exist; should fall back to west neighbor (0,0)
    assert mosaic.sample(1.0, 0.5) == pytest.approx(20.0)

    # Key mismatch forces conservative scan fallback.
    mosaic_miskeyed = DemMosaic(tiles={(0, 1): grid})
    assert mosaic_miskeyed.sample(0.5, 0.5) == pytest.approx(15.0)

    with pytest.raises(ValueError, match="grid_size must be"):
        mosaic.sample_grid(
            GeoRect(west=0.0, south=0.0, east=1.0, north=1.0), grid_size=1
        )


def test_copernicus_download_geotiff_with_fake_httpx(
    monkeypatch: pytest.MonkeyPatch, tmp_path: Path
) -> None:
    # Fake STAC item that points to a fake GeoTIFF URL.
    item = {
        "assets": {
            "elevation": {"href": "https://example.invalid/fake.tif"},
        }
    }
    content = b"FAKE_GEOTIFF_BYTES"

    class FakeResponse:
        def __init__(self, *, json_data=None, body=None):
            self._json = json_data
            self._body = body

        def raise_for_status(self) -> None:
            return None

        def json(self):
            return self._json

        def iter_bytes(self, *, chunk_size: int):
            assert chunk_size > 0
            yield self._body

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

    class FakeClient:
        def __init__(self, *args, **kwargs):
            pass

        def __enter__(self):
            return self

        def __exit__(self, exc_type, exc, tb):
            return False

        def get(self, url: str):
            assert url.endswith(".json")
            return FakeResponse(json_data=item)

        def stream(self, method: str, url: str):
            assert method == "GET"
            assert url.endswith(".tif")
            return FakeResponse(body=content)

    import terrain.dem_downloader as dem_downloader

    monkeypatch.setattr(dem_downloader.httpx, "Client", FakeClient)

    client = CopernicusStacClient(dataset="glo30")
    tile = CopernicusDemTile(lat_deg=39, lon_deg=116)
    path = client.download_elevation_geotiff(tile, out_dir=tmp_path)
    assert path.exists()
    assert path.read_bytes() == content

    # Cached download should return same path without changing contents.
    path2 = client.download_elevation_geotiff(tile, out_dir=tmp_path)
    assert path2 == path
    assert path2.read_bytes() == content
