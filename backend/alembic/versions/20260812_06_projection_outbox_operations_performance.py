"""Bound projection outbox operational aggregates to unfinished queue rows.

Revision ID: 20260812_06
Revises: 20260809_05
Create Date: 2026-08-12
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260812_06"
down_revision = "20260809_05"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Support bounded queue-state metrics without indexing processed history."""
    op.create_index(
        "ix_projection_outbox_operations_active",
        "projection_outbox",
        ["status", "available_at", "locked_at", "attempts"],
        unique=False,
        sqlite_where=sa.text("status IN ('pending', 'processing', 'failed')"),
        postgresql_where=sa.text("status IN ('pending', 'processing', 'failed')"),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Projection outbox operations performance migration is intentionally irreversible."
    )
