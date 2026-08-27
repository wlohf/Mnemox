"""Track Coach action starts and abandonments separately from acceptance.

Revision ID: 20260826_13
Revises: 20260823_12
Create Date: 2026-08-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260826_13"
down_revision = "20260823_12"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "coach_skill_stats",
        sa.Column("started_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "coach_skill_stats",
        sa.Column("abandoned_count", sa.Integer(), nullable=False, server_default="0"),
    )


def downgrade() -> None:
    op.drop_column("coach_skill_stats", "abandoned_count")
    op.drop_column("coach_skill_stats", "started_count")
