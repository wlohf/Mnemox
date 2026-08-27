"""Add durable Coach action attempts and Pomodoro attribution.

Revision ID: 20260826_14
Revises: 20260826_13
Create Date: 2026-08-26
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260826_14"
down_revision = "20260826_13"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "coach_action_attempts",
        sa.Column("id", sa.String(length=40), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("nudge_id", sa.String(length=40), nullable=False),
        sa.Column("action_type", sa.String(length=80), nullable=False),
        sa.Column("route", sa.String(length=200), nullable=True),
        sa.Column("action_payload", sa.JSON(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("observed_at", sa.DateTime(), nullable=True),
        sa.Column("completed_at", sa.DateTime(), nullable=True),
        sa.Column("abandoned_at", sa.DateTime(), nullable=True),
        sa.Column("expires_at", sa.DateTime(), nullable=True),
        sa.Column("linked_event_id", sa.Integer(), nullable=True),
        sa.Column("linked_event_type", sa.String(length=80), nullable=True),
        sa.Column("outcome_source", sa.String(length=40), nullable=True),
        sa.Column("outcome_reason", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.func.now()),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_coach_action_attempts_user_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["nudge_id"], ["coach_nudges.id"], name="fk_coach_action_attempts_nudge_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["linked_event_id"], ["learning_events.id"], name="fk_coach_action_attempts_linked_event_id", ondelete="SET NULL"),
        sa.PrimaryKeyConstraint("id", name="pk_coach_action_attempts"),
    )
    op.create_index("ix_coach_action_attempts_user_id", "coach_action_attempts", ["user_id"], unique=False)
    op.create_index("ix_coach_action_attempts_nudge_id", "coach_action_attempts", ["nudge_id"], unique=False)
    op.create_index("ix_coach_action_attempts_status", "coach_action_attempts", ["status"], unique=False)
    op.create_index("ix_coach_action_attempts_started_at", "coach_action_attempts", ["started_at"], unique=False)
    op.create_index("ix_coach_action_attempts_linked_event_id", "coach_action_attempts", ["linked_event_id"], unique=False)
    op.create_index("ix_coach_action_attempts_user_nudge_status", "coach_action_attempts", ["user_id", "nudge_id", "status"], unique=False)
    op.add_column("pomodoros", sa.Column("coach_action_attempt_id", sa.String(length=40), nullable=True))
    op.create_index("ix_pomodoros_coach_action_attempt_id", "pomodoros", ["coach_action_attempt_id"], unique=False)


def downgrade() -> None:
    op.drop_index("ix_pomodoros_coach_action_attempt_id", table_name="pomodoros")
    op.drop_column("pomodoros", "coach_action_attempt_id")
    op.drop_index("ix_coach_action_attempts_user_nudge_status", table_name="coach_action_attempts")
    op.drop_index("ix_coach_action_attempts_linked_event_id", table_name="coach_action_attempts")
    op.drop_index("ix_coach_action_attempts_started_at", table_name="coach_action_attempts")
    op.drop_index("ix_coach_action_attempts_status", table_name="coach_action_attempts")
    op.drop_index("ix_coach_action_attempts_nudge_id", table_name="coach_action_attempts")
    op.drop_index("ix_coach_action_attempts_user_id", table_name="coach_action_attempts")
    op.drop_table("coach_action_attempts")
