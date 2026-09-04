"""Add Stage 3 entity resolution and knowledge projection lifecycle.

Revision ID: 20260903_21
Revises: 20260903_20
Create Date: 2026-09-03
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260903_21"
down_revision = "20260903_20"
branch_labels = None
depends_on = None


def upgrade() -> None:
    op.create_table(
        "entity_resolution_candidates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("extraction_run_id", sa.Integer(), nullable=False),
        sa.Column("knowledge_unit_id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("mention_text", sa.String(length=120), nullable=False),
        sa.Column("mention_normalized", sa.String(length=120), nullable=False),
        sa.Column("mention_context", sa.String(length=500), server_default="", nullable=False),
        sa.Column("relation_type", sa.String(length=30), server_default="about", nullable=False),
        sa.Column("candidate_concept_id", sa.Integer(), nullable=True),
        sa.Column("exact_score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("alias_score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("lexical_score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("vector_score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("context_score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("combined_score", sa.Float(), server_default="0.0", nullable=False),
        sa.Column("decision", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("resolved_concept_id", sa.Integer(), nullable=True),
        sa.Column("decided_by", sa.String(length=20), nullable=True),
        sa.Column("decided_at", sa.DateTime(), nullable=True),
        sa.Column("identity_hash", sa.String(length=64), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "alias_score >= 0.0 AND alias_score <= 1.0",
            name="ck_entity_resolution_candidates_alias_score",
        ),
        sa.CheckConstraint(
            "combined_score >= 0.0 AND combined_score <= 1.0",
            name="ck_entity_resolution_candidates_combined_score",
        ),
        sa.CheckConstraint(
            "context_score >= 0.0 AND context_score <= 1.0",
            name="ck_entity_resolution_candidates_context_score",
        ),
        sa.CheckConstraint(
            "decided_by IS NULL OR decided_by IN ('rule', 'model', 'user')",
            name="ck_entity_resolution_candidates_decided_by",
        ),
        sa.CheckConstraint(
            "decision IN ('pending', 'accepted', 'rejected', 'create_new')",
            name="ck_entity_resolution_candidates_decision",
        ),
        sa.CheckConstraint(
            "exact_score >= 0.0 AND exact_score <= 1.0",
            name="ck_entity_resolution_candidates_exact_score",
        ),
        sa.CheckConstraint(
            "lexical_score >= 0.0 AND lexical_score <= 1.0",
            name="ck_entity_resolution_candidates_lexical_score",
        ),
        sa.CheckConstraint(
            "relation_type IN ('about', 'uses', 'applies_to', 'exemplifies')",
            name="ck_entity_resolution_candidates_relation_type",
        ),
        sa.CheckConstraint(
            "vector_score >= 0.0 AND vector_score <= 1.0",
            name="ck_entity_resolution_candidates_vector_score",
        ),
        sa.ForeignKeyConstraint(
            ["candidate_concept_id"], ["concepts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["extraction_run_id"], ["knowledge_extraction_runs.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["knowledge_unit_id"], ["knowledge_units.id"], ondelete="CASCADE"
        ),
        sa.ForeignKeyConstraint(
            ["resolved_concept_id"], ["concepts.id"], ondelete="SET NULL"
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "identity_hash",
            name="uq_entity_resolution_candidates_user_identity",
        ),
    )
    for column in (
        "candidate_concept_id",
        "claim_id",
        "extraction_run_id",
        "knowledge_unit_id",
        "resolved_concept_id",
        "user_id",
    ):
        op.create_index(
            f"ix_entity_resolution_candidates_{column}",
            "entity_resolution_candidates",
            [column],
        )
    op.create_index(
        "ix_entity_resolution_candidates_user_claim",
        "entity_resolution_candidates",
        ["user_id", "claim_id"],
    )
    op.create_index(
        "ix_entity_resolution_candidates_user_decision",
        "entity_resolution_candidates",
        ["user_id", "decision", "created_at"],
    )

    op.create_table(
        "claim_concept_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("claim_id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.Integer(), nullable=False),
        sa.Column("relation_type", sa.String(length=30), server_default="about", nullable=False),
        sa.Column("mention_text", sa.String(length=120), nullable=False),
        sa.Column("confidence", sa.Float(), server_default="1.0", nullable=False),
        sa.Column("derivation_type", sa.String(length=30), nullable=False),
        sa.Column("review_status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("resolution_candidate_id", sa.Integer(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_claim_concept_links_confidence",
        ),
        sa.CheckConstraint(
            "derivation_type IN ('canonical_exact', 'alias_exact', 'semantic', 'user', 'manual')",
            name="ck_claim_concept_links_derivation_type",
        ),
        sa.CheckConstraint(
            "relation_type IN ('about', 'uses', 'applies_to', 'exemplifies')",
            name="ck_claim_concept_links_relation_type",
        ),
        sa.CheckConstraint(
            "review_status IN ('pending', 'confirmed', 'rejected')",
            name="ck_claim_concept_links_review_status",
        ),
        sa.ForeignKeyConstraint(["claim_id"], ["claims.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(["concept_id"], ["concepts.id"], ondelete="CASCADE"),
        sa.ForeignKeyConstraint(
            ["resolution_candidate_id"],
            ["entity_resolution_candidates.id"],
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "claim_id",
            "concept_id",
            "relation_type",
            name="uq_claim_concept_links_identity",
        ),
    )
    for column in ("claim_id", "concept_id", "resolution_candidate_id", "user_id"):
        op.create_index(f"ix_claim_concept_links_{column}", "claim_concept_links", [column])
    op.create_index(
        "ix_claim_concept_links_user_claim_review",
        "claim_concept_links",
        ["user_id", "claim_id", "review_status"],
    )
    op.create_index(
        "ix_claim_concept_links_user_concept_review",
        "claim_concept_links",
        ["user_id", "concept_id", "review_status"],
    )

    op.create_table(
        "knowledge_embedding_projections",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("object_type", sa.String(length=30), nullable=False),
        sa.Column("object_id", sa.Integer(), nullable=False),
        sa.Column("content_hash", sa.String(length=64), nullable=False),
        sa.Column("configuration_fingerprint", sa.String(length=64), nullable=False),
        sa.Column("embedding_model", sa.String(length=160), nullable=False),
        sa.Column("collection", sa.String(length=160), nullable=False),
        sa.Column("vector_key", sa.String(length=200), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempt_count", sa.Integer(), server_default="0", nullable=False),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("indexed_at", sa.DateTime(), nullable=True),
        sa.Column("deleted_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "attempt_count >= 0",
            name="ck_knowledge_embedding_projections_attempt_count",
        ),
        sa.CheckConstraint(
            "object_type IN ('claim', 'concept', 'note_unit', 'material_unit')",
            name="ck_knowledge_embedding_projections_object_type",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'ready', 'degraded', 'failed', 'deleting', 'deleted')",
            name="ck_knowledge_embedding_projections_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "object_type",
            "object_id",
            "embedding_model",
            name="uq_knowledge_embedding_projections_identity",
        ),
        sa.UniqueConstraint(
            "vector_key",
            "collection",
            name="uq_knowledge_embedding_projections_vector",
        ),
    )
    op.create_index(
        "ix_knowledge_embedding_projections_user_id",
        "knowledge_embedding_projections",
        ["user_id"],
    )
    op.create_index(
        "ix_knowledge_embedding_projections_object",
        "knowledge_embedding_projections",
        ["user_id", "object_type", "object_id"],
    )
    op.create_index(
        "ix_knowledge_embedding_projections_user_status",
        "knowledge_embedding_projections",
        ["user_id", "status", "updated_at"],
    )

    op.create_table(
        "knowledge_projection_outbox",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("aggregate_type", sa.String(length=30), nullable=False),
        sa.Column("aggregate_id", sa.Integer(), nullable=False),
        sa.Column("aggregate_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("operation", sa.String(length=20), nullable=False),
        sa.Column(
            "projection_target",
            sa.String(length=40),
            server_default="chroma_knowledge",
            nullable=False,
        ),
        sa.Column("idempotency_key", sa.String(length=200), nullable=False),
        sa.Column("payload_version", sa.Integer(), server_default="1", nullable=False),
        sa.Column("payload", sa.JSON(), server_default=sa.text("'{}'"), nullable=False),
        sa.Column("status", sa.String(length=20), server_default="pending", nullable=False),
        sa.Column("attempts", sa.Integer(), server_default="0", nullable=False),
        sa.Column("available_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("locked_at", sa.DateTime(), nullable=True),
        sa.Column("lease_owner", sa.String(length=120), nullable=True),
        sa.Column("processed_at", sa.DateTime(), nullable=True),
        sa.Column("last_error", sa.String(length=500), nullable=True),
        sa.Column("dead_lettered_at", sa.DateTime(), nullable=True),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "aggregate_type IN ('source', 'revision', 'unit', 'claim', 'concept', 'relation', 'user')",
            name="ck_knowledge_projection_outbox_aggregate_type",
        ),
        sa.CheckConstraint("attempts >= 0", name="ck_knowledge_projection_outbox_attempts"),
        sa.CheckConstraint(
            "operation IN ('upsert', 'delete', 'rebuild_user')",
            name="ck_knowledge_projection_outbox_operation",
        ),
        sa.CheckConstraint(
            "payload_version >= 1",
            name="ck_knowledge_projection_outbox_payload_version",
        ),
        sa.CheckConstraint(
            "projection_target IN ('chroma_knowledge', 'sparse_knowledge', 'neo4j_graph')",
            name="ck_knowledge_projection_outbox_target",
        ),
        sa.CheckConstraint(
            "status IN ('pending', 'processing', 'processed', 'failed')",
            name="ck_knowledge_projection_outbox_status",
        ),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], ondelete="CASCADE"),
        sa.PrimaryKeyConstraint("id"),
        sa.UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_knowledge_projection_outbox_user_key",
        ),
    )
    op.create_index(
        "ix_knowledge_projection_outbox_user_id",
        "knowledge_projection_outbox",
        ["user_id"],
    )
    op.create_index(
        "ix_knowledge_projection_outbox_available",
        "knowledge_projection_outbox",
        ["status", "available_at", "created_at"],
    )
    op.create_index(
        "ix_knowledge_projection_outbox_dead_letter",
        "knowledge_projection_outbox",
        ["dead_lettered_at"],
    )
    op.create_index(
        "ix_knowledge_projection_outbox_lease",
        "knowledge_projection_outbox",
        ["status", "locked_at"],
    )
    op.create_index(
        "ix_knowledge_projection_outbox_user_status",
        "knowledge_projection_outbox",
        ["user_id", "status", "created_at"],
    )


def downgrade() -> None:
    op.drop_table("knowledge_projection_outbox")
    op.drop_table("knowledge_embedding_projections")
    op.drop_table("claim_concept_links")
    op.drop_table("entity_resolution_candidates")
