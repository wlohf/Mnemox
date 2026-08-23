"""Add stable temporal-memory fact identity and conflict resolution history.

Revision ID: 20260823_12
Revises: 20260822_11
Create Date: 2026-08-23
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260823_12"
down_revision = "20260822_11"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "memory_declarations",
        sa.Column("fact_key", sa.String(length=100), nullable=False, server_default=""),
    )
    op.add_column(
        "memory_declarations",
        sa.Column("conflicts_with_id", sa.Integer(), nullable=True),
    )
    op.add_column(
        "memory_declarations",
        sa.Column("resolution_reason", sa.String(length=255), nullable=True),
    )
    op.execute(
        sa.text(
            "UPDATE memory_declarations SET fact_key = "
            "COALESCE((SELECT user_memories.memory_key FROM user_memories "
            "WHERE user_memories.id = memory_declarations.memory_id "
            "AND user_memories.user_id = memory_declarations.user_id), '') "
            "WHERE fact_key = ''"
        )
    )
    op.execute(
        sa.text(
            "WITH ranked_facts AS ("
            "SELECT memory_declarations.id, ROW_NUMBER() OVER ("
            "PARTITION BY memory_declarations.user_id, memory_declarations.fact_key "
            "ORDER BY COALESCE(user_memories.is_locked, 0) DESC, "
            "memory_declarations.observed_at DESC, memory_declarations.id DESC"
            ") AS duplicate_rank "
            "FROM memory_declarations "
            "LEFT JOIN user_memories ON user_memories.id = memory_declarations.memory_id "
            "AND user_memories.user_id = memory_declarations.user_id "
            "WHERE memory_declarations.review_status = 'confirmed' "
            "AND memory_declarations.valid_to IS NULL AND memory_declarations.fact_key != ''"
            ") UPDATE memory_declarations "
            "SET review_status = 'superseded', valid_to = CURRENT_TIMESTAMP, "
            "resolution_reason = 'migration_reconciled_duplicate_fact' "
            "WHERE id IN (SELECT id FROM ranked_facts WHERE duplicate_rank > 1)"
        )
    )
    op.execute(
        sa.text(
            "UPDATE user_memories SET status = 'superseded', review_status = 'superseded' "
            "WHERE EXISTS (SELECT 1 FROM memory_declarations "
            "WHERE memory_declarations.memory_id = user_memories.id "
            "AND memory_declarations.user_id = user_memories.user_id "
            "AND memory_declarations.resolution_reason = 'migration_reconciled_duplicate_fact') "
            "AND NOT EXISTS (SELECT 1 FROM memory_declarations "
            "WHERE memory_declarations.memory_id = user_memories.id "
            "AND memory_declarations.user_id = user_memories.user_id "
            "AND memory_declarations.review_status = 'confirmed' "
            "AND memory_declarations.valid_to IS NULL)"
        )
    )
    op.create_index(
        "ix_memory_declarations_conflicts_with_id",
        "memory_declarations",
        ["conflicts_with_id"],
    )
    op.create_index(
        "ix_memory_declarations_user_fact_review_valid",
        "memory_declarations",
        ["user_id", "fact_key", "review_status", "valid_to"],
    )
    current_fact_predicate = sa.text("review_status = 'confirmed' AND valid_to IS NULL AND fact_key != ''")
    op.create_index(
        "uq_memory_declarations_user_fact_current",
        "memory_declarations",
        ["user_id", "fact_key"],
        unique=True,
        sqlite_where=current_fact_predicate,
        postgresql_where=current_fact_predicate,
    )


def downgrade() -> None:
    op.drop_index("uq_memory_declarations_user_fact_current", table_name="memory_declarations")
    op.drop_index("ix_memory_declarations_user_fact_review_valid", table_name="memory_declarations")
    op.drop_index("ix_memory_declarations_conflicts_with_id", table_name="memory_declarations")
    op.drop_column("memory_declarations", "resolution_reason")
    op.drop_column("memory_declarations", "conflicts_with_id")
    op.drop_column("memory_declarations", "fact_key")
