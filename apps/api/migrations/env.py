from __future__ import annotations

import os
import sys
from logging.config import fileConfig
from pathlib import Path
from typing import Optional

from alembic import context
from sqlalchemy import engine_from_config, pool

config = context.config

if config.config_file_name is not None:
    fileConfig(config.config_file_name)

API_ROOT = Path(__file__).resolve().parents[1]
API_SRC = API_ROOT / "src"
sys.path.insert(0, str(API_SRC))

from models import Base  # noqa: E402

target_metadata = Base.metadata


def _get_sqlalchemy_url() -> Optional[str]:
    url = os.environ.get("DATABASE_URL")
    if url:
        return url

    try:
        from digital_earth_config import Settings

        return Settings().database.dsn
    except Exception:  # noqa: BLE001
        return None


def run_migrations_offline() -> None:
    url = _get_sqlalchemy_url() or config.get_main_option("sqlalchemy.url")
    context.configure(
        url=url,
        target_metadata=target_metadata,
        literal_binds=True,
        dialect_opts={"paramstyle": "named"},
        compare_type=True,
    )

    with context.begin_transaction():
        context.run_migrations()


def run_migrations_online() -> None:
    configuration = config.get_section(config.config_ini_section, {})

    url = _get_sqlalchemy_url()
    if url:
        configuration["sqlalchemy.url"] = url

    connectable = engine_from_config(
        configuration,
        prefix="sqlalchemy.",
        poolclass=pool.NullPool,
    )

    with connectable.connect() as connection:
        context.configure(
            connection=connection,
            target_metadata=target_metadata,
            compare_type=True,
        )

        with context.begin_transaction():
            context.run_migrations()


if context.is_offline_mode():
    run_migrations_offline()
else:
    run_migrations_online()
