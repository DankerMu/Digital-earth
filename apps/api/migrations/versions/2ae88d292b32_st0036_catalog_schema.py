"""[ST-0036] Catalog schema for ECMWF runs/times/assets

Revision ID: 2ae88d292b32
Revises:
Create Date: 2026-01-18 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "2ae88d292b32"
down_revision: str | None = None
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "ecmwf_runs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("run_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
    )
    op.create_index("ix_ecmwf_runs_run_time", "ecmwf_runs", ["run_time"], unique=True)

    op.create_table(
        "ecmwf_times",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("ecmwf_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("valid_time", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "created_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.UniqueConstraint("run_id", "valid_time", name="uq_ecmwf_times_run_valid"),
    )
    op.create_index("ix_ecmwf_times_valid_time", "ecmwf_times", ["valid_time"])

    op.create_table(
        "ecmwf_assets",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column(
            "run_id",
            sa.Integer(),
            sa.ForeignKey("ecmwf_runs.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column(
            "time_id",
            sa.Integer(),
            sa.ForeignKey("ecmwf_times.id", ondelete="CASCADE"),
            nullable=False,
        ),
        sa.Column("variable", sa.String(length=32), nullable=False),
        sa.Column("level", sa.String(length=32), nullable=False),
        sa.Column("status", sa.String(length=32), nullable=False),
        sa.Column(
            "version",
            sa.Integer(),
            server_default=sa.text("1"),
            nullable=False,
        ),
        sa.Column("path", sa.String(length=2048), nullable=False),
        sa.UniqueConstraint(
            "run_id",
            "time_id",
            "variable",
            "level",
            "version",
            name="uq_ecmwf_assets_identity",
        ),
    )


def downgrade() -> None:
    op.drop_table("ecmwf_assets")
    op.drop_index("ix_ecmwf_times_valid_time", table_name="ecmwf_times")
    op.drop_table("ecmwf_times")
    op.drop_index("ix_ecmwf_runs_run_time", table_name="ecmwf_runs")
    op.drop_table("ecmwf_runs")
