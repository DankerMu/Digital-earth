from __future__ import annotations

import os
from functools import lru_cache

from sqlalchemy import Engine, create_engine

from config import get_settings


@lru_cache(maxsize=1)
def get_engine() -> Engine:
    url = os.environ.get("DATABASE_URL")
    if url:
        return create_engine(url, pool_pre_ping=True)

    settings = get_settings()
    return create_engine(settings.database.dsn, pool_pre_ping=True)
