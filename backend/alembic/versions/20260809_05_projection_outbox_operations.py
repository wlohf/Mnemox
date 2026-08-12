"""Add outbox dead-letter state and durable worker heartbeats.

Revision ID: 20260809_05
Revises: 20260809_04
Create Date: 2026-08-09
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260809_05"
down_revision = "20260809_04"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Preserve terminal failures while making their DLQ state explicit."""
    op.add_column(
        "projection_outbox",
        sa.Column("dead_lettered_at", sa.DateTime(), nullable=True),
    )
    op.create_index(
        "ix_projection_outbox_dead_lettered_at",
        "projection_outbox",
        ["dead_lettered_at"],
        unique=False,
    )
    # Historical rows do not retain the configured retry cap, so this
    # migration must not guess whether they were terminal. Runtime
    # reconciliation persists the DLQ marker using the active deployment cap.
    op.create_table(
        "projection_outbox_worker_heartbeats",
        sa.Column("worker_id", sa.String(length=120), nullable=False),
        sa.Column("started_at", sa.DateTime(), nullable=False),
        sa.Column("last_heartbeat_at", sa.DateTime(), nullable=False),
        sa.Column("last_poll_at", sa.DateTime(), nullable=True),
        sa.Column("last_success_at", sa.DateTime(), nullable=True),
        sa.Column("last_error_at", sa.DateTime(), nullable=True),
        sa.Column("last_projection_failure_at", sa.DateTime(), nullable=True),
        sa.Column("stopped_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.PrimaryKeyConstraint("worker_id"),
    )
    op.create_index(
        "ix_projection_outbox_worker_heartbeats_last_heartbeat_at",
        "projection_outbox_worker_heartbeats",
        ["last_heartbeat_at"],
        unique=False,
    )
    op.create_table(
        "projection_outbox_retry_policy",
        sa.Column("id", sa.Integer(), nullable=False),
        sa.Column("max_attempts", sa.Integer(), nullable=False),
        sa.Column("policy_version", sa.Integer(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("id = 1", name="ck_projection_outbox_retry_policy_singleton"),
        sa.CheckConstraint("max_attempts >= 1", name="ck_projection_outbox_retry_policy_attempts"),
        sa.CheckConstraint("policy_version >= 1", name="ck_projection_outbox_retry_policy_version"),
        sa.PrimaryKeyConstraint("id"),
    )


def downgrade() -> None:
    raise NotImplementedError(
        "Projection outbox operations migration is intentionally irreversible."
    )
