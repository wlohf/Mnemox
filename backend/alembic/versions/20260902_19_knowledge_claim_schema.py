"""Add canonical Mnemox V2 source, revision, Claim, and Evidence schema.

Revision ID: 20260902_19
Revises: 20260901_18
Create Date: 2026-09-02
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260902_19"
down_revision = "20260901_18"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "knowledge_sources",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_type", sa.String(length=30), nullable=False),
        sa.Column("source_record_id", sa.Integer(), nullable=False),
        sa.Column("source_key", sa.String(length=160), nullable=False),
        sa.Column("title_snapshot", sa.String(length=200), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("current_revision", sa.Integer(), server_default="0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("current_revision >= 0", name="ck_knowledge_sources_current_revision"),
        sa.CheckConstraint("status IN ('active', 'deleting', 'deleted')", name="ck_knowledge_sources_status"),
        sa.CheckConstraint("source_type IN ('material', 'note')", name="ck_knowledge_sources_type"),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint("user_id", "source_key", name="uq_knowledge_sources_user_key"),
        sa.UniqueConstraint(
            "user_id",
            "source_type",
            "source_record_id",
            name="uq_knowledge_sources_user_record",
        ),
    )
    op.create_index("ix_knowledge_sources_user_id", "knowledge_sources", ["user_id"])
    op.create_index(
        "ix_knowledge_sources_user_status_updated",
        "knowledge_sources",
        ["user_id", "status", "updated_at"],
    )

    op.create_table(
        "knowledge_source_revisions",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_source_id", sa.Integer(), nullable=False),
        sa.Column("revision", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("title_snapshot", sa.String(length=200), server_default="", nullable=False),
        sa.Column("status", sa.String(length=20), server_default="current", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("superseded_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint("revision >= 1", name="ck_knowledge_source_revisions_revision"),
        sa.CheckConstraint(
            "status IN ('current', 'superseded', 'deleted')",
            name="ck_knowledge_source_revisions_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["knowledge_source_id"],
            ["knowledge_sources.id"],
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "knowledge_source_id",
            "revision",
            name="uq_knowledge_source_revisions_number",
        ),
    )
    op.create_index(
        "ix_knowledge_source_revisions_knowledge_source_id",
        "knowledge_source_revisions",
        ["knowledge_source_id"],
    )
    op.create_index(
        "ix_knowledge_source_revisions_user_id",
        "knowledge_source_revisions",
        ["user_id"],
    )
    op.create_index(
        "ix_knowledge_source_revisions_user_source",
        "knowledge_source_revisions",
        ["user_id", "knowledge_source_id"],
    )
    current_revision_predicate = sa.text("status = 'current'")
    op.create_index(
        "uq_knowledge_source_revisions_current",
        "knowledge_source_revisions",
        ["knowledge_source_id"],
        unique=True,
        sqlite_where=current_revision_predicate,
        postgresql_where=current_revision_predicate,
    )

    op.create_table(
        "knowledge_units",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_revision_id", sa.Integer(), nullable=False),
        sa.Column("parent_unit_id", sa.Integer(), nullable=True),
        sa.Column("unit_type", sa.String(length=30), nullable=False),
        sa.Column("ordinal", sa.Integer(), nullable=False),
        sa.Column("text", sa.Text(), nullable=False),
        sa.Column("text_hash", sa.String(length=64), nullable=False),
        sa.Column("locator", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("ordinal >= 0", name="ck_knowledge_units_ordinal"),
        sa.CheckConstraint(
            "unit_type IN ('chapter', 'chunk', 'note_body', 'message')",
            name="ck_knowledge_units_type",
        ),
        sa.ForeignKeyConstraint(["parent_unit_id"], ["knowledge_units.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["knowledge_source_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_revision_id",
            "unit_type",
            "ordinal",
            name="uq_knowledge_units_revision_type_ordinal",
        ),
    )
    op.create_index("ix_knowledge_units_parent_unit_id", "knowledge_units", ["parent_unit_id"])
    op.create_index(
        "ix_knowledge_units_source_revision_id",
        "knowledge_units",
        ["source_revision_id"],
    )
    op.create_index("ix_knowledge_units_user_id", "knowledge_units", ["user_id"])
    op.create_index(
        "ix_knowledge_units_user_revision",
        "knowledge_units",
        ["user_id", "source_revision_id"],
    )

    op.create_table(
        "claims",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("source_revision_id", sa.Integer(), nullable=False),
        sa.Column("statement", sa.String(length=500), nullable=False),
        sa.Column("claim_kind", sa.String(length=30), server_default="observation", nullable=False),
        sa.Column("fingerprint", sa.String(length=64), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("derivation_type", sa.String(length=20), server_default="manual", nullable=False),
        sa.Column("review_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("lifecycle_status", sa.String(length=20), server_default="active", nullable=False),
        sa.Column("extractor_version", sa.String(length=80), nullable=True),
        sa.Column("schema_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("model_version", sa.String(length=120), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("reviewed_at", sa.DateTime(), nullable=True),
        sa.CheckConstraint(
            "claim_kind IN ('definition', 'principle', 'causal', 'recommendation', "
            "'comparison', 'observation')",
            name="ck_claims_kind",
        ),
        sa.CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_claims_confidence"),
        sa.CheckConstraint(
            "derivation_type IN ('explicit', 'inferred', 'manual', 'migration')",
            name="ck_claims_derivation_type",
        ),
        sa.CheckConstraint(
            "lifecycle_status IN ('active', 'superseded', 'deleted')",
            name="ck_claims_lifecycle_status",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'confirmed', 'rejected')",
            name="ck_claims_review_status",
        ),
        sa.CheckConstraint("schema_version >= 1", name="ck_claims_schema_version"),
        sa.ForeignKeyConstraint(
            ["source_revision_id"],
            ["knowledge_source_revisions.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "source_revision_id",
            "fingerprint",
            name="uq_claims_revision_fingerprint",
        ),
    )
    op.create_index("ix_claims_source_revision_id", "claims", ["source_revision_id"])
    op.create_index("ix_claims_user_id", "claims", ["user_id"])
    op.create_index("ix_claims_user_revision", "claims", ["user_id", "source_revision_id"])
    op.create_index(
        "ix_claims_user_visibility",
        "claims",
        ["user_id", "lifecycle_status", "review_status", "updated_at"],
    )

    op.create_table(
        "claim_evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_unit_id", sa.Integer(), nullable=False),
        sa.Column("excerpt", sa.Text(), nullable=False),
        sa.Column("char_start", sa.Integer(), nullable=False),
        sa.Column("char_end", sa.Integer(), nullable=False),
        sa.Column("locator", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("grounding_method", sa.String(length=30), server_default="manual", nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("char_end > char_start", name="ck_claim_evidence_char_end"),
        sa.CheckConstraint("char_start >= 0", name="ck_claim_evidence_char_start"),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_claim_evidence_confidence",
        ),
        sa.CheckConstraint(
            "grounding_method IN ('exact_span', 'normalized_span', 'manual')",
            name="ck_claim_evidence_grounding_method",
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["knowledge_unit_id"],
            ["knowledge_units.id"],
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "claim_id",
            "knowledge_unit_id",
            "char_start",
            "char_end",
            name="uq_claim_evidence_span",
        ),
    )
    op.create_index("ix_claim_evidence_claim_id", "claim_evidence", ["claim_id"])
    op.create_index(
        "ix_claim_evidence_knowledge_unit_id",
        "claim_evidence",
        ["knowledge_unit_id"],
    )
    op.create_index("ix_claim_evidence_user_id", "claim_evidence", ["user_id"])
    op.create_index(
        "ix_claim_evidence_user_claim",
        "claim_evidence",
        ["user_id", "claim_id"],
    )
    op.create_index(
        "ix_claim_evidence_user_unit",
        "claim_evidence",
        ["user_id", "knowledge_unit_id"],
    )


def downgrade() -> None:
    op.drop_index("ix_claim_evidence_user_unit", table_name="claim_evidence")
    op.drop_index("ix_claim_evidence_user_claim", table_name="claim_evidence")
    op.drop_index("ix_claim_evidence_user_id", table_name="claim_evidence")
    op.drop_index("ix_claim_evidence_knowledge_unit_id", table_name="claim_evidence")
    op.drop_index("ix_claim_evidence_claim_id", table_name="claim_evidence")
    op.drop_table("claim_evidence")
    op.drop_index("ix_claims_user_visibility", table_name="claims")
    op.drop_index("ix_claims_user_revision", table_name="claims")
    op.drop_index("ix_claims_user_id", table_name="claims")
    op.drop_index("ix_claims_source_revision_id", table_name="claims")
    op.drop_table("claims")
    op.drop_index("ix_knowledge_units_user_revision", table_name="knowledge_units")
    op.drop_index("ix_knowledge_units_user_id", table_name="knowledge_units")
    op.drop_index("ix_knowledge_units_source_revision_id", table_name="knowledge_units")
    op.drop_index("ix_knowledge_units_parent_unit_id", table_name="knowledge_units")
    op.drop_table("knowledge_units")
    op.drop_index("uq_knowledge_source_revisions_current", table_name="knowledge_source_revisions")
    op.drop_index("ix_knowledge_source_revisions_user_source", table_name="knowledge_source_revisions")
    op.drop_index("ix_knowledge_source_revisions_user_id", table_name="knowledge_source_revisions")
    op.drop_index(
        "ix_knowledge_source_revisions_knowledge_source_id",
        table_name="knowledge_source_revisions",
    )
    op.drop_table("knowledge_source_revisions")
    op.drop_index("ix_knowledge_sources_user_status_updated", table_name="knowledge_sources")
    op.drop_index("ix_knowledge_sources_user_id", table_name="knowledge_sources")
    op.drop_table("knowledge_sources")
