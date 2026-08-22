"""Add durable retrieval lifecycle state and rebuildable SQL chunk manifests.

Revision ID: 20260822_10
Revises: 20260816_09
Create Date: 2026-08-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260822_10"
down_revision = "20260816_09"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "retrieval_projections",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False, server_default="material"),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("backend", sa.String(length=30), nullable=False, server_default="chroma"),
        sa.Column("status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("last_operation", sa.String(length=20), nullable=False, server_default="ingest"),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("indexed_version", sa.Integer(), nullable=True),
        sa.Column("source_signature", sa.String(length=64), nullable=True),
        sa.Column("content_hash", sa.String(length=64), nullable=True),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=True),
        sa.Column("embedding_model", sa.String(length=160), nullable=True),
        sa.Column("chunk_size", sa.Integer(), nullable=True),
        sa.Column("chunk_overlap", sa.Integer(), nullable=True),
        sa.Column("chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("vector_chunk_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("attempt_count", sa.Integer(), nullable=False, server_default="0"),
        sa.Column("last_error", sa.Text(), nullable=True),
        sa.Column("last_indexed_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint(
            "user_id", "source_type", "source_id", "backend",
            name="uq_retrieval_projection_source_backend",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'indexing', 'ready', 'degraded', 'failed', 'deleting', 'deleted')",
            name="ck_retrieval_projection_status",
        ),
        sa.CheckConstraint("source_version >= 1", name="ck_retrieval_projection_source_version"),
        sa.CheckConstraint("attempt_count >= 0", name="ck_retrieval_projection_attempt_count"),
        sa.CheckConstraint("chunk_count >= 0", name="ck_retrieval_projection_chunk_count"),
        sa.CheckConstraint("vector_chunk_count >= 0", name="ck_retrieval_projection_vector_chunk_count"),
    )
    op.create_index("ix_retrieval_projections_user_id", "retrieval_projections", ["user_id"])
    op.create_index(
        "ix_retrieval_projections_user_status",
        "retrieval_projections",
        ["user_id", "status", "updated_at"],
    )

    op.create_table(
        "retrieval_projection_chunks",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("projection_id", sa.Integer(), nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False, server_default="material"),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("chunk_index", sa.Integer(), nullable=False),
        sa.Column("chunk_hash", sa.String(length=64), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["projection_id"], ["retrieval_projections.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("projection_id", "chunk_index", name="uq_retrieval_projection_chunk"),
        sa.CheckConstraint("chunk_index >= 0", name="ck_retrieval_projection_chunk_index"),
        sa.CheckConstraint("source_version >= 1", name="ck_retrieval_chunk_source_version"),
    )
    op.create_index("ix_retrieval_projection_chunks_projection_id", "retrieval_projection_chunks", ["projection_id"])
    op.create_index("ix_retrieval_projection_chunks_user_id", "retrieval_projection_chunks", ["user_id"])
    op.create_index(
        "ix_retrieval_projection_chunks_user_source",
        "retrieval_projection_chunks",
        ["user_id", "source_type", "source_id"],
    )


def downgrade() -> None:
    op.drop_table("retrieval_projection_chunks")
    op.drop_table("retrieval_projections")
