"""Add learner evidence and derived concept state.

Revision ID: 20260804_01
Revises: 20260801_01
Create Date: 2026-08-04
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260804_01"
down_revision = "20260801_01"
branch_labels = None
depends_on = None


def upgrade() -> None:
    """Create the replayable learner-model boundary and seed legacy mastery."""
    op.create_table(
        "learner_evidence",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.Integer(), nullable=False),
        sa.Column("evidence_type", sa.String(length=40), nullable=False),
        sa.Column("evidence_category", sa.String(length=20), nullable=False),
        sa.Column("dimension", sa.String(length=40), nullable=True),
        sa.Column("score", sa.Float(), nullable=False),
        sa.Column("reliability", sa.Float(), nullable=False),
        sa.Column("source_event_id", sa.Integer(), nullable=True),
        sa.Column("source_type", sa.String(length=40), nullable=False),
        sa.Column("source_id", sa.String(length=160), nullable=True),
        sa.Column("observed_at", sa.DateTime(), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("payload_version", sa.Integer(), nullable=False),
        sa.Column("payload", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint("score >= 0.0 AND score <= 1.0", name="ck_learner_evidence_score"),
        sa.CheckConstraint(
            "evidence_category IN ('direct', 'indirect', 'manual', 'legacy')",
            name="ck_learner_evidence_category",
        ),
        sa.CheckConstraint(
            "evidence_type IN ('answer', 'recall', 'explanation', 'application', 'hint_count', 'review_result', 'study_duration', 'study_frequency', 'repeated_question', 'interruption', 'recovery', 'legacy_mastery', 'manual_override')",
            name="ck_learner_evidence_type",
        ),
        sa.CheckConstraint(
            "payload_version >= 1",
            name="ck_learner_evidence_payload_version",
        ),
        sa.CheckConstraint(
            "reliability >= 0.0 AND reliability <= 1.0",
            name="ck_learner_evidence_reliability",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["concepts.id"],
            name="fk_learner_evidence_concept_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            ["learning_events.id"],
            name="fk_learner_evidence_source_event_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_learner_evidence_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_learner_evidence"),
        sa.UniqueConstraint(
            "user_id",
            "concept_id",
            "evidence_type",
            "source_event_id",
            name="uq_learner_evidence_event_type",
        ),
    )
    op.create_index("ix_learner_evidence_user_id", "learner_evidence", ["user_id"], unique=False)
    op.create_index("ix_learner_evidence_concept_id", "learner_evidence", ["concept_id"], unique=False)
    op.create_index("ix_learner_evidence_source_event_id", "learner_evidence", ["source_event_id"], unique=False)
    op.create_index("ix_learner_evidence_observed_at", "learner_evidence", ["observed_at"], unique=False)
    op.create_index(
        "ix_learner_evidence_user_concept_observed",
        "learner_evidence",
        ["user_id", "concept_id", "observed_at"],
        unique=False,
    )

    op.create_table(
        "user_concept_state",
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.Integer(), nullable=False),
        sa.Column("mastery_estimate", sa.Float(), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("forgetting_risk", sa.Float(), nullable=False),
        sa.Column("mastery_dimensions", sa.JSON(), nullable=False),
        sa.Column("common_error_type", sa.String(length=80), nullable=True),
        sa.Column("last_evidence_at", sa.DateTime(), nullable=True),
        sa.Column("last_reviewed_at", sa.DateTime(), nullable=True),
        sa.Column("next_review_at", sa.DateTime(), nullable=True),
        sa.Column("manual_override", sa.JSON(), nullable=True),
        sa.Column("source_event_id", sa.Integer(), nullable=True),
        sa.Column("reliability", sa.Float(), nullable=False),
        sa.Column("model_version", sa.String(length=50), nullable=False),
        sa.Column("explanation_summary", sa.JSON(), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.CheckConstraint(
            "mastery_estimate >= 0.0 AND mastery_estimate <= 100.0",
            name="ck_user_concept_state_mastery",
        ),
        sa.CheckConstraint(
            "confidence >= 0.0 AND confidence <= 1.0",
            name="ck_user_concept_state_confidence",
        ),
        sa.CheckConstraint(
            "forgetting_risk >= 0.0 AND forgetting_risk <= 1.0",
            name="ck_user_concept_state_forgetting_risk",
        ),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["concepts.id"],
            name="fk_user_concept_state_concept_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["source_event_id"],
            ["learning_events.id"],
            name="fk_user_concept_state_source_event_id",
            ondelete="SET NULL",
        ),
        sa.ForeignKeyConstraint(
            ["user_id"],
            ["users.id"],
            name="fk_user_concept_state_user_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("user_id", "concept_id", name="pk_user_concept_state"),
    )
    op.create_index("ix_user_concept_state_source_event_id", "user_concept_state", ["source_event_id"], unique=False)
    op.create_index("ix_user_concept_state_updated_at", "user_concept_state", ["updated_at"], unique=False)

    # ``Concept.mastery`` used a 0-100 scale. Preserve every value as a
    # low-reliability legacy input and initialize the derived projection. The
    # old column remains untouched for one compatibility release.
    op.execute(
        sa.text(
            """
            INSERT INTO learner_evidence (
                user_id, concept_id, evidence_type, evidence_category, dimension,
                score, reliability, source_event_id, source_type, source_id,
                observed_at, model_version, payload_version, payload, created_at
            )
            SELECT
                user_id, id, 'legacy_mastery', 'legacy', 'overall',
                CASE
                    WHEN mastery < 0 THEN 0.0
                    WHEN mastery > 100 THEN 1.0
                    ELSE mastery / 100.0
                END,
                0.35, NULL, 'legacy', name_normalized,
                COALESCE(updated_at, created_at, CURRENT_TIMESTAMP),
                'legacy-concept-mastery-v1', 1,
                '{"field":"concepts.mastery","scale":"0-100"}',
                CURRENT_TIMESTAMP
            FROM concepts
            """
        )
    )
    op.execute(
        sa.text(
            """
            INSERT INTO user_concept_state (
                user_id, concept_id, mastery_estimate, confidence, forgetting_risk,
                mastery_dimensions, common_error_type, last_evidence_at,
                last_reviewed_at, next_review_at, manual_override, source_event_id,
                reliability, model_version, explanation_summary, created_at, updated_at
            )
            SELECT
                user_id, id,
                CASE
                    WHEN mastery < 0 THEN 0.0
                    WHEN mastery > 100 THEN 100.0
                    ELSE mastery
                END,
                0.35, 0.5, '{}', NULL,
                COALESCE(updated_at, created_at, CURRENT_TIMESTAMP),
                NULL, NULL, NULL, NULL, 0.35,
                'legacy-concept-mastery-v1',
                '{"basis":"legacy Concept.mastery migration","recomputable":"true"}',
                CURRENT_TIMESTAMP, CURRENT_TIMESTAMP
            FROM concepts
            """
        )
    )


def downgrade() -> None:
    """Avoid silently deleting replayable learner evidence."""
    raise NotImplementedError("The learner-model boundary migration is intentionally irreversible.")
