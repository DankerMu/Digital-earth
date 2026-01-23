"""[ST-0078] Risk POI evaluations

Revision ID: 0f12a9b6c3d4
Revises: c770cb4c3220
Create Date: 2026-01-23 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "0f12a9b6c3d4"
down_revision: str | None = "c770cb4c3220"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "risk_poi_evaluations",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "poi_id",
            sa.Integer(),
            sa.ForeignKey("risk_pois.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "product_id",
            sa.Integer(),
            sa.ForeignKey("products.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("valid_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("risk_level", sa.Integer(), nullable=False),
        sa.Column(
            "evaluated_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "poi_id",
            "product_id",
            "valid_time",
            name="uq_risk_poi_evaluations_identity",
        ),
    )
    op.create_index("ix_risk_poi_evaluations_poi_id", "risk_poi_evaluations", ["poi_id"])
    op.create_index(
        "ix_risk_poi_evaluations_product_time",
        "risk_poi_evaluations",
        ["product_id", "valid_time"],
    )
    op.create_index(
        "ix_risk_poi_evaluations_valid_time", "risk_poi_evaluations", ["valid_time"]
    )


def downgrade() -> None:
    op.drop_index("ix_risk_poi_evaluations_valid_time", table_name="risk_poi_evaluations")
    op.drop_index(
        "ix_risk_poi_evaluations_product_time", table_name="risk_poi_evaluations"
    )
    op.drop_index("ix_risk_poi_evaluations_poi_id", table_name="risk_poi_evaluations")
    op.drop_table("risk_poi_evaluations")

