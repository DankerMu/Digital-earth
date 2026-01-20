from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Iterator, Literal, Optional

import numpy as np
import xarray as xr

from local.cldas_loader import load_cldas_dataset


class StatisticsSourceError(RuntimeError):
    pass


SourceKind = Literal["cldas", "archive"]

_CLDAS_FILENAME_RE: re.Pattern[str] = re.compile(
    r"^CHINA_WEST_(?P<resolution>[0-9]+P[0-9]+)_HOR-(?P<var>[A-Za-z0-9]+)-(?P<ts>\d{10})\.nc$",
    re.IGNORECASE,
)


def _parse_cldas_timestamp(name: str) -> tuple[str, datetime]:
    match = _CLDAS_FILENAME_RE.match(name)
    if not match:
        raise StatisticsSourceError(f"Unrecognized CLDAS filename: {name}")
    ts = match.group("ts")
    try:
        dt = datetime.strptime(ts, "%Y%m%d%H").replace(tzinfo=timezone.utc)
    except ValueError as exc:
        raise StatisticsSourceError(
            f"Invalid CLDAS timestamp in filename: {name}"
        ) from exc
    return match.group("var").upper(), dt


@dataclass(frozen=True)
class GridSlice:
    time: datetime
    lat: np.ndarray
    lon: np.ndarray
    values: np.ndarray


class StatisticsDataSource:
    kind: SourceKind

    def iter_slices(
        self, *, variable: str, start: datetime, end: datetime
    ) -> Iterator[GridSlice]:
        raise NotImplementedError


class CldasDirectorySource(StatisticsDataSource):
    kind: SourceKind = "cldas"

    def __init__(self, root_dir: str | Path, *, engine: Optional[str] = None) -> None:
        self._root_dir = Path(root_dir).expanduser().resolve()
        self._engine = engine

    @property
    def root_dir(self) -> Path:
        return self._root_dir

    def list_files(
        self, *, variable: str, start: datetime, end: datetime
    ) -> list[Path]:
        variable = (variable or "").strip().upper()
        if variable == "":
            raise ValueError("variable must not be empty")

        if not self._root_dir.is_dir():
            raise FileNotFoundError(f"CLDAS root_dir not found: {self._root_dir}")

        candidates = self._root_dir.rglob(f"CHINA_WEST_*_HOR-{variable}-*.nc")
        matches: list[tuple[datetime, Path]] = []
        for path in candidates:
            try:
                var_code, dt = _parse_cldas_timestamp(path.name)
            except StatisticsSourceError:
                continue
            if var_code != variable:
                continue
            if start <= dt < end:
                matches.append((dt, path))

        matches.sort(key=lambda item: item[0])
        return [path for _, path in matches]

    def iter_slices(
        self, *, variable: str, start: datetime, end: datetime
    ) -> Iterator[GridSlice]:
        variable = (variable or "").strip().upper()
        if variable == "":
            raise ValueError("variable must not be empty")

        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)

        for path in self.list_files(variable=variable, start=start, end=end):
            _, dt = _parse_cldas_timestamp(path.name)
            ds = load_cldas_dataset(path, engine=self._engine)
            try:
                if variable not in ds.data_vars:
                    raise StatisticsSourceError(
                        f"Variable {variable!r} not found in dataset: {path.name}"
                    )
                da = ds[variable]
                if "time" in da.dims:
                    da = da.isel(time=0)
                if set(da.dims) != {"lat", "lon"}:
                    raise StatisticsSourceError(
                        f"Expected dims {{'lat','lon'}}, got {list(da.dims)} in {path.name}"
                    )
                da = da.transpose("lat", "lon")
                yield GridSlice(
                    time=dt,
                    lat=np.asarray(ds["lat"].values),
                    lon=np.asarray(ds["lon"].values),
                    values=np.asarray(da.values).astype(np.float32, copy=False),
                )
            finally:
                ds.close()


class ArchiveDatasetSource(StatisticsDataSource):
    kind: SourceKind = "archive"

    def __init__(
        self,
        dataset_path: str | Path,
        *,
        engine: Optional[str] = None,
    ) -> None:
        self._dataset_path = Path(dataset_path).expanduser().resolve()
        self._engine = engine

    @property
    def dataset_path(self) -> Path:
        return self._dataset_path

    def iter_slices(
        self, *, variable: str, start: datetime, end: datetime
    ) -> Iterator[GridSlice]:
        variable = (variable or "").strip()
        if variable == "":
            raise ValueError("variable must not be empty")

        start = start.astimezone(timezone.utc)
        end = end.astimezone(timezone.utc)

        if not self._dataset_path.is_file():
            raise FileNotFoundError(f"Archive dataset not found: {self._dataset_path}")

        ds: xr.Dataset
        try:
            ds = xr.open_dataset(
                self._dataset_path,
                engine=self._engine,
                decode_cf=True,
                mask_and_scale=True,
            )
        except Exception as exc:  # noqa: BLE001
            raise StatisticsSourceError(
                f"Failed to open archive dataset: {self._dataset_path}"
            ) from exc

        try:
            if variable not in ds.data_vars:
                raise StatisticsSourceError(
                    f"Variable {variable!r} not found; available={list(ds.data_vars)}"
                )
            if "time" not in ds.coords:
                raise StatisticsSourceError(
                    "Archive dataset missing required coordinate: time"
                )
            if "lat" not in ds.coords or "lon" not in ds.coords:
                raise StatisticsSourceError(
                    "Archive dataset missing required coordinates: lat/lon"
                )

            times = np.asarray(ds["time"].values)
            if times.size == 0:
                return
            if not np.issubdtype(times.dtype, np.datetime64):
                raise StatisticsSourceError(
                    f"Archive time coordinate must be datetime64; got {times.dtype}"
                )
            times_s = times.astype("datetime64[s]")
            start64 = np.datetime64(start.replace(tzinfo=None), "s")
            end64 = np.datetime64(end.replace(tzinfo=None), "s")
            indices = np.where((times_s >= start64) & (times_s < end64))[0]

            lat = np.asarray(ds["lat"].values)
            lon = np.asarray(ds["lon"].values)

            for idx in indices.tolist():
                time64 = np.datetime64(times_s[idx], "s")
                iso = np.datetime_as_string(time64, unit="s")
                dt = datetime.fromisoformat(iso).replace(tzinfo=timezone.utc)

                da = ds[variable].isel(time=idx)
                if set(da.dims) != {"lat", "lon"}:
                    raise StatisticsSourceError(
                        f"Expected dims {{'lat','lon'}}, got {list(da.dims)} at time index {idx}"
                    )
                da = da.transpose("lat", "lon")
                yield GridSlice(
                    time=dt,
                    lat=lat,
                    lon=lon,
                    values=np.asarray(da.values).astype(np.float32, copy=False),
                )
        finally:
            ds.close()
