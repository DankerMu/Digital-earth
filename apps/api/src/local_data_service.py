from __future__ import annotations

from functools import lru_cache

from config import get_settings
from data_source import DataSource, LocalDataSource, RemoteDataSource


@lru_cache(maxsize=1)
def get_data_source() -> DataSource:
    settings = get_settings()
    if settings.pipeline.data_source == "local":
        return LocalDataSource()
    return RemoteDataSource()
