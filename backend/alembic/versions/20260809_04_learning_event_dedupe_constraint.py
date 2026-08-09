"""Enforce durable user-scoped learning-event idempotency.

Revision ID: 20260809_04
Revises: 20260804_03
Create Date: 2026-08-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260809_04"
down_revision = "20260804_03"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Keep historical events while making future idempotency atomic."""
    # Older releases only performed a select-then-insert check. Retain the
    # oldest historical event and clear the duplicate idempotency keys before
    # creating the constraint, so migrations never delete ledger records.
    op.execute(
        """
        WITH ranked_events AS (
            SELECT
                id,
                ROW_NUMBER() OVER (
                    PARTITION BY user_id, event_type, dedupe_key
                    ORDER BY id ASC
                ) AS duplicate_rank
            FROM learning_events
            WHERE dedupe_key IS NOT NULL
        )
        UPDATE learning_events
        SET dedupe_key = NULL
        WHERE id IN (
            SELECT id FROM ranked_events WHERE duplicate_rank > 1
        )
        """
    )
    op.create_index(
        "uq_learning_events_user_type_dedupe",
        "learning_events",
        ["user_id", "event_type", "dedupe_key"],
        unique=True,
        sqlite_where=sa.text("dedupe_key IS NOT NULL"),
        postgresql_where=sa.text("dedupe_key IS NOT NULL"),
    )


def downgrade() -> None:
    op.drop_index("uq_learning_events_user_type_dedupe", table_name="learning_events")
