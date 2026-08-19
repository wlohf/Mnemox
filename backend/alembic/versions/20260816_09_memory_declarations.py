"""Add canonical auditable memory declarations.

Revision ID: 20260816_09
Revises: 20260816_08
Create Date: 2026-08-16
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260816_09"
down_revision = "20260816_08"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep user-confirmed memory changes as immutable audit declarations."""
    op.create_table(
        "memory_declarations",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("memory_id", sa.Integer(), nullable=False),
        sa.Column("subject", sa.String(length=160), nullable=False),
        sa.Column("predicate", sa.String(length=80), nullable=False),
        sa.Column("value", sa.Text(), nullable=False),
        sa.Column("valid_from", sa.DateTime(), nullable=False),
        sa.Column("valid_to", sa.DateTime(), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default="confirmed"),
        sa.Column("source_event_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=50), nullable=False, server_default="manual"),
        sa.Column("source_id", sa.String(length=160), nullable=True),
        sa.Column("evidence", sa.Text(), nullable=True),
        sa.Column("created_by", sa.String(length=30), nullable=False, server_default="user"),
        sa.Column("model_version", sa.String(length=80), nullable=True),
        sa.Column("supersedes_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["memory_id"], ["user_memories.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["supersedes_id"], ["memory_declarations.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_memory_declarations_user_id", "memory_declarations", ["user_id"], unique=False)
    op.create_index("ix_memory_declarations_memory_id", "memory_declarations", ["memory_id"], unique=False)
    op.create_index(
        "ix_memory_declarations_review_status",
        "memory_declarations",
        ["review_status"],
        unique=False,
    )
    op.create_index(
        "ix_memory_declarations_user_memory_observed",
        "memory_declarations",
        ["user_id", "memory_id", "observed_at"],
        unique=False,
    )
    op.create_index(
        "ix_memory_declarations_user_review_observed",
        "memory_declarations",
        ["user_id", "review_status", "observed_at"],
        unique=False,
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Memory declaration audit history is intentionally irreversible."
    )
