"""Canonical Mnemox V2 source, revision, Claim, and Evidence models.

SQL remains the authority for ownership, lifecycle, review, and deletion.
Chroma may consume the rebuildable Stage 3 knowledge projection; Neo4j and
Graphiti remain later-stage shadow candidates only.
"""
from __future__ import annotations

from sqlalchemy import (
    JSON,
    CheckConstraint,
    Column,
    DateTime,
    Float,
    ForeignKey,
    Index,
    Integer,
    String,
    Text,
    UniqueConstraint,
    text,
)
from sqlalchemy.orm import relationship
from sqlalchemy.sql import func

from app.database import Base


class KnowledgeSource(Base):
    """Stable user-owned identity for a Material or Note."""

    __tablename__ = "knowledge_sources"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "source_type",
            "source_record_id",
            name="uq_knowledge_sources_user_record",
        ),
        UniqueConstraint("user_id", "source_key", name="uq_knowledge_sources_user_key"),
        CheckConstraint(
            "source_type IN ('material', 'note')",
            name="ck_knowledge_sources_type",
        ),
        CheckConstraint(
            "status IN ('active', 'deleting', 'deleted')",
            name="ck_knowledge_sources_status",
        ),
        CheckConstraint(
            "current_revision >= 0",
            name="ck_knowledge_sources_current_revision",
        ),
        Index("ix_knowledge_sources_user_status_updated", "user_id", "status", "updated_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_type = Column(String(30), nullable=False)
    source_record_id = Column(Integer, nullable=False)
    source_key = Column(String(160), nullable=False)
    title_snapshot = Column(String(200), nullable=False, default="", server_default="")
    status = Column(String(20), nullable=False, default="active", server_default="active")
    current_revision = Column(Integer, nullable=False, default=0, server_default="0")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    deleted_at = Column(DateTime, nullable=True)

    revisions = relationship(
        "KnowledgeSourceRevision",
        back_populates="source",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KnowledgeSourceRevision(Base):
    """Immutable identity for one version of a canonical source."""

    __tablename__ = "knowledge_source_revisions"
    __table_args__ = (
        UniqueConstraint(
            "knowledge_source_id",
            "revision",
            name="uq_knowledge_source_revisions_number",
        ),
        CheckConstraint("revision >= 1", name="ck_knowledge_source_revisions_revision"),
        CheckConstraint(
            "status IN ('current', 'superseded', 'deleted')",
            name="ck_knowledge_source_revisions_status",
        ),
        Index(
            "uq_knowledge_source_revisions_current",
            "knowledge_source_id",
            unique=True,
            sqlite_where=text("status = 'current'"),
            postgresql_where=text("status = 'current'"),
        ),
        Index(
            "ix_knowledge_source_revisions_user_source",
            "user_id",
            "knowledge_source_id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_source_id = Column(
        Integer,
        ForeignKey("knowledge_sources.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    revision = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    title_snapshot = Column(String(200), nullable=False, default="", server_default="")
    status = Column(String(20), nullable=False, default="current", server_default="current")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    superseded_at = Column(DateTime, nullable=True)

    source = relationship("KnowledgeSource", back_populates="revisions")
    units = relationship(
        "KnowledgeUnit",
        back_populates="source_revision",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    claims = relationship(
        "Claim",
        back_populates="source_revision",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )
    extraction_runs = relationship(
        "KnowledgeExtractionRun",
        back_populates="source_revision",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KnowledgeUnit(Base):
    """Versioned source slice with a stable locator."""

    __tablename__ = "knowledge_units"
    __table_args__ = (
        UniqueConstraint(
            "source_revision_id",
            "unit_type",
            "ordinal",
            name="uq_knowledge_units_revision_type_ordinal",
        ),
        CheckConstraint(
            "unit_type IN ('chapter', 'chunk', 'note_body', 'message')",
            name="ck_knowledge_units_type",
        ),
        CheckConstraint("ordinal >= 0", name="ck_knowledge_units_ordinal"),
        Index("ix_knowledge_units_user_revision", "user_id", "source_revision_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_revision_id = Column(
        Integer,
        ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    parent_unit_id = Column(
        Integer,
        ForeignKey("knowledge_units.id", ondelete="CASCADE"),
        nullable=True,
        index=True,
    )
    unit_type = Column(String(30), nullable=False)
    ordinal = Column(Integer, nullable=False)
    text = Column(Text, nullable=False)
    text_hash = Column(String(64), nullable=False)
    locator = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    source_revision = relationship("KnowledgeSourceRevision", back_populates="units")
    parent = relationship("KnowledgeUnit", remote_side=[id])
    evidence = relationship(
        "ClaimEvidence",
        back_populates="knowledge_unit",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class KnowledgeExtractionRun(Base):
    """Durable, idempotent extraction audit row and recoverable lease."""

    __tablename__ = "knowledge_extraction_runs"
    __table_args__ = (
        UniqueConstraint(
            "source_revision_id",
            "extractor_type",
            "extractor_version",
            "schema_version",
            "input_hash",
            name="uq_knowledge_extraction_runs_identity",
        ),
        CheckConstraint(
            "extractor_type IN ('deterministic', 'llm', 'manual')",
            name="ck_knowledge_extraction_runs_type",
        ),
        CheckConstraint(
            "status IN ('queued', 'running', 'succeeded', 'partial', 'failed', 'cancelled')",
            name="ck_knowledge_extraction_runs_status",
        ),
        CheckConstraint("attempt_count >= 0", name="ck_knowledge_extraction_runs_attempt_count"),
        CheckConstraint("schema_version >= 1", name="ck_knowledge_extraction_runs_schema_version"),
        Index(
            "ix_knowledge_extraction_runs_available",
            "status",
            "available_at",
            "created_at",
        ),
        Index(
            "ix_knowledge_extraction_runs_user_revision",
            "user_id",
            "source_revision_id",
        ),
        Index("ix_knowledge_extraction_runs_lease", "status", "locked_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_revision_id = Column(
        Integer,
        ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    extractor_type = Column(String(30), nullable=False)
    extractor_version = Column(String(80), nullable=False)
    schema_version = Column(Integer, nullable=False, default=1, server_default="1")
    provider = Column(String(80), nullable=True)
    model = Column(String(120), nullable=True)
    prompt_hash = Column(String(64), nullable=True)
    input_hash = Column(String(64), nullable=False)
    status = Column(String(20), nullable=False, default="queued", server_default="queued")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    available_at = Column(DateTime, nullable=False, server_default=func.now())
    locked_at = Column(DateTime, nullable=True)
    lease_owner = Column(String(120), nullable=True)
    started_at = Column(DateTime, nullable=True)
    finished_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    usage = Column(JSON, nullable=False, default=dict, server_default="{}")
    stats = Column(JSON, nullable=False, default=dict, server_default="{}")
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())

    source_revision = relationship("KnowledgeSourceRevision", back_populates="extraction_runs")


class Claim(Base):
    """One atomic statement made by one source revision."""

    __tablename__ = "claims"
    __table_args__ = (
        UniqueConstraint(
            "source_revision_id",
            "fingerprint",
            name="uq_claims_revision_fingerprint",
        ),
        CheckConstraint(
            "claim_kind IN ('definition', 'principle', 'causal', 'recommendation', "
            "'comparison', 'observation')",
            name="ck_claims_kind",
        ),
        CheckConstraint(
            "derivation_type IN ('explicit', 'inferred', 'manual', 'migration')",
            name="ck_claims_derivation_type",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'confirmed', 'rejected')",
            name="ck_claims_review_status",
        ),
        CheckConstraint(
            "lifecycle_status IN ('active', 'superseded', 'deleted')",
            name="ck_claims_lifecycle_status",
        ),
        CheckConstraint("confidence >= 0.0 AND confidence <= 1.0", name="ck_claims_confidence"),
        CheckConstraint("schema_version >= 1", name="ck_claims_schema_version"),
        Index(
            "ix_claims_user_visibility",
            "user_id",
            "lifecycle_status",
            "review_status",
            "updated_at",
        ),
        Index("ix_claims_user_revision", "user_id", "source_revision_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    source_revision_id = Column(
        Integer,
        ForeignKey("knowledge_source_revisions.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    statement = Column(String(500), nullable=False)
    claim_kind = Column(String(30), nullable=False, default="observation", server_default="observation")
    fingerprint = Column(String(64), nullable=False)
    confidence = Column(Float, nullable=False, default=1.0, server_default="1.0")
    derivation_type = Column(String(20), nullable=False, default="manual", server_default="manual")
    # Conservative schema default: only the manual-creation service promotes a
    # grounded Claim to confirmed. Later automatic extractors must never become
    # product-visible merely because a caller omitted review_status.
    review_status = Column(String(20), nullable=False, default="pending", server_default="pending")
    lifecycle_status = Column(String(20), nullable=False, default="active", server_default="active")
    extractor_version = Column(String(80), nullable=True)
    schema_version = Column(Integer, nullable=False, default=1, server_default="1")
    model_version = Column(String(120), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    reviewed_at = Column(DateTime, nullable=True)

    source_revision = relationship("KnowledgeSourceRevision", back_populates="claims")
    evidence = relationship(
        "ClaimEvidence",
        back_populates="claim",
        cascade="all, delete-orphan",
        passive_deletes=True,
    )


class ClaimEvidence(Base):
    """Exact or manually selected source location grounding a Claim."""

    __tablename__ = "claim_evidence"
    __table_args__ = (
        CheckConstraint("char_start >= 0", name="ck_claim_evidence_char_start"),
        CheckConstraint("char_end > char_start", name="ck_claim_evidence_char_end"),
        CheckConstraint(
            "grounding_method IN ('exact_span', 'normalized_span', 'manual')",
            name="ck_claim_evidence_grounding_method",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_claim_evidence_confidence",
        ),
        UniqueConstraint(
            "claim_id",
            "knowledge_unit_id",
            "char_start",
            "char_end",
            name="uq_claim_evidence_span",
        ),
        Index("ix_claim_evidence_user_claim", "user_id", "claim_id"),
        Index("ix_claim_evidence_user_unit", "user_id", "knowledge_unit_id"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claim_id = Column(
        Integer,
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_unit_id = Column(
        Integer,
        ForeignKey("knowledge_units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    excerpt = Column(Text, nullable=False)
    char_start = Column(Integer, nullable=False)
    char_end = Column(Integer, nullable=False)
    locator = Column(JSON, nullable=False, default=dict, server_default="{}")
    grounding_method = Column(String(30), nullable=False, default="manual", server_default="manual")
    confidence = Column(Float, nullable=False, default=1.0, server_default="1.0")
    created_at = Column(DateTime, nullable=False, server_default=func.now())

    claim = relationship("Claim", back_populates="evidence")
    knowledge_unit = relationship("KnowledgeUnit", back_populates="evidence")


class ClaimRelation(Base):
    """Reviewable, user-owned relation between two grounded Claims."""

    __tablename__ = "claim_relations"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "from_claim_id",
            "to_claim_id",
            "relation_type",
            name="uq_claim_relations_identity",
        ),
        CheckConstraint("from_claim_id <> to_claim_id", name="ck_claim_relations_no_self_loop"),
        CheckConstraint(
            "relation_type IN ('supports', 'contradicts', 'refines', 'exemplifies', 'analogous_to')",
            name="ck_claim_relations_type",
        ),
        CheckConstraint(
            "derivation_type IN ('explicit', 'inferred', 'manual', 'migration')",
            name="ck_claim_relations_derivation_type",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'confirmed', 'rejected')",
            name="ck_claim_relations_review_status",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_claim_relations_confidence",
        ),
        Index(
            "ix_claim_relations_user_from_review",
            "user_id",
            "from_claim_id",
            "review_status",
        ),
        Index(
            "ix_claim_relations_user_to_review",
            "user_id",
            "to_claim_id",
            "review_status",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    from_claim_id = Column(
        Integer, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    to_claim_id = Column(
        Integer, ForeignKey("claims.id", ondelete="CASCADE"), nullable=False, index=True
    )
    relation_type = Column(String(30), nullable=False)
    confidence = Column(Float, nullable=False, default=1.0, server_default="1.0")
    derivation_type = Column(String(20), nullable=False, default="manual", server_default="manual")
    review_status = Column(String(20), nullable=False, default="pending", server_default="pending")
    rationale = Column(String(500), nullable=False, default="", server_default="")
    # Minimal provenance only: evidence ids / evaluator inputs, never hidden reasoning or source text.
    evidence_provenance = Column(JSON, nullable=False, default=dict, server_default="{}")
    model_version = Column(String(120), nullable=True)
    evaluator_version = Column(String(120), nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
    reviewed_at = Column(DateTime, nullable=True)


class EntityResolutionCandidate(Base):
    """Reviewable mapping from one extracted mention to a user-owned Concept."""

    __tablename__ = "entity_resolution_candidates"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "identity_hash",
            name="uq_entity_resolution_candidates_user_identity",
        ),
        CheckConstraint(
            "relation_type IN ('about', 'uses', 'applies_to', 'exemplifies')",
            name="ck_entity_resolution_candidates_relation_type",
        ),
        CheckConstraint(
            "decision IN ('pending', 'accepted', 'rejected', 'create_new')",
            name="ck_entity_resolution_candidates_decision",
        ),
        CheckConstraint(
            "decided_by IS NULL OR decided_by IN ('rule', 'model', 'user')",
            name="ck_entity_resolution_candidates_decided_by",
        ),
        CheckConstraint(
            "exact_score >= 0.0 AND exact_score <= 1.0",
            name="ck_entity_resolution_candidates_exact_score",
        ),
        CheckConstraint(
            "alias_score >= 0.0 AND alias_score <= 1.0",
            name="ck_entity_resolution_candidates_alias_score",
        ),
        CheckConstraint(
            "lexical_score >= 0.0 AND lexical_score <= 1.0",
            name="ck_entity_resolution_candidates_lexical_score",
        ),
        CheckConstraint(
            "vector_score >= 0.0 AND vector_score <= 1.0",
            name="ck_entity_resolution_candidates_vector_score",
        ),
        CheckConstraint(
            "context_score >= 0.0 AND context_score <= 1.0",
            name="ck_entity_resolution_candidates_context_score",
        ),
        CheckConstraint(
            "combined_score >= 0.0 AND combined_score <= 1.0",
            name="ck_entity_resolution_candidates_combined_score",
        ),
        Index(
            "ix_entity_resolution_candidates_user_decision",
            "user_id",
            "decision",
            "created_at",
        ),
        Index(
            "ix_entity_resolution_candidates_user_claim",
            "user_id",
            "claim_id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    extraction_run_id = Column(
        Integer,
        ForeignKey("knowledge_extraction_runs.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    knowledge_unit_id = Column(
        Integer,
        ForeignKey("knowledge_units.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claim_id = Column(
        Integer,
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    mention_text = Column(String(120), nullable=False)
    mention_normalized = Column(String(120), nullable=False)
    mention_context = Column(String(500), nullable=False, default="", server_default="")
    relation_type = Column(String(30), nullable=False, default="about", server_default="about")
    candidate_concept_id = Column(
        Integer,
        ForeignKey("concepts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    exact_score = Column(Float, nullable=False, default=0.0, server_default="0.0")
    alias_score = Column(Float, nullable=False, default=0.0, server_default="0.0")
    lexical_score = Column(Float, nullable=False, default=0.0, server_default="0.0")
    vector_score = Column(Float, nullable=False, default=0.0, server_default="0.0")
    context_score = Column(Float, nullable=False, default=0.0, server_default="0.0")
    combined_score = Column(Float, nullable=False, default=0.0, server_default="0.0")
    decision = Column(String(20), nullable=False, default="pending", server_default="pending")
    resolved_concept_id = Column(
        Integer,
        ForeignKey("concepts.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    decided_by = Column(String(20), nullable=True)
    decided_at = Column(DateTime, nullable=True)
    identity_hash = Column(String(64), nullable=False)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class ClaimConceptLink(Base):
    """User-scoped, reviewable semantic anchor from a Claim to a Concept."""

    __tablename__ = "claim_concept_links"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "claim_id",
            "concept_id",
            "relation_type",
            name="uq_claim_concept_links_identity",
        ),
        CheckConstraint(
            "relation_type IN ('about', 'uses', 'applies_to', 'exemplifies')",
            name="ck_claim_concept_links_relation_type",
        ),
        CheckConstraint(
            "derivation_type IN ('canonical_exact', 'alias_exact', 'semantic', 'user', 'manual')",
            name="ck_claim_concept_links_derivation_type",
        ),
        CheckConstraint(
            "review_status IN ('pending', 'confirmed', 'rejected')",
            name="ck_claim_concept_links_review_status",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_claim_concept_links_confidence",
        ),
        Index(
            "ix_claim_concept_links_user_claim_review",
            "user_id",
            "claim_id",
            "review_status",
        ),
        Index(
            "ix_claim_concept_links_user_concept_review",
            "user_id",
            "concept_id",
            "review_status",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    claim_id = Column(
        Integer,
        ForeignKey("claims.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    concept_id = Column(
        Integer,
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    relation_type = Column(String(30), nullable=False, default="about", server_default="about")
    mention_text = Column(String(120), nullable=False)
    confidence = Column(Float, nullable=False, default=1.0, server_default="1.0")
    derivation_type = Column(String(30), nullable=False)
    review_status = Column(String(20), nullable=False, default="pending", server_default="pending")
    resolution_candidate_id = Column(
        Integer,
        ForeignKey("entity_resolution_candidates.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class KnowledgeEmbeddingProjection(Base):
    """SQL lifecycle metadata for a disposable knowledge vector."""

    __tablename__ = "knowledge_embedding_projections"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "object_type",
            "object_id",
            "embedding_model",
            name="uq_knowledge_embedding_projections_identity",
        ),
        UniqueConstraint(
            "vector_key",
            "collection",
            name="uq_knowledge_embedding_projections_vector",
        ),
        CheckConstraint(
            "object_type IN ('claim', 'concept', 'note_unit', 'material_unit')",
            name="ck_knowledge_embedding_projections_object_type",
        ),
        CheckConstraint(
            "status IN ('pending', 'ready', 'degraded', 'failed', 'deleting', 'deleted')",
            name="ck_knowledge_embedding_projections_status",
        ),
        CheckConstraint(
            "attempt_count >= 0",
            name="ck_knowledge_embedding_projections_attempt_count",
        ),
        Index(
            "ix_knowledge_embedding_projections_user_status",
            "user_id",
            "status",
            "updated_at",
        ),
        Index(
            "ix_knowledge_embedding_projections_object",
            "user_id",
            "object_type",
            "object_id",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    object_type = Column(String(30), nullable=False)
    object_id = Column(Integer, nullable=False)
    content_hash = Column(String(64), nullable=False)
    configuration_fingerprint = Column(String(64), nullable=False)
    embedding_model = Column(String(160), nullable=False)
    collection = Column(String(160), nullable=False)
    vector_key = Column(String(200), nullable=False)
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    attempt_count = Column(Integer, nullable=False, default=0, server_default="0")
    last_error = Column(String(500), nullable=True)
    indexed_at = Column(DateTime, nullable=True)
    deleted_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())


class KnowledgeProjectionOutbox(Base):
    """Durable command log for knowledge-only disposable projections."""

    __tablename__ = "knowledge_projection_outbox"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "idempotency_key",
            name="uq_knowledge_projection_outbox_user_key",
        ),
        CheckConstraint(
            "aggregate_type IN ('source', 'revision', 'unit', 'claim', 'concept', 'relation', 'user')",
            name="ck_knowledge_projection_outbox_aggregate_type",
        ),
        CheckConstraint(
            "operation IN ('upsert', 'delete', 'rebuild_user')",
            name="ck_knowledge_projection_outbox_operation",
        ),
        CheckConstraint(
            "projection_target IN ('chroma_knowledge', 'sparse_knowledge', 'neo4j_graph')",
            name="ck_knowledge_projection_outbox_target",
        ),
        CheckConstraint(
            "status IN ('pending', 'processing', 'processed', 'failed')",
            name="ck_knowledge_projection_outbox_status",
        ),
        CheckConstraint("attempts >= 0", name="ck_knowledge_projection_outbox_attempts"),
        CheckConstraint("payload_version >= 1", name="ck_knowledge_projection_outbox_payload_version"),
        Index(
            "ix_knowledge_projection_outbox_available",
            "status",
            "available_at",
            "created_at",
        ),
        Index(
            "ix_knowledge_projection_outbox_user_status",
            "user_id",
            "status",
            "created_at",
        ),
        Index("ix_knowledge_projection_outbox_lease", "status", "locked_at"),
        Index("ix_knowledge_projection_outbox_dead_letter", "dead_lettered_at"),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    aggregate_type = Column(String(30), nullable=False)
    aggregate_id = Column(Integer, nullable=False)
    aggregate_version = Column(Integer, nullable=False, default=1, server_default="1")
    operation = Column(String(20), nullable=False)
    projection_target = Column(
        String(40),
        nullable=False,
        default="chroma_knowledge",
        server_default="chroma_knowledge",
    )
    idempotency_key = Column(String(200), nullable=False)
    payload_version = Column(Integer, nullable=False, default=1, server_default="1")
    payload = Column(JSON, nullable=False, default=dict, server_default="{}")
    status = Column(String(20), nullable=False, default="pending", server_default="pending")
    attempts = Column(Integer, nullable=False, default=0, server_default="0")
    available_at = Column(DateTime, nullable=False, server_default=func.now())
    locked_at = Column(DateTime, nullable=True)
    lease_owner = Column(String(120), nullable=True)
    processed_at = Column(DateTime, nullable=True)
    last_error = Column(String(500), nullable=True)
    dead_lettered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, nullable=False, server_default=func.now())
    updated_at = Column(DateTime, nullable=False, server_default=func.now(), onupdate=func.now())
