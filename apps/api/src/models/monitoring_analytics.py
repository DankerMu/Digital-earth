from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Index, Integer, JSON, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class HistoricalStatisticArtifact(Base):
    __tablename__ = "historical_statistics"
    __table_args__ = (
        UniqueConstraint(
            "source",
            "variable",
            "window_kind",
            "window_key",
            "version",
            name="uq_historical_statistics_identity",
        ),
        Index("ix_historical_statistics_window_end", "window_end"),
        Index("ix_historical_statistics_variable", "variable"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    source: Mapped[str] = mapped_column(String(32), nullable=False)
    variable: Mapped[str] = mapped_column(String(64), nullable=False)
    window_kind: Mapped[str] = mapped_column(String(32), nullable=False)
    window_key: Mapped[str] = mapped_column(String(64), nullable=False)
    version: Mapped[str] = mapped_column(String(32), nullable=False)

    window_start: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    window_end: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    samples: Mapped[int] = mapped_column(Integer, nullable=False)

    dataset_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    metadata_path: Mapped[str] = mapped_column(String(2048), nullable=False)
    extra: Mapped[dict] = mapped_column(JSON, nullable=False, default=dict)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )


class BiasTileSet(Base):
    __tablename__ = "bias_tile_sets"
    __table_args__ = (
        UniqueConstraint(
            "layer",
            "time_key",
            "level_key",
            name="uq_bias_tile_sets_identity",
        ),
        Index("ix_bias_tile_sets_layer", "layer"),
        Index("ix_bias_tile_sets_time_key", "time_key"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    layer: Mapped[str] = mapped_column(String(128), nullable=False)
    time_key: Mapped[str] = mapped_column(String(32), nullable=False)
    level_key: Mapped[str] = mapped_column(String(32), nullable=False)

    min_zoom: Mapped[int] = mapped_column(Integer, nullable=False)
    max_zoom: Mapped[int] = mapped_column(Integer, nullable=False)
    formats: Mapped[list[str]] = mapped_column(JSON, nullable=False, default=list)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
