"""Add durable learner projection outbox.

Revision ID: 20260804_02
Revises: 20260804_01
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa

revision = "20260804_02"
down_revision = "20260804_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "projection_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.Integer(), nullable=True),
        sa.Column("source_event_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("projection_type", sa.String(length=60), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("payload_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("occurred_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("status", sa.String(length=20), nullable=False),
        sa.Column("attempts", sa.Integer(), nullable=False),
        sa.Column("available_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("status IN ('pending', 'processing', 'processed', 'failed')", name="ck_projection_outbox_status"),
        sa.CheckConstraint("attempts >= 0", name="ck_projection_outbox_attempts"),
        sa.CheckConstraint("payload_version >= 1", name="ck_projection_outbox_payload_version"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_projection_outbox_user_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], name="fk_projection_outbox_concept_id", ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["source_event_id"], ["learning_events.id"], name="fk_projection_outbox_source_event_id", ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id", name="pk_projection_outbox"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_projection_outbox_user_key"),
    )
    op.create_index("ix_projection_outbox_user_id", "projection_outbox", ["user_id"], unique=False)
    op.create_index("ix_projection_outbox_concept_id", "projection_outbox", ["concept_id"], unique=False)
    op.create_index("ix_projection_outbox_source_event_id", "projection_outbox", ["source_event_id"], unique=False)
    op.create_index("ix_projection_outbox_status", "projection_outbox", ["status"], unique=False)
    op.create_index("ix_projection_outbox_available_at", "projection_outbox", ["available_at"], unique=False)
    op.create_index("ix_projection_outbox_occurred_at", "projection_outbox", ["occurred_at"], unique=False)
    op.create_index("ix_projection_outbox_pending", "projection_outbox", ["status", "available_at", "id"], unique=False)
    op.create_index("ix_projection_outbox_user_concept_time", "projection_outbox", ["user_id", "concept_id", "occurred_at"], unique=False)


def downgrade() -> None:
    raise NotImplementedError("Projection outbox data is replayable but downgrade is intentionally manual.")
