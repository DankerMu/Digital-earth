from __future__ import annotations

import json
from datetime import datetime
from typing import Iterable, Optional

from sqlalchemy import (
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    JSON,
    LargeBinary,
    String,
    Text,
    UniqueConstraint,
    func,
)
from sqlalchemy.orm import Mapped, mapped_column, relationship
from sqlalchemy.types import TypeDecorator

from .base import Base


class GeometryBlob(TypeDecorator[object]):
    impl = LargeBinary
    cache_ok = True

    def process_bind_param(self, value: object, dialect: object) -> Optional[bytes]:
        if value is None:
            return None

        if isinstance(value, (bytes, bytearray, memoryview)):
            return bytes(value)

        if isinstance(value, str):
            return value.encode("utf-8")

        try:
            payload = json.dumps(value, ensure_ascii=False, separators=(",", ":"))
        except TypeError as exc:  # pragma: no cover
            raise ValueError(
                "geometry must be bytes, str, or JSON-serializable"
            ) from exc
        return payload.encode("utf-8")

    def process_result_value(self, value: object, dialect: object) -> object:
        if value is None:
            return None

        if isinstance(value, memoryview):
            raw = value.tobytes()
        else:
            raw = value

        if not isinstance(raw, (bytes, bytearray)):
            return raw

        try:
            text = raw.decode("utf-8")
        except UnicodeDecodeError:
            return bytes(raw)

        stripped = text.lstrip()
        if not stripped.startswith(("{", "[")):
            return bytes(raw)

        try:
            return json.loads(text)
        except json.JSONDecodeError:
            return bytes(raw)


def bbox_from_geojson(value: object) -> tuple[float, float, float, float]:
    """Compute a (min_x, min_y, max_x, max_y) bbox from GeoJSON-ish inputs."""

    def iter_positions(node: object) -> Iterable[tuple[float, float]]:
        if isinstance(node, dict):
            if "coordinates" in node:
                yield from iter_positions(node["coordinates"])
                return
            if node.get("type") == "Feature" and "geometry" in node:
                yield from iter_positions(node["geometry"])
                return
            if node.get("type") == "FeatureCollection" and "features" in node:
                for feature in node["features"]:
                    yield from iter_positions(feature)
                return
            if node.get("type") == "GeometryCollection" and "geometries" in node:
                for geom in node["geometries"]:
                    yield from iter_positions(geom)
                return

            for nested in node.values():
                yield from iter_positions(nested)
            return

        if isinstance(node, (list, tuple)):
            if (
                len(node) >= 2
                and isinstance(node[0], (int, float))
                and isinstance(node[1], (int, float))
            ):
                yield float(node[0]), float(node[1])
                return
            for nested in node:
                yield from iter_positions(nested)

    positions = list(iter_positions(value))
    if not positions:
        raise ValueError("GeoJSON contains no coordinates")

    xs = [x for x, _y in positions]
    ys = [y for _x, y in positions]
    return min(xs), min(ys), max(xs), max(ys)


class Product(Base):
    __tablename__ = "products"
    __table_args__ = (
        Index("ix_products_issued_at", "issued_at"),
        Index("ix_products_valid_from", "valid_from"),
        Index("ix_products_valid_to", "valid_to"),
        Index("ix_products_status", "status"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    title: Mapped[str] = mapped_column(String(256), nullable=False)
    text: Mapped[Optional[str]] = mapped_column(Text)
    issued_at: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    version: Mapped[int] = mapped_column(Integer, nullable=False, default=1)
    status: Mapped[str] = mapped_column(String(32), nullable=False, default="draft")
    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    hazards: Mapped[list["ProductHazard"]] = relationship(
        back_populates="product", cascade="all, delete-orphan"
    )
    versions: Mapped[list["ProductVersion"]] = relationship(
        back_populates="product",
        cascade="all, delete-orphan",
        order_by="ProductVersion.version",
    )


class ProductVersion(Base):
    __tablename__ = "product_versions"
    __table_args__ = (
        UniqueConstraint(
            "product_id",
            "version",
            name="uq_product_versions_product_id_version",
        ),
        Index("ix_product_versions_product_id", "product_id"),
        Index("ix_product_versions_published_at", "published_at"),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    version: Mapped[int] = mapped_column(Integer, nullable=False)
    snapshot: Mapped[object] = mapped_column(JSON, nullable=False)
    published_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True),
        nullable=False,
        server_default=func.now(),
    )

    product: Mapped["Product"] = relationship(back_populates="versions")


class ProductHazard(Base):
    __tablename__ = "product_hazards"
    __table_args__ = (
        Index("ix_product_hazards_product_id", "product_id"),
        Index("ix_product_hazards_valid_from", "valid_from"),
        Index("ix_product_hazards_valid_to", "valid_to"),
        Index(
            "ix_product_hazards_bbox",
            "bbox_min_x",
            "bbox_max_x",
            "bbox_min_y",
            "bbox_max_y",
        ),
    )

    id: Mapped[int] = mapped_column(Integer, primary_key=True)
    product_id: Mapped[int] = mapped_column(
        ForeignKey("products.id", ondelete="CASCADE"), nullable=False
    )
    severity: Mapped[str] = mapped_column(String(32), nullable=False)
    geometry: Mapped[object] = mapped_column(GeometryBlob(), nullable=False)
    valid_from: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False
    )
    valid_to: Mapped[datetime] = mapped_column(DateTime(timezone=True), nullable=False)

    bbox_min_x: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_min_y: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_max_x: Mapped[float] = mapped_column(Float, nullable=False)
    bbox_max_y: Mapped[float] = mapped_column(Float, nullable=False)

    created_at: Mapped[datetime] = mapped_column(
        DateTime(timezone=True), nullable=False, server_default=func.now()
    )

    product: Mapped["Product"] = relationship(back_populates="hazards")

    def set_geometry_from_geojson(self, geojson: object) -> None:
        self.geometry = geojson
        min_x, min_y, max_x, max_y = bbox_from_geojson(geojson)
        self.bbox_min_x = min_x
        self.bbox_min_y = min_y
        self.bbox_max_x = max_x
        self.bbox_max_y = max_y
