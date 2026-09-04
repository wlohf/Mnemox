"""Add Stage 4 ClaimRelation persistence.

Revision ID: 20260903_22
Revises: 20260903_21
Create Date: 2026-09-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_22"
down_revision = "20260903_21"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "claim_relations",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("from_claim_id", sa.Integer(), nullable=False),
        sa.Column("to_claim_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("derivation_type", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("review_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("rationale", sa.String(length=500), server_default="", nullable=False),
        sa.Column("evidence_provenance", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("evaluator_version", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("from_claim_id <> to_claim_id", name="ck_claim_relations_no_self_loop"),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_claim_relations_confidence"),
        sa.CheckConstraint("derivation_type IN ('explicit', 'inferred', 'manual', 'migration')", name="ck_claim_relations_derivation_type"),
        sa.CheckConstraint("relation_type IN ('supports', 'contradicts', 'refines', 'exemplifies', 'analogous_to')", name="ck_claim_relations_type"),
        sa.CheckConstraint("review_status IN ('pending', 'confirmed', 'rejected')", name="ck_claim_relations_review_status"),
        sa.ForeignKeyConstraint(["from_claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["to_claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "from_claim_id", "to_claim_id", "relation_type", name="uq_claim_relations_identity"),
    )
    for column in ("user_id", "from_claim_id", "to_claim_id"):
        op.create_index(f"ix_claim_relations_{column}", "claim_relations", [column])
    op.create_index("ix_claim_relations_user_from_review", "claim_relations", ["user_id", "from_claim_id", "review_status"])
    op.create_index("ix_claim_relations_user_to_review", "claim_relations", ["user_id", "to_claim_id", "review_status"])


def downgrade() -> None:
    op.drop_table("claim_relations")
