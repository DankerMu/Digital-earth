from __future__ import annotations

from dataclasses import dataclass
from datetime import timezone
from typing import Any, Iterable, Mapping, Optional, Sequence

import numpy as np
import xarray as xr

from .accumulator import GridStatisticsAccumulator, exact_percentiles
from .sources import GridSlice, StatisticsDataSource
from .storage import StatisticsArtifact, StatisticsStore
from .time_windows import TimeWindow


class StatisticsBatchError(RuntimeError):
    pass


def _normalize_percentile_name(p: float) -> str:
    value = float(p)
    if value.is_integer():
        return f"p{int(value)}"
    return f"p{str(value).replace('.', 'p')}"


def _format_iso(dt: object) -> str:
    if not hasattr(dt, "astimezone"):
        return str(dt)
    return dt.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


def _build_dataset(
    *,
    variable: str,
    lat: np.ndarray,
    lon: np.ndarray,
    stats: Mapping[str, np.ndarray],
    percentiles: Mapping[float, np.ndarray],
    attrs: Mapping[str, Any],
) -> xr.Dataset:
    coords = {"lat": np.asarray(lat), "lon": np.asarray(lon)}
    data_vars: dict[str, xr.DataArray] = {}

    for name, grid in stats.items():
        values = np.asarray(grid)
        if name != "count":
            values = values.astype(np.float32, copy=False)
        data_vars[name] = xr.DataArray(
            values,
            dims=["lat", "lon"],
            coords=coords,
            attrs={"source_variable": variable, "statistic": name},
        )

    for p, grid in percentiles.items():
        name = _normalize_percentile_name(p)
        data_vars[name] = xr.DataArray(
            np.asarray(grid, dtype=np.float32),
            dims=["lat", "lon"],
            coords=coords,
            attrs={
                "source_variable": variable,
                "statistic": "percentile",
                "p": float(p),
            },
        )

    ds = xr.Dataset(data_vars=data_vars, coords=coords)
    ds.attrs.update(dict(attrs))
    return ds


@dataclass(frozen=True)
class StatisticsBatchResult:
    window: TimeWindow
    samples: int
    artifact: StatisticsArtifact


def compute_window_statistics(
    *,
    slices: Iterable[GridSlice],
    variable: str,
    percentiles: Sequence[float] = (),
    exact_percentiles_max_samples: int = 64,
) -> tuple[xr.Dataset, int]:
    variable = (variable or "").strip()
    if variable == "":
        raise ValueError("variable must not be empty")

    ref_lat: Optional[np.ndarray] = None
    ref_lon: Optional[np.ndarray] = None
    acc: Optional[GridStatisticsAccumulator] = None

    stored: list[np.ndarray] = []
    total = 0

    for item in slices:
        lat = np.asarray(item.lat)
        lon = np.asarray(item.lon)
        values = np.asarray(item.values, dtype=np.float32)

        if ref_lat is None:
            ref_lat = lat
            ref_lon = lon
            if values.ndim != 2:
                raise StatisticsBatchError("Expected 2D grid values")
            acc = GridStatisticsAccumulator(
                shape=(values.shape[0], values.shape[1]), percentiles=percentiles
            )
        else:
            assert ref_lon is not None
            if lat.shape != ref_lat.shape or lon.shape != ref_lon.shape:
                raise StatisticsBatchError(
                    "lat/lon coordinate shape mismatch within window"
                )
            if not np.array_equal(lat, ref_lat) or not np.array_equal(lon, ref_lon):
                raise StatisticsBatchError(
                    "lat/lon coordinate values differ within window"
                )

        assert acc is not None
        acc.update(values)

        total += 1
        if (
            percentiles
            and exact_percentiles_max_samples > 0
            and total <= exact_percentiles_max_samples
        ):
            stored.append(values)

    if ref_lat is None or ref_lon is None or acc is None:
        raise StatisticsBatchError("No input slices found for window")

    result = acc.finalize()

    stats: dict[str, np.ndarray] = {
        "mean": result.mean,
        "min": result.min,
        "max": result.max,
        "count": result.count,
    }

    pct = dict(result.percentiles)
    if percentiles and 0 < total <= exact_percentiles_max_samples:
        pct = exact_percentiles(samples=stored, percentiles=percentiles)

    ds = _build_dataset(
        variable=variable,
        lat=ref_lat,
        lon=ref_lon,
        stats=stats,
        percentiles=pct,
        attrs={"source_variable": variable, "samples": int(total)},
    )
    return ds, total


def run_historical_statistics(
    *,
    source: StatisticsDataSource,
    variable: str,
    windows: Sequence[TimeWindow],
    store: StatisticsStore,
    output_source_name: str,
    version: str,
    percentiles: Sequence[float] = (),
    exact_percentiles_max_samples: int = 64,
    engine: str = "h5netcdf",
    extra_metadata: Optional[Mapping[str, Any]] = None,
) -> list[StatisticsBatchResult]:
    if not windows:
        return []

    results: list[StatisticsBatchResult] = []

    for window in windows:
        slices = source.iter_slices(
            variable=variable,
            start=window.start,
            end=window.end,
        )
        ds, samples = compute_window_statistics(
            slices=slices,
            variable=variable,
            percentiles=percentiles,
            exact_percentiles_max_samples=exact_percentiles_max_samples,
        )

        ds.attrs.update(
            {
                "schema_version": 1,
                "source_kind": getattr(source, "kind", "unknown"),
                "output_source": str(output_source_name),
                "version": str(version),
                "window_kind": window.kind,
                "window_key": window.key,
                "window_start": _format_iso(window.start),
                "window_end": _format_iso(window.end),
            }
        )

        artifact = store.resolve_paths(
            source=str(output_source_name),
            variable=str(variable).upper(),
            window_kind=str(window.kind),
            window_key=str(window.key),
            version=str(version),
        )

        metadata: dict[str, Any] = {
            "schema_version": 1,
            "source_kind": getattr(source, "kind", "unknown"),
            "output_source": str(output_source_name),
            "variable": str(variable).upper(),
            "window_kind": window.kind,
            "window_key": window.key,
            "window_start": _format_iso(window.start),
            "window_end": _format_iso(window.end),
            "samples": int(samples),
            "version": str(version),
            "percentiles": [float(p) for p in percentiles],
        }
        if extra_metadata:
            metadata.update(dict(extra_metadata))

        store.write_dataset(ds, artifact=artifact, metadata=metadata, engine=engine)

        results.append(
            StatisticsBatchResult(window=window, samples=samples, artifact=artifact)
        )

    return results
