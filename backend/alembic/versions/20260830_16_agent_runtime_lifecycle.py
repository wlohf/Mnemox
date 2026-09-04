"""Add durable AgentRuntime scheduling and job lifecycle state.

Revision ID: 20260830_16
Revises: 20260827_15
Create Date: 2026-08-30
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260830_16"
down_revision = "20260827_15"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("agent_jobs", sa.Column("scenario", sa.String(length=100), nullable=True))
    op.add_column("agent_jobs", sa.Column("run_key", sa.String(length=160), nullable=True))
    op.add_column(
        "agent_jobs",
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column("agent_jobs", sa.Column("scheduled_for", sa.DateTime(), nullable=True))
    op.add_column("agent_jobs", sa.Column("started_at", sa.DateTime(), nullable=True))
    op.add_column("agent_jobs", sa.Column("finished_at", sa.DateTime(), nullable=True))
    op.add_column("agent_jobs", sa.Column("cancel_requested_at", sa.DateTime(), nullable=True))
    op.add_column("agent_jobs", sa.Column("resumed_from_job_id", sa.String(length=32), nullable=True))
    op.add_column("agent_jobs", sa.Column("lease_owner", sa.String(length=64), nullable=True))
    op.add_column("agent_jobs", sa.Column("lease_expires_at", sa.DateTime(), nullable=True))
    op.add_column("agent_jobs", sa.Column("checkpoint", sa.JSON(), nullable=True))
    op.create_index("ix_agent_jobs_scenario", "agent_jobs", ["scenario"], unique=False)
    op.create_index("ix_agent_jobs_scheduled_for", "agent_jobs", ["scheduled_for"], unique=False)
    op.create_index("ix_agent_jobs_resumed_from_job_id", "agent_jobs", ["resumed_from_job_id"], unique=False)
    op.create_index("ix_agent_jobs_lease_expires_at", "agent_jobs", ["lease_expires_at"], unique=False)
    op.create_index(
        "uq_agent_jobs_user_run_key",
        "agent_jobs",
        ["user_id", "run_key"],
        unique=True,
    )
    op.create_table(
        "agent_action_confirmations",
        sa.Column("id", sa.String(length=32), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("job_id", sa.String(length=32), nullable=False),
        sa.Column("action_id", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("action_snapshot", sa.JSON(), nullable=False),
        sa.Column("draft", sa.JSON(), nullable=False),
        sa.Column("result", sa.JSON(), nullable=True),
        sa.Column("confirmed_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.PrimaryKeyConstraint("id"),
    )
    op.create_index(
        "ix_agent_action_confirmations_user_id",
        "agent_action_confirmations",
        ["user_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_action_confirmations_job_id",
        "agent_action_confirmations",
        ["job_id"],
        unique=False,
    )
    op.create_index(
        "ix_agent_action_confirmations_status",
        "agent_action_confirmations",
        ["status"],
        unique=False,
    )
    op.create_index(
        "ix_agent_action_confirmations_created_at",
        "agent_action_confirmations",
        ["created_at"],
        unique=False,
    )
    op.create_index(
        "uq_agent_action_confirmations_user_job_action",
        "agent_action_confirmations",
        ["user_id", "job_id", "action_id"],
        unique=True,
    )

    op.add_column("coach_preferences", sa.Column("proactive_last_evaluated_at", sa.DateTime(), nullable=True))
    op.add_column("coach_preferences", sa.Column("proactive_next_evaluate_at", sa.DateTime(), nullable=True))
    op.add_column(
        "coach_preferences",
        sa.Column("proactive_failure_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.create_index(
        "ix_coach_preferences_proactive_next_evaluate_at",
        "coach_preferences",
        ["proactive_next_evaluate_at"],
        unique=False,
    )


def downgrade() -> None:
    op.drop_index("ix_coach_preferences_proactive_next_evaluate_at", table_name="coach_preferences")
    op.drop_column("coach_preferences", "proactive_failure_count")
    op.drop_column("coach_preferences", "proactive_next_evaluate_at")
    op.drop_column("coach_preferences", "proactive_last_evaluated_at")

    op.drop_index(
        "uq_agent_action_confirmations_user_job_action",
        table_name="agent_action_confirmations",
    )
    op.drop_index("ix_agent_action_confirmations_created_at", table_name="agent_action_confirmations")
    op.drop_index("ix_agent_action_confirmations_status", table_name="agent_action_confirmations")
    op.drop_index("ix_agent_action_confirmations_job_id", table_name="agent_action_confirmations")
    op.drop_index("ix_agent_action_confirmations_user_id", table_name="agent_action_confirmations")
    op.drop_table("agent_action_confirmations")

    op.drop_index("uq_agent_jobs_user_run_key", table_name="agent_jobs")
    op.drop_index("ix_agent_jobs_lease_expires_at", table_name="agent_jobs")
    op.drop_index("ix_agent_jobs_resumed_from_job_id", table_name="agent_jobs")
    op.drop_index("ix_agent_jobs_scheduled_for", table_name="agent_jobs")
    op.drop_index("ix_agent_jobs_scenario", table_name="agent_jobs")
    op.drop_column("agent_jobs", "resumed_from_job_id")
    op.drop_column("agent_jobs", "checkpoint")
    op.drop_column("agent_jobs", "lease_expires_at")
    op.drop_column("agent_jobs", "lease_owner")
    op.drop_column("agent_jobs", "cancel_requested_at")
    op.drop_column("agent_jobs", "finished_at")
    op.drop_column("agent_jobs", "started_at")
    op.drop_column("agent_jobs", "scheduled_for")
    op.drop_column("agent_jobs", "attempt_count")
    op.drop_column("agent_jobs", "run_key")
    op.drop_column("agent_jobs", "scenario")
