from __future__ import annotations

from datetime import datetime

from sqlalchemy import DateTime, ForeignKey, Index, Integer, String, UniqueConstraint, func
from sqlalchemy.orm import Mapped, mapped_column, relationship

from .base import Base


class EcmwfRun(Base):
    __tablename__ = "ecmwf_runs"
    __table_args__ = (Index("ix_ecmwf_runs_run_time", "run_time", unique=True),)

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_time: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    times: Mapped[list["EcmwfTime"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )
    assets: Mapped[list["EcmwfAsset"]] = relationship(
        back_populates="run", cascade="all, delete-orphan"
    )


class EcmwfTime(Base):
    __tablename__ = "ecmwf_times"
    __table_args__ = (
        UniqueConstraint("run_id", "valid_time", name="uq_ecmwf_times_run_valid"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ecmwf_runs.id", ondelete="CASCADE"), nullable=False
    )
    valid_time: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, index=True
    )
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    run: Mapped["EcmwfRun"] = relationship(back_populates="times")
    assets: Mapped[list["EcmwfAsset"]] = relationship(
        back_populates="time", cascade="all, delete-orphan"
    )


class EcmwfAsset(Base):
    __tablename__ = "ecmwf_assets"
    __table_args__ = (
        UniqueConstraint(
            "run_id",
            "time_id",
            "variable",
            "level",
            "version",
            name="uq_ecmwf_assets_identity",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    run_id: Mapped[int] = mapped_column(
        ForeignKey("ecmwf_runs.id", ondelete="CASCADE"), nullable=False
    )
    time_id: Mapped[int] = mapped_column(
        ForeignKey("ecmwf_times.id", ondelete="CASCADE"), nullable=False
    )
    variable: Mapped[str] = mapped_column(String(32), nullable=False)
    level: Mapped[str] = mapped_column(String(32), nullable=False)
    status: Mapped[str] = mapped_column(String(32), nullable=False)
    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    path: Mapped[str] = mapped_column(String(2048), nullable=False)

    run: Mapped["EcmwfRun"] = relationship(back_populates="assets")
    time: Mapped["EcmwfTime"] = relationship(back_populates="assets")
