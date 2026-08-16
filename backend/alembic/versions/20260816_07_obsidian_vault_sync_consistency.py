"""Persist safe pull-sync identity, missing-file, and conflict state.

Revision ID: 20260816_07
Revises: 20260812_06
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260816_07"
down_revision = "20260812_06"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep vault identity and conflict candidates without deleting user notes."""
    op.add_column("notes", sa.Column("source_vault_id", sa.String(length=160), nullable=True))
    op.add_column("notes", sa.Column("source_file_id", sa.String(length=160), nullable=True))
    op.add_column("notes", sa.Column("source_sync_hash", sa.String(length=64), nullable=True))
    op.add_column("notes", sa.Column("source_sync_state", sa.String(length=20), nullable=True))
    op.add_column("notes", sa.Column("source_conflict_title", sa.String(length=200), nullable=True))
    op.add_column("notes", sa.Column("source_conflict_content", sa.Text(), nullable=True))
    op.add_column("notes", sa.Column("source_conflict_hash", sa.String(length=64), nullable=True))
    op.create_index("ix_notes_source_vault_id", "notes", ["source_vault_id"], unique=False)
    op.create_index("ix_notes_source_file_id", "notes", ["source_file_id"], unique=False)
    op.create_index("ix_notes_source_sync_state", "notes", ["source_sync_state"], unique=False)
    op.create_index(
        "uq_notes_source_identity",
        "notes",
        ["user_id", "source_vault_id", "source_file_id"],
        unique=True,
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Obsidian vault consistency migration is intentionally irreversible."
    )
