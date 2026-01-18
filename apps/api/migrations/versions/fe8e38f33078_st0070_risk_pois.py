"""[ST-0070] Risk POI schema

Revision ID: fe8e38f33078
Revises: 2ae88d292b32
Create Date: 2026-01-18 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "fe8e38f33078"
down_revision: str | None = "2ae88d292b32"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "risk_pois",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("name", sa.String(length=256), nullable=False),
        sa.Column("type", sa.String(length=64), nullable=False),
        sa.Column("lon", sa.Float(), nullable=False),
        sa.Column("lat", sa.Float(), nullable=False),
        sa.Column("alt", sa.Float(), nullable=True),
        sa.Column(
            "weight",
            sa.Float(),
            server_default=sa.text("1.0"),
            nullable=False,
        ),
        sa.Column("tags", sa.JSON(), nullable=True),
    )
    op.create_index("ix_risk_pois_geom", "risk_pois", ["lon", "lat"])
    op.create_index("ix_risk_pois_type", "risk_pois", ["type"])


def downgrade() -> None:
    op.drop_index("ix_risk_pois_type", table_name="risk_pois")
    op.drop_index("ix_risk_pois_geom", table_name="risk_pois")
    op.drop_table("risk_pois")
