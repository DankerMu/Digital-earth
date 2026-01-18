"""[ST-0062] Seed sample products

Revision ID: 2f3d78f91802
Revises: 21e9a72ac61b
Create Date: 2026-01-18 22:06:28.221666

"""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import sqlalchemy as sa
from alembic import op


# revision identifiers, used by Alembic.
revision: str = "2f3d78f91802"
down_revision: str | None = "21e9a72ac61b"
branch_labels: str | None = None
depends_on: str | None = None


_SAMPLE_MARKER = "[ST-0062 sample]"


def _encode_geojson(geojson: object) -> bytes:
    return json.dumps(geojson, ensure_ascii=False, separators=(",", ":")).encode(
        "utf-8"
    )


def upgrade() -> None:
    conn = op.get_bind()

    products = sa.table(
        "products",
        sa.column("id", sa.Integer),
        sa.column("title", sa.String),
        sa.column("text", sa.Text),
        sa.column("issued_at", sa.DateTime(timezone=True)),
        sa.column("valid_from", sa.DateTime(timezone=True)),
        sa.column("valid_to", sa.DateTime(timezone=True)),
        sa.column("version", sa.Integer),
        sa.column("status", sa.String),
    )
    hazards = sa.table(
        "product_hazards",
        sa.column("id", sa.Integer),
        sa.column("product_id", sa.Integer),
        sa.column("severity", sa.String),
        sa.column("geometry", sa.LargeBinary),
        sa.column("valid_from", sa.DateTime(timezone=True)),
        sa.column("valid_to", sa.DateTime(timezone=True)),
        sa.column("bbox_min_x", sa.Float),
        sa.column("bbox_min_y", sa.Float),
        sa.column("bbox_max_x", sa.Float),
        sa.column("bbox_max_y", sa.Float),
    )

    now = datetime.now(timezone.utc)
    valid_to = now + timedelta(days=3650)

    sample_products = [
        {
            "title": "降雪",
            "text": f"{_SAMPLE_MARKER} 降雪示例产品（低等级）",
            "issued_at": now,
            "valid_from": now,
            "valid_to": valid_to,
            "version": 1,
            "status": "published",
        },
        {
            "title": "大风",
            "text": f"{_SAMPLE_MARKER} 大风示例产品（中等级）",
            "issued_at": now,
            "valid_from": now,
            "valid_to": valid_to,
            "version": 1,
            "status": "published",
        },
        {
            "title": "强降水",
            "text": f"{_SAMPLE_MARKER} 强降水示例产品（高等级）",
            "issued_at": now,
            "valid_from": now,
            "valid_to": valid_to,
            "version": 1,
            "status": "published",
        },
    ]

    titles = [item["title"] for item in sample_products]
    existing_titles = set(
        conn.execute(
            sa.select(products.c.title).where(products.c.title.in_(titles))
        ).scalars()
    )
    to_insert = [
        item for item in sample_products if item["title"] not in existing_titles
    ]
    if to_insert:
        op.bulk_insert(products, to_insert)

    id_rows = conn.execute(
        sa.select(products.c.id, products.c.title).where(products.c.title.in_(titles))
    ).all()
    product_ids = {title: int(pid) for pid, title in id_rows}

    existing_hazard_product_ids = set(
        conn.execute(
            sa.select(hazards.c.product_id).where(
                hazards.c.product_id.in_(list(product_ids.values()))
            )
        ).scalars()
    )

    sample_hazards: list[dict[str, object]] = []

    snow_polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [126.0, 45.0],
                [127.0, 45.0],
                [127.0, 46.0],
                [126.0, 46.0],
                [126.0, 45.0],
            ]
        ],
    }
    wind_polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [85.0, 42.0],
                [86.5, 42.0],
                [86.5, 43.0],
                [85.0, 43.0],
                [85.0, 42.0],
            ]
        ],
    }
    rain_polygon = {
        "type": "Polygon",
        "coordinates": [
            [
                [112.0, 22.0],
                [114.0, 22.0],
                [114.0, 23.5],
                [112.0, 23.5],
                [112.0, 22.0],
            ]
        ],
    }

    def add_hazard(
        *,
        title: str,
        severity: str,
        geometry: dict,
        bbox: tuple[float, float, float, float],
    ) -> None:
        product_id = product_ids.get(title)
        if not product_id:
            return
        if product_id in existing_hazard_product_ids:
            return
        bbox_min_x, bbox_min_y, bbox_max_x, bbox_max_y = bbox
        sample_hazards.append(
            {
                "product_id": product_id,
                "severity": severity,
                "geometry": _encode_geojson(geometry),
                "valid_from": now,
                "valid_to": valid_to,
                "bbox_min_x": bbox_min_x,
                "bbox_min_y": bbox_min_y,
                "bbox_max_x": bbox_max_x,
                "bbox_max_y": bbox_max_y,
            }
        )

    add_hazard(
        title="降雪",
        severity="low",
        geometry=snow_polygon,
        bbox=(126.0, 45.0, 127.0, 46.0),
    )
    add_hazard(
        title="大风",
        severity="medium",
        geometry=wind_polygon,
        bbox=(85.0, 42.0, 86.5, 43.0),
    )
    add_hazard(
        title="强降水",
        severity="high",
        geometry=rain_polygon,
        bbox=(112.0, 22.0, 114.0, 23.5),
    )

    if sample_hazards:
        op.bulk_insert(hazards, sample_hazards)


def downgrade() -> None:
    conn = op.get_bind()

    products = sa.table(
        "products",
        sa.column("id", sa.Integer),
        sa.column("text", sa.Text),
    )
    hazards = sa.table(
        "product_hazards",
        sa.column("product_id", sa.Integer),
    )

    sample_ids = [
        int(pid)
        for pid in conn.execute(
            sa.select(products.c.id).where(products.c.text.like(f"%{_SAMPLE_MARKER}%"))
        ).scalars()
    ]
    if not sample_ids:
        return

    conn.execute(sa.delete(hazards).where(hazards.c.product_id.in_(sample_ids)))
    conn.execute(sa.delete(products).where(products.c.id.in_(sample_ids)))
