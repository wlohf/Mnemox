"""Store explicit identity candidates for legacy Vault path conflicts.

Revision ID: 20260816_08
Revises: 20260816_07
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260816_08"
down_revision = "20260816_07"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep unconfirmed Vault identity separate from the active note binding."""
    op.add_column("notes", sa.Column("source_conflict_vault_id", sa.String(length=160), nullable=True))
    op.add_column("notes", sa.Column("source_conflict_file_id", sa.String(length=160), nullable=True))


def downgrade() -> None:
    raise NotImplementedError(
        "Obsidian conflict identity migration is intentionally irreversible."
    )
