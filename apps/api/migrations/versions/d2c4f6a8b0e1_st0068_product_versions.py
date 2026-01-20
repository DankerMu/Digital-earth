"""[ST-0068] Product version snapshots

Revision ID: d2c4f6a8b0e1
Revises: 2f3d78f91802, c770cb4c3220
Create Date: 2026-01-20 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "d2c4f6a8b0e1"
down_revision: tuple[str, str] = ("2f3d78f91802", "c770cb4c3220")
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "product_versions",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("version", sa.Integer(), nullable=False),
        sa.Column("snapshot", sa.JSON(), nullable=False),
        sa.Column(
            "published_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "product_id",
            "version",
            name="uq_product_versions_product_id_version",
        ),
    )
    op.create_index(
        "ix_product_versions_product_id", "product_versions", ["product_id"]
    )
    op.create_index(
        "ix_product_versions_published_at", "product_versions", ["published_at"]
    )


def downgrade() -> None:
    op.drop_index("ix_product_versions_published_at", table_name="product_versions")
    op.drop_index("ix_product_versions_product_id", table_name="product_versions")
    op.drop_table("product_versions")
