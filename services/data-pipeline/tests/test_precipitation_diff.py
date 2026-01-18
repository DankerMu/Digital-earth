from __future__ import annotations

import numpy as np
import pytest
import xarray as xr


def _tp_dataset(
    *,
    times: list[str],
    tp_mm: list[float],
    dim: str = "time",
) -> xr.Dataset:
    data = np.asarray(tp_mm, dtype=np.float32)[:, None, None]
    da = xr.DataArray(
        data,
        dims=[dim, "lat", "lon"],
        coords={
            dim: np.asarray(times, dtype="datetime64[s]"),
            "lat": np.asarray([10.0], dtype=np.float32),
            "lon": np.asarray([100.0], dtype=np.float32),
        },
        name="tp",
        attrs={"units": "mm"},
    )
    return xr.Dataset({"tp": da})


def test_precipitation_amount_from_accumulation_supports_mixed_steps() -> None:
    from datacube.precipitation import precipitation_amount_from_accumulation

    ds = _tp_dataset(
        times=[
            "2026-01-01T00:00:00",
            "2026-01-01T03:00:00",
            "2026-01-01T06:00:00",
            "2026-01-01T12:00:00",
        ],
        tp_mm=[0.0, 1.0, 2.0, 5.0],
    )

    out = precipitation_amount_from_accumulation(ds["tp"])
    assert out.attrs.get("units") == "mm"
    assert out.values[:, 0, 0].tolist() == pytest.approx([0.0, 1.0, 1.0, 3.0])


def test_precipitation_amount_from_accumulation_clamps_negative_diffs() -> None:
    from datacube.precipitation import precipitation_amount_from_accumulation

    ds = _tp_dataset(
        times=[
            "2026-01-01T00:00:00",
            "2026-01-01T03:00:00",
            "2026-01-01T06:00:00",
            "2026-01-01T09:00:00",
        ],
        tp_mm=[0.0, 2.0, 1.0, 3.0],
    )

    out = precipitation_amount_from_accumulation(ds["tp"], clamp_negative=True)
    assert (out.values >= 0).all()
    assert out.values[:, 0, 0].tolist() == pytest.approx([0.0, 2.0, 0.0, 2.0])


def test_precipitation_amount_from_accumulation_allows_missing_initial_value() -> None:
    from datacube.precipitation import precipitation_amount_from_accumulation

    ds = _tp_dataset(
        times=[
            "2026-01-01T00:00:00",
            "2026-01-01T03:00:00",
        ],
        tp_mm=[0.0, 1.0],
    )

    out = precipitation_amount_from_accumulation(ds["tp"], initial=None)
    assert np.isnan(out.values[0, 0, 0])
    assert out.values[1, 0, 0] == pytest.approx(1.0, abs=1e-6)


def test_precipitation_amount_from_accumulation_infers_valid_time_dim() -> None:
    from datacube.precipitation import precipitation_amount_from_accumulation

    ds = _tp_dataset(
        times=[
            "2026-01-01T00:00:00",
            "2026-01-01T06:00:00",
        ],
        tp_mm=[0.0, 3.0],
        dim="valid_time",
    )

    out = precipitation_amount_from_accumulation(ds["tp"])
    assert out.dims[0] == "valid_time"
    assert out.values[:, 0, 0].tolist() == pytest.approx([0.0, 3.0])


def test_precipitation_amount_from_accumulation_rejects_unknown_time_dim() -> None:
    from datacube.precipitation import precipitation_amount_from_accumulation

    da = xr.DataArray(
        np.zeros((2, 1, 1), dtype=np.float32),
        dims=["t", "lat", "lon"],
        coords={
            "t": np.asarray(
                ["2026-01-01T00:00:00", "2026-01-01T03:00:00"], dtype="datetime64[s]"
            ),
            "lat": np.asarray([10.0], dtype=np.float32),
            "lon": np.asarray([100.0], dtype=np.float32),
        },
    )

    with pytest.raises(ValueError, match="Unable to infer time dimension"):
        precipitation_amount_from_accumulation(da)


def test_precipitation_amount_from_accumulation_handles_empty_time_axis() -> None:
    from datacube.precipitation import precipitation_amount_from_accumulation

    da = xr.DataArray(
        np.zeros((0, 1, 1), dtype=np.float32),
        dims=["time", "lat", "lon"],
        coords={
            "time": np.asarray([], dtype="datetime64[s]"),
            "lat": np.asarray([10.0], dtype=np.float32),
            "lon": np.asarray([100.0], dtype=np.float32),
        },
        attrs={"units": "mm"},
    )
    out = precipitation_amount_from_accumulation(da)
    assert out.dtype == np.float32
    assert out.sizes["time"] == 0


def test_add_precipitation_amount_from_tp_is_noop_without_tp() -> None:
    from datacube.precipitation import add_precipitation_amount_from_tp

    ds = xr.Dataset(
        {
            "t2m": xr.DataArray(
                np.zeros((1, 1, 1), dtype=np.float32), dims=["time", "lat", "lon"]
            )
        },
        coords={
            "time": np.asarray(["2026-01-01T00:00:00"], dtype="datetime64[s]"),
            "lat": np.asarray([10.0], dtype=np.float32),
            "lon": np.asarray([100.0], dtype=np.float32),
        },
    )

    out = add_precipitation_amount_from_tp(ds)
    assert out is ds
    assert "precipitation_amount" not in out.data_vars


def test_add_precipitation_amount_from_tp_respects_overwrite_flag() -> None:
    from datacube.precipitation import add_precipitation_amount_from_tp

    ds = _tp_dataset(
        times=[
            "2026-01-01T00:00:00",
            "2026-01-01T03:00:00",
        ],
        tp_mm=[0.0, 1.0],
    )
    existing = xr.full_like(ds["tp"], 42.0).rename("precipitation_amount")
    ds["precipitation_amount"] = existing

    out = add_precipitation_amount_from_tp(ds, overwrite=False)
    assert out is ds
    assert out["precipitation_amount"].values[0, 0, 0] == pytest.approx(42.0)

    out2 = add_precipitation_amount_from_tp(ds, overwrite=True)
    assert out2 is not ds
    assert out2["precipitation_amount"].values[:, 0, 0].tolist() == pytest.approx(
        [0.0, 1.0]
    )


def test_datacube_from_dataset_adds_precipitation_amount_from_tp() -> None:
    from datacube.core import DataCube

    ds = xr.Dataset(
        {
            "tp": xr.DataArray(
                np.asarray([0.0, 0.001, 0.002, 0.005], dtype=np.float32)[:, None, None],
                dims=["time", "lat", "lon"],
                attrs={"units": "m"},
            )
        },
        coords={
            "time": np.asarray(
                [
                    "2026-01-01T00:00:00",
                    "2026-01-01T03:00:00",
                    "2026-01-01T06:00:00",
                    "2026-01-01T12:00:00",
                ],
                dtype="datetime64[s]",
            ),
            "lat": np.asarray([10.0], dtype=np.float32),
            "lon": np.asarray([100.0], dtype=np.float32),
        },
    )

    cube = DataCube.from_dataset(ds)
    out = cube.dataset
    assert "precipitation_amount" in out.data_vars
    assert out["tp"].attrs.get("units") == "mm"
    assert out["precipitation_amount"].attrs.get("units") == "mm"
    assert out["precipitation_amount"].values[:, 0, 0, 0].tolist() == pytest.approx(
        [0.0, 1.0, 1.0, 3.0]
    )
