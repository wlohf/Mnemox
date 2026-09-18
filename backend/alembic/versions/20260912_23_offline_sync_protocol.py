"""Add offline CRUD CAS versions and durable idempotency receipts.

Revision ID: 20260912_23
Revises: 20260903_22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260912_23"
down_revision = "20260903_22"
branch_labels = None
depends_on = None


_SYNC_TABLES = ("notes", "goals", "tasks", "anki_cards", "wrong_questions")


def upgrade() -> None:
    for table in _SYNC_TABLES:
        op.add_column(
            table,
            sa.Column("sync_version", sa.Integer(), nullable=False, server_default="1"),
        )
    op.create_table(
        "sync_receipts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("idempotency_key", sa.String(length=36), nullable=False),
        sa.Column("method", sa.String(length=10), nullable=False),
        sa.Column("path", sa.String(length=500), nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("status_code", sa.Integer(), nullable=True),
        sa.Column("response_body", sa.Text(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "idempotency_key", name="uq_sync_receipts_user_key"),
    )
    op.create_index("ix_sync_receipts_user_id", "sync_receipts", ["user_id"])


def downgrade() -> None:
    op.drop_table("sync_receipts")
    for table in reversed(_SYNC_TABLES):
        op.drop_column(table, "sync_version")
