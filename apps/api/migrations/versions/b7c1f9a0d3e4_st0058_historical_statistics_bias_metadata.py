"""[ST-0058] Historical statistics & bias metadata

Revision ID: b7c1f9a0d3e4
Revises: d2c4f6a8b0e1
Create Date: 2026-01-22 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "b7c1f9a0d3e4"
down_revision: str | None = "d2c4f6a8b0e1"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "historical_statistics",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("source", sa.String(length=32), nullable=False),
        sa.Column("variable", sa.String(length=64), nullable=False),
        sa.Column("window_kind", sa.String(length=32), nullable=False),
        sa.Column("window_key", sa.String(length=64), nullable=False),
        sa.Column("version", sa.String(length=32), nullable=False),
        sa.Column("window_start", sa.DateTime(timezone=True), nullable=False),
        sa.Column("window_end", sa.DateTime(timezone=True), nullable=False),
        sa.Column("samples", sa.Integer(), nullable=False),
        sa.Column("dataset_path", sa.String(length=2048), nullable=False),
        sa.Column("metadata_path", sa.String(length=2048), nullable=False),
        sa.Column("extra", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "source",
            "variable",
            "window_kind",
            "window_key",
            "version",
            name="uq_historical_statistics_identity",
        ),
    )
    op.create_index(
        "ix_historical_statistics_window_end", "historical_statistics", ["window_end"]
    )
    op.create_index(
        "ix_historical_statistics_variable", "historical_statistics", ["variable"]
    )

    op.create_table(
        "bias_tile_sets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("layer", sa.String(length=128), nullable=False),
        sa.Column("time_key", sa.String(length=32), nullable=False),
        sa.Column("level_key", sa.String(length=32), nullable=False),
        sa.Column("min_zoom", sa.Integer(), nullable=False),
        sa.Column("max_zoom", sa.Integer(), nullable=False),
        sa.Column("formats", sa.JSON(), server_default=sa.text("'[]'"), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint(
            "layer", "time_key", "level_key", name="uq_bias_tile_sets_identity"
        ),
    )
    op.create_index("ix_bias_tile_sets_layer", "bias_tile_sets", ["layer"])
    op.create_index("ix_bias_tile_sets_time_key", "bias_tile_sets", ["time_key"])


def downgrade() -> None:
    op.drop_index("ix_bias_tile_sets_time_key", table_name="bias_tile_sets")
    op.drop_index("ix_bias_tile_sets_layer", table_name="bias_tile_sets")
    op.drop_table("bias_tile_sets")

    op.drop_index(
        "ix_historical_statistics_variable", table_name="historical_statistics"
    )
    op.drop_index(
        "ix_historical_statistics_window_end", table_name="historical_statistics"
    )
    op.drop_table("historical_statistics")

