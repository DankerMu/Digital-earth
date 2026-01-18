"""[ST-0061] Forecast products schema (products/product_hazards)

Revision ID: 38d43e1089d1
Revises: 2ae88d292b32
Create Date: 2026-01-18 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "38d43e1089d1"
down_revision: str | None = "2ae88d292b32"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "products",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("title", sa.String(length=256), nullable=False),
        sa.Column("text", sa.Text(), nullable=True),
        sa.Column("issued_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column(
            "status",
            sa.String(length=32),
            server_default=sa.text("'draft'"),
            nullable=False,
        ),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_products_issued_at", "products", ["issued_at"])
    op.create_index("ix_products_status", "products", ["status"])
    op.create_index("ix_products_valid_from", "products", ["valid_from"])
    op.create_index("ix_products_valid_to", "products", ["valid_to"])

    op.create_table(
        "product_hazards",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("severity", sa.String(length=32), nullable=False),
        sa.Column("geometry", sa.LargeBinary(), nullable=False),
        sa.Column("valid_from", sa.DateTime(timezone=True), nullable=False),
        sa.Column("valid_to", sa.DateTime(timezone=True), nullable=False),
        sa.Column("bbox_min_x", sa.Float(), nullable=False),
        sa.Column("bbox_min_y", sa.Float(), nullable=False),
        sa.Column("bbox_max_x", sa.Float(), nullable=False),
        sa.Column("bbox_max_y", sa.Float(), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_product_hazards_product_id", "product_hazards", ["product_id"])
    op.create_index("ix_product_hazards_valid_from", "product_hazards", ["valid_from"])
    op.create_index("ix_product_hazards_valid_to", "product_hazards", ["valid_to"])
    op.create_index(
        "ix_product_hazards_bbox",
        "product_hazards",
        ["bbox_min_x", "bbox_max_x", "bbox_min_y", "bbox_max_y"],
    )


def downgrade() -> None:
    op.drop_index("ix_product_hazards_bbox", table_name="product_hazards")
    op.drop_index("ix_product_hazards_valid_to", table_name="product_hazards")
    op.drop_index("ix_product_hazards_valid_from", table_name="product_hazards")
    op.drop_index("ix_product_hazards_product_id", table_name="product_hazards")
    op.drop_table("product_hazards")
    op.drop_index("ix_products_valid_to", table_name="products")
    op.drop_index("ix_products_valid_from", table_name="products")
    op.drop_index("ix_products_status", table_name="products")
    op.drop_index("ix_products_issued_at", table_name="products")
    op.drop_table("products")
