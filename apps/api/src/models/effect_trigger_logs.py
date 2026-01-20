from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, Float, Index, Integer, String, func
from sqlalchemy.orm import Mapped, mapped_column

from .base import Base


class EffectTriggerLog(Base):
    __tablename__ = "effect_trigger_logs"
    __table_args__ = (
        Index("ix_effect_trigger_logs_received_at", "received_at"),
        Index("ix_effect_trigger_logs_triggered_at", "triggered_at"),
        Index("ix_effect_trigger_logs_effect_type", "effect_type"),
        Index("ix_effect_trigger_logs_client_id", "client_id"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    effect_type: Mapped[str] = mapped_column(String(64), nullable=False)
    triggered_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    received_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )
    client_id: Mapped[str | None] = mapped_column(String(128))
    client: Mapped[str | None] = mapped_column(String(64))
    fps: Mapped[float | None] = mapped_column(Float)
