"""Add account session and login-throttle state.

Revision ID: 20260827_15
Revises: 20260826_14
Create Date: 2026-08-27
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260827_15"
down_revision = "20260826_14"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column(
        "users",
        sa.Column("token_version", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("failed_login_count", sa.Integer(), nullable=False, server_default="0"),
    )
    op.add_column(
        "users",
        sa.Column("login_failed_window_started_at", sa.DateTime(), nullable=True),
    )
    op.add_column(
        "users",
        sa.Column("login_locked_until", sa.DateTime(), nullable=True),
    )


def downgrade() -> None:
    op.drop_column("users", "login_locked_until")
    op.drop_column("users", "login_failed_window_started_at")
    op.drop_column("users", "failed_login_count")
    op.drop_column("users", "token_version")
