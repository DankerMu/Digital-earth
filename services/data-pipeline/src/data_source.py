from __future__ import annotations

from abc import ABC, abstractmethod
from pathlib import Path
from typing import Optional

from digital_earth_config.local_data import LocalDataPaths, get_local_data_paths

from local.cache import get_local_file_index
from local.cldas_loader import (
    CldasGridSummary,
    load_cldas_dataset,
    summarize_cldas_dataset,
)
from local.ecmwf_loader import read_ecmwf_grib_bytes
from local.indexer import LocalDataKind, LocalFileIndex, LocalFileIndexItem
from local.town_forecast import TownForecastFile, parse_town_forecast_file


class DataSourceError(RuntimeError):
    pass


class DataNotFoundError(FileNotFoundError, DataSourceError):
    pass


class DataSource(ABC):
    @abstractmethod
    def list_files(
        self,
        *,
        kinds: Optional[set[LocalDataKind]] = None,
        refresh: bool = False,
    ) -> LocalFileIndex:
        raise NotImplementedError

    @abstractmethod
    def open_path(self, relative_path: str) -> Path:
        raise NotImplementedError

    def get_index_item(
        self, relative_path: str, *, refresh: bool = False
    ) -> LocalFileIndexItem:
        index = self.list_files(refresh=refresh)
        for item in index.items:
            if item.relative_path == relative_path:
                return item
        raise DataNotFoundError(f"Local data file not found in index: {relative_path}")

    def read_bytes(self, relative_path: str) -> bytes:
        return self.open_path(relative_path).read_bytes()

    def load_cldas_summary(self, relative_path: str) -> CldasGridSummary:
        ds = load_cldas_dataset(self.open_path(relative_path))
        return summarize_cldas_dataset(ds)

    def load_town_forecast(
        self, relative_path: str, *, max_stations: Optional[int] = None
    ) -> TownForecastFile:
        return parse_town_forecast_file(
            self.open_path(relative_path), max_stations=max_stations
        )

    def load_ecmwf_bytes(
        self, relative_path: str, *, max_bytes: Optional[int] = None
    ) -> bytes:
        return read_ecmwf_grib_bytes(self.open_path(relative_path), max_bytes=max_bytes)


class LocalDataSource(DataSource):
    def __init__(
        self,
        *,
        paths: Optional[LocalDataPaths] = None,
        cache_path: Optional[Path] = None,
    ) -> None:
        self._paths = paths or get_local_data_paths()
        self._cache_path = cache_path

    @property
    def paths(self) -> LocalDataPaths:
        return self._paths

    def list_files(
        self,
        *,
        kinds: Optional[set[LocalDataKind]] = None,
        refresh: bool = False,
    ) -> LocalFileIndex:
        return get_local_file_index(
            self._paths,
            cache_path=self._cache_path or Path(".cache/local-data-index.json"),
            refresh=refresh,
            kinds=kinds,
        )

    def open_path(self, relative_path: str) -> Path:
        if relative_path.strip() == "":
            raise DataSourceError("relative_path must not be empty")

        root = self._paths.root_dir.resolve()
        candidate = (root / relative_path).resolve()
        if not candidate.is_relative_to(root):
            raise DataSourceError(
                "relative_path must resolve within local data root_dir"
            )
        if not candidate.is_file():
            raise DataNotFoundError(f"Local data file not found: {relative_path}")
        return candidate


class RemoteDataSource(DataSource):
    def list_files(
        self,
        *,
        kinds: Optional[set[LocalDataKind]] = None,
        refresh: bool = False,
    ) -> LocalFileIndex:
        raise DataSourceError("RemoteDataSource is not implemented yet")

    def open_path(self, relative_path: str) -> Path:
        raise DataSourceError("RemoteDataSource is not implemented yet")
