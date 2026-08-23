"""Add reviewable concept identity, source evidence and learner counters.

Revision ID: 20260822_11
Revises: 20260822_10
Create Date: 2026-08-22
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260822_11"
down_revision = "20260822_10"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.add_column("concepts", sa.Column("review_status", sa.String(length=20), nullable=False, server_default="confirmed"))
    op.add_column("concept_edges", sa.Column("review_status", sa.String(length=20), nullable=False, server_default="confirmed"))
    for column_name in ("attempt_count", "correct_count", "hint_count"):
        op.add_column(
            "user_concept_state",
            sa.Column(column_name, sa.Integer(), nullable=False, server_default="0"),
        )

    op.create_table(
        "concept_aliases",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.Integer(), nullable=False),
        sa.Column("alias", sa.String(length=120), nullable=False),
        sa.Column("alias_normalized", sa.String(length=120), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False, server_default="manual"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.UniqueConstraint("user_id", "alias_normalized", name="uq_concept_aliases_user_name"),
    )
    op.create_index("ix_concept_aliases_user_id", "concept_aliases", ["user_id"])
    op.create_index("ix_concept_aliases_concept_id", "concept_aliases", ["concept_id"])
    op.create_index("ix_concept_aliases_user_concept", "concept_aliases", ["user_id", "concept_id"])

    op.create_table(
        "concept_source_evidence",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.Integer(), nullable=False),
        sa.Column("edge_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=30), nullable=False, server_default="material"),
        sa.Column("source_id", sa.Integer(), nullable=False),
        sa.Column("source_version", sa.Integer(), nullable=False, server_default="1"),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False, server_default="0.8"),
        sa.Column("review_status", sa.String(length=20), nullable=False, server_default="pending"),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.Column("updated_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["edge_id"], ["concept_edges.id"], ondelete="CASCADE"),
        sa.CheckConstraint(
            "review_status IN ('pending', 'confirmed', 'rejected')",
            name="ck_concept_source_evidence_review_status",
        ),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_concept_source_evidence_confidence"),
        sa.CheckConstraint("source_version >= 1", name="ck_concept_source_evidence_source_version"),
    )
    op.create_index("ix_concept_source_evidence_user_id", "concept_source_evidence", ["user_id"])
    op.create_index("ix_concept_source_evidence_concept_id", "concept_source_evidence", ["concept_id"])
    op.create_index("ix_concept_source_evidence_edge_id", "concept_source_evidence", ["edge_id"])
    op.create_index(
        "ix_concept_source_evidence_user_source", "concept_source_evidence", ["user_id", "source_type", "source_id"],
    )
    op.create_index(
        "ix_concept_source_evidence_user_concept", "concept_source_evidence", ["user_id", "concept_id", "review_status"],
    )

    op.create_table(
        "concept_audit_events",
        sa.Column("id", sa.Integer(), primary_key=True, autoincrement=True),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.Integer(), nullable=True),
        sa.Column("operation", sa.String(length=40), nullable=False),
        sa.Column("actor", sa.String(length=30), nullable=False, server_default="user"),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), nullable=False, server_default=sa.text("CURRENT_TIMESTAMP")),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="SET NULL"),
    )
    op.create_index("ix_concept_audit_events_user_id", "concept_audit_events", ["user_id"])
    op.create_index("ix_concept_audit_events_concept_id", "concept_audit_events", ["concept_id"])
    op.create_index(
        "ix_concept_audit_events_user_concept", "concept_audit_events", ["user_id", "concept_id", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("concept_audit_events")
    op.drop_table("concept_source_evidence")
    op.drop_table("concept_aliases")
    for column_name in ("hint_count", "correct_count", "attempt_count"):
        op.drop_column("user_concept_state", column_name)
    op.drop_column("concept_edges", "review_status")
    op.drop_column("concepts", "review_status")
