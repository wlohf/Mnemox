"""Learner-model evidence and derived concept state.

Evidence rows are immutable, replayable inputs. ``UserConceptState`` is a
user-scoped projection that may be deleted and rebuilt from those inputs.
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
)
from sqlalchemy.sql import func, text

from app.database import Base


class LearnerEvidence(Base):
    """One normalized, replayable signal about a user's concept knowledge."""

    __tablename__ = "learner_evidence"
    __table_args__ = (
        UniqueConstraint(
            "user_id",
            "concept_id",
            "evidence_type",
            "source_event_id",
            name="uq_learner_evidence_event_type",
        ),
        CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_learner_evidence_score"),
        CheckConstraint(
            "evidence_category IN ('direct', 'indirect', 'manual', 'legacy')",
            name="ck_learner_evidence_category",
        ),
        CheckConstraint(
            "evidence_type IN ('answer', 'recall', 'explanation', 'application', 'hint_count', 'review_result', 'study_duration', 'study_frequency', 'repeated_question', 'interruption', 'recovery', 'legacy_mastery', 'manual_override')",
            name="ck_learner_evidence_type",
        ),
        CheckConstraint(
            "payload_version >= 1",
            name="ck_learner_evidence_payload_version",
        ),
        CheckConstraint(
            "reliability >= 0.0 AND reliability <= 1.0",
            name="ck_learner_evidence_reliability",
        ),
        Index(
            "ix_learner_evidence_user_concept_observed",
            "user_id",
            "concept_id",
            "observed_at",
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    concept_id = Column(
        Integer,
        ForeignKey("concepts.id", ondelete="CASCADE"),
        nullable=False,
        index=True,
    )
    evidence_type = Column(String(40), nullable=False)
    evidence_category = Column(String(20), nullable=False, comment="direct | indirect | manual | legacy")
    dimension = Column(String(40), nullable=True)
    score = Column(Float, nullable=False, comment="Normalized evidence score in [0, 1]")
    reliability = Column(Float, nullable=False, default=1.0)
    source_event_id = Column(
        Integer,
        ForeignKey("learning_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    source_type = Column(String(40), nullable=False)
    source_id = Column(String(160), nullable=True)
    observed_at = Column(DateTime, nullable=False, index=True)
    model_version = Column(String(50), nullable=False)
    payload_version = Column(Integer, nullable=False, default=1)
    payload = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)


class UserConceptState(Base):
    """Current derived learner state for one user and one concept."""

    __tablename__ = "user_concept_state"
    __table_args__ = (
        CheckConstraint(
            "mastery_estimate >= 0.0 AND mastery_estimate <= 100.0",
            name="ck_user_concept_state_mastery",
        ),
        CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_user_concept_state_confidence",
        ),
        CheckConstraint(
            "forgetting_risk >= 0.0 AND forgetting_risk <= 1.0",
            name="ck_user_concept_state_forgetting_risk",
        ),
    )

    user_id = Column(
        Integer,
        ForeignKey("users.id", ondelete="CASCADE"),
        primary_key=True,
    )
    concept_id = Column(
        Integer,
        ForeignKey("concepts.id", ondelete="CASCADE"),
        primary_key=True,
    )
    mastery_estimate = Column(Float, nullable=False, default=0.0)
    confidence = Column(Float, nullable=False, default=0.0)
    forgetting_risk = Column(Float, nullable=False, default=1.0)
    mastery_dimensions = Column(JSON, nullable=False, default=dict)
    common_error_type = Column(String(80), nullable=True)
    last_evidence_at = Column(DateTime, nullable=True)
    last_reviewed_at = Column(DateTime, nullable=True)
    next_review_at = Column(DateTime, nullable=True)
    manual_override = Column(JSON, nullable=True)
    source_event_id = Column(
        Integer,
        ForeignKey("learning_events.id", ondelete="SET NULL"),
        nullable=True,
        index=True,
    )
    reliability = Column(Float, nullable=False, default=0.0)
    model_version = Column(String(50), nullable=False)
    explanation_summary = Column(JSON, nullable=False, default=dict)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(
        DateTime,
        server_default=func.now(),
        onupdate=func.now(),
        nullable=False,
        index=True,
    )


class ProjectionOutbox(Base):
    """Durable projection command emitted with a learning event.

    The natural key makes enqueueing safe to repeat while the lifecycle
    columns let workers recover rows that were claimed before a crash.
    """

    __tablename__ = "projection_outbox"
    __table_args__ = (
        UniqueConstraint("user_id", "idempotency_key", name="uq_projection_outbox_user_key"),
        CheckConstraint("status IN ('pending', 'processing', 'processed', 'failed')", name="ck_projection_outbox_status"),
        CheckConstraint("attempts >= 0", name="ck_projection_outbox_attempts"),
        CheckConstraint("payload_version >= 1", name="ck_projection_outbox_payload_version"),
        Index("ix_projection_outbox_pending", "status", "available_at", "id"),
        Index("ix_projection_outbox_user_concept_time", "user_id", "concept_id", "occurred_at"),
        Index("ix_projection_outbox_dead_lettered_at", "dead_lettered_at"),
        Index(
            "ix_projection_outbox_operations_active",
            "status",
            "available_at",
            "locked_at",
            "attempts",
            sqlite_where=text("status IN ('pending', 'processing', 'failed')"),
            postgresql_where=text("status IN ('pending', 'processing', 'failed')"),
        ),
    )

    id = Column(Integer, primary_key=True, autoincrement=True)
    user_id = Column(Integer, ForeignKey("users.id", ondelete="CASCADE"), nullable=False, index=True)
    concept_id = Column(Integer, ForeignKey("concepts.id", ondelete="CASCADE"), nullable=True, index=True)
    source_event_id = Column(Integer, ForeignKey("learning_events.id", ondelete="CASCADE"), nullable=False, index=True)
    idempotency_key = Column(String(200), nullable=False)
    projection_type = Column(String(60), nullable=False, default="learner_state")
    model_version = Column(String(50), nullable=False, default="explainable-rules-v1")
    payload_version = Column(Integer, nullable=False, default=1)
    payload = Column(JSON, nullable=False, default=dict)
    occurred_at = Column(DateTime, nullable=False, server_default=func.now(), index=True)
    status = Column(String(20), nullable=False, default="pending", index=True)
    attempts = Column(Integer, nullable=False, default=0)
    available_at = Column(DateTime, server_default=func.now(), nullable=False, index=True)
    locked_at = Column(DateTime, nullable=True)
    processed_at = Column(DateTime, nullable=True)
    last_error = Column(Text, nullable=True)
    dead_lettered_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class ProjectionOutboxWorkerHeartbeat(Base):
    """Durable worker liveness timestamps for cross-instance outbox operations."""

    __tablename__ = "projection_outbox_worker_heartbeats"

    worker_id = Column(String(120), primary_key=True)
    started_at = Column(DateTime, nullable=False)
    last_heartbeat_at = Column(DateTime, nullable=False, index=True)
    last_poll_at = Column(DateTime, nullable=True)
    last_success_at = Column(DateTime, nullable=True)
    last_error_at = Column(DateTime, nullable=True)
    last_projection_failure_at = Column(DateTime, nullable=True)
    stopped_at = Column(DateTime, nullable=True)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)


class ProjectionOutboxRetryPolicy(Base):
    """One versioned retry policy shared by every DLQ-aware consumer."""

    __tablename__ = "projection_outbox_retry_policy"
    __table_args__ = (
        CheckConstraint("id = 1", name="ck_projection_outbox_retry_policy_singleton"),
        CheckConstraint("max_attempts >= 1", name="ck_projection_outbox_retry_policy_attempts"),
        CheckConstraint("policy_version >= 1", name="ck_projection_outbox_retry_policy_version"),
    )

    id = Column(Integer, primary_key=True)
    max_attempts = Column(Integer, nullable=False)
    policy_version = Column(Integer, nullable=False)
    created_at = Column(DateTime, server_default=func.now(), nullable=False)
    updated_at = Column(DateTime, server_default=func.now(), onupdate=func.now(), nullable=False)
