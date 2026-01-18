from __future__ import annotations

from collections.abc import Sequence

from sqlalchemy import Float, Index, Integer, JSON, String, Select, select
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RiskPOI(Base):
    __tablename__ = "risk_pois"
    __table_args__ = (
        Index("ix_risk_pois_geom", "lon", "lat"),
        Index("ix_risk_pois_type", "type"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    name: Mapped[str] = mapped_column(String(256), nullable=False)
    poi_type: Mapped[str] = mapped_column("type", String(64), nullable=False)
    lon: Mapped[float] = mapped_column(Float, nullable=False)
    lat: Mapped[float] = mapped_column(Float, nullable=False)
    alt: Mapped[float | None] = mapped_column(Float, nullable=True)
    weight: Mapped[float] = mapped_column(Float, nullable=False, default=1.0)
    tags: Mapped[list[str] | None] = mapped_column(JSON, nullable=True)

    @classmethod
    def select_in_bbox(
        cls,
        *,
        min_lon: float,
        min_lat: float,
        max_lon: float,
        max_lat: float,
        poi_types: Sequence[str] | None = None,
    ) -> Select[tuple["RiskPOI"]]:
        stmt = select(cls).where(
            cls.lon >= min_lon,
            cls.lon <= max_lon,
            cls.lat >= min_lat,
            cls.lat <= max_lat,
        )

        if poi_types:
            stmt = stmt.where(cls.poi_type.in_(list(poi_types)))

        return stmt
