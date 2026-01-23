from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class RiskPOIEvaluation(Base):
    __tablename__ = "risk_poi_evaluations"
    __table_args__ = (
        UniqueConstraint(
            "poi_id",
            "product_id",
            "valid_time",
            name="uq_risk_poi_evaluations_identity",
        ),
        Index("ix_risk_poi_evaluations_poi_id", "poi_id"),
        Index("ix_risk_poi_evaluations_product_time", "product_id", "valid_time"),
        Index("ix_risk_poi_evaluations_valid_time", "valid_time"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    poi_id: Mapped[int] = mapped_column(
        ForeignKey("risk_pois.id", ondelete="CASCADE"), nullable=False
    )
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    valid_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    risk_level: Mapped[int] = mapped_column(Integer, nullable=False)
    evaluated_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )
