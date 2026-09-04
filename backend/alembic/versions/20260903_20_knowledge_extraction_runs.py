"""Add durable Mnemox V2 knowledge extraction runs.

Revision ID: 20260903_20
Revises: 20260902_19
Create Date: 2026-09-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_20"
down_revision = "20260902_19"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_extraction_runs",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_revision_id", sa.Integer(), nullable=False),
        sa.Column("extractor_type", sa.String(length=30), nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=False),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("provider", sa.String(length=80), nullable=True),
        sa.Column("model", sa.String(length=120), nullable=True),
        sa.Column("prompt_hash", sa.String(length=64), nullable=True),
        sa.Column("input_hash", sa.String(length=64), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="queued", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("started_at", sa.DateTime(), nullable=True),
        sa.Column("finished_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("usage", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("stats", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("attempt_count >= 0", name="ck_knowledge_extraction_runs_attempt_count"),
        sa.CheckConstraint("schema_version >= 1", name="ck_knowledge_extraction_runs_schema_version"),
        sa.CheckConstraint(
            "extractor_type IN ('deterministic', 'llm', 'manual')",
            name="ck_knowledge_extraction_runs_type",
        ),
        sa.CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled')",
            name="ck_knowledge_extraction_runs_status",
        ),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["knowledge_source_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_revision_id",
            "extractor_type",
            "extractor_version",
            "schema_version",
            "input_hash",
            name="uq_knowledge_extraction_runs_identity",
        ),
    )
    op.create_index(
        "ix_knowledge_extraction_runs_available",
        "knowledge_extraction_runs",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_knowledge_extraction_runs_lease",
        "knowledge_extraction_runs",
        ["status", "locked_at"],
    )
    op.create_index(
        "ix_knowledge_extraction_runs_source_revision_id",
        "knowledge_extraction_runs",
        ["source_revision_id"],
    )
    op.create_index(
        "ix_knowledge_extraction_runs_user_id",
        "knowledge_extraction_runs",
        ["user_id"],
    )
    op.create_index(
        "ix_knowledge_extraction_runs_user_revision",
        "knowledge_extraction_runs",
        ["user_id", "source_revision_id"],
    )


def downgrade() -> None:
    op.drop_index(
        "ix_knowledge_extraction_runs_user_revision",
        table_name="knowledge_extraction_runs",
    )
    op.drop_index("ix_knowledge_extraction_runs_user_id", table_name="knowledge_extraction_runs")
    op.drop_index(
        "ix_knowledge_extraction_runs_source_revision_id",
        table_name="knowledge_extraction_runs",
    )
    op.drop_index("ix_knowledge_extraction_runs_lease", table_name="knowledge_extraction_runs")
    op.drop_index("ix_knowledge_extraction_runs_available", table_name="knowledge_extraction_runs")
    op.drop_table("knowledge_extraction_runs")
