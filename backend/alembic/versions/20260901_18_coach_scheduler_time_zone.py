"""Add the learner time zone used by proactive Coach scheduling.

Revision ID: 20260901_18
Revises: 20260901_17
Create Date: 2026-09-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260901_18"
down_revision = "20260901_17"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "coach_preferences",
        sa.Column(
            "time_zone",
            sa.String(length=64),
            nullable=False,
            server_default="UTC",
        ),
    )


def downgrade() -> None:
    op.drop_column("coach_preferences", "time_zone")
