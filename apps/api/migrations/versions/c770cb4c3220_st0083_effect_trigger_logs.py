"""[ST-0083] Effect trigger logs (effect_trigger_logs)

Revision ID: c770cb4c3220
Revises: 21e9a72ac61b
Create Date: 2026-01-20 00:00:00.000000

"""

from __future__ import annotations

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = "c770cb4c3220"
down_revision: str | None = "21e9a72ac61b"
branch_labels: str | None = None
depends_on: str | None = None


def upgrade() -> None:
    op.create_table(
        "effect_trigger_logs",
        sa.Column("id", sa.Integer(), primary_key=True),
        sa.Column("effect_type", sa.String(length=64), nullable=False),
        sa.Column("triggered_at", sa.DateTime(timezone=True), nullable=False),
        sa.Column(
            "received_at",
            sa.DateTime(timezone=True),
            server_default=sa.text("now()"),
            nullable=False,
        ),
        sa.Column("client_id", sa.String(length=128), nullable=True),
        sa.Column("client", sa.String(length=64), nullable=True),
        sa.Column("fps", sa.Float(), nullable=True),
    )
    op.create_index(
        "ix_effect_trigger_logs_received_at", "effect_trigger_logs", ["received_at"]
    )
    op.create_index(
        "ix_effect_trigger_logs_triggered_at", "effect_trigger_logs", ["triggered_at"]
    )
    op.create_index(
        "ix_effect_trigger_logs_effect_type", "effect_trigger_logs", ["effect_type"]
    )
    op.create_index(
        "ix_effect_trigger_logs_client_id", "effect_trigger_logs", ["client_id"]
    )


def downgrade() -> None:
    op.drop_index("ix_effect_trigger_logs_client_id", table_name="effect_trigger_logs")
    op.drop_index(
        "ix_effect_trigger_logs_effect_type", table_name="effect_trigger_logs"
    )
    op.drop_index(
        "ix_effect_trigger_logs_triggered_at", table_name="effect_trigger_logs"
    )
    op.drop_index(
        "ix_effect_trigger_logs_received_at", table_name="effect_trigger_logs"
    )
    op.drop_table("effect_trigger_logs")
