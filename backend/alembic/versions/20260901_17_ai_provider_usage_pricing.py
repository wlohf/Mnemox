"""Add user-configured AI provider pricing for usage reconciliation.

Revision ID: 20260901_17
Revises: 20260830_16
Create Date: 2026-09-01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260901_17"
down_revision = "20260830_16"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "ai_provider_settings",
        sa.Column("input_price_per_million", sa.Float(), nullable=True),
    )
    op.add_column(
        "ai_provider_settings",
        sa.Column("output_price_per_million", sa.Float(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("ai_provider_settings", "output_price_per_million")
    op.drop_column("ai_provider_settings", "input_price_per_million")
