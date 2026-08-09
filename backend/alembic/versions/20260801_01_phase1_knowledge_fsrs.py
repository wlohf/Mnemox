"""Add the Phase 1 knowledge-layer and FSRS schema.

Revision ID: 20260801_01
Revises: 20260801_00
Create Date: 2026-08-01

The preceding revision is a frozen v1.3 schema snapshot.  Keep this revision
additive and explicit so both a new PostgreSQL database and a stamped v1.3
database receive exactly the same Phase 1 schema.
"""
from __future__ import annotations

from alembic import op
import sqlalchemy as sa


revision = "20260801_01"
down_revision = "20260801_00"
branch_labels = None
depends_on = None


def _create_wrong_question_concept_foreign_key() -> None:
    """Add the FK using SQLite batch mode when a legacy table already exists."""
    bind = op.get_bind()
    if bind.dialect.name == "sqlite":
        with op.batch_alter_table("wrong_questions", recreate="always") as batch_op:
            batch_op.create_foreign_key(
                "fk_wrong_questions_concept_id",
                "concepts",
                ["concept_id"],
                ["id"],
            )
        return

    op.create_foreign_key(
        "fk_wrong_questions_concept_id",
        "wrong_questions",
        "concepts",
        ["concept_id"],
        ["id"],
    )


def upgrade() -> None:
    """Upgrade the frozen v1.3 baseline to the Phase 1 schema."""
    # v1.3's standalone initializer did not consistently import this model.
    # Keep the repair explicit so a stamped legacy database receives the table.
    op.create_table(
        "prompt_templates",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("mode_key", sa.String(length=40), nullable=False),
        sa.Column("content", sa.Text(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=True),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_prompt_templates_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_prompt_templates"),
        if_not_exists=True,
    )
    op.create_index(
        "ix_prompt_templates_user_id",
        "prompt_templates",
        ["user_id"],
        unique=False,
        if_not_exists=True,
    )

    op.create_table(
        "concepts",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("name", sa.String(length=120), nullable=False),
        sa.Column("name_normalized", sa.String(length=120), nullable=False),
        sa.Column("description", sa.Text(), nullable=True),
        sa.Column("mastery", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.Column("updated_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_concepts_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_concepts"),
        sa.UniqueConstraint("user_id", "name_normalized", name="uq_concepts_user_name"),
    )
    op.create_index("ix_concepts_user_id", "concepts", ["user_id"], unique=False)
    op.create_index("ix_concepts_name_normalized", "concepts", ["name_normalized"], unique=False)

    op.create_table(
        "concept_edges",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("from_concept_id", sa.Integer(), nullable=False),
        sa.Column("to_concept_id", sa.Integer(), nullable=False),
        sa.Column("edge_type", sa.String(length=30), nullable=False),
        sa.Column("confidence", sa.Float(), nullable=False),
        sa.Column("source", sa.String(length=40), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_concept_edges_user_id"),
        sa.ForeignKeyConstraint(
            ["from_concept_id"],
            ["concepts.id"],
            name="fk_concept_edges_from_concept_id",
            ondelete="CASCADE",
        ),
        sa.ForeignKeyConstraint(
            ["to_concept_id"],
            ["concepts.id"],
            name="fk_concept_edges_to_concept_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_concept_edges"),
        sa.UniqueConstraint(
            "user_id",
            "from_concept_id",
            "to_concept_id",
            "edge_type",
            name="uq_concept_edges_pair",
        ),
    )
    op.create_index("ix_concept_edges_user_id", "concept_edges", ["user_id"], unique=False)
    op.create_index(
        "ix_concept_edges_from_concept_id",
        "concept_edges",
        ["from_concept_id"],
        unique=False,
    )
    op.create_index(
        "ix_concept_edges_to_concept_id",
        "concept_edges",
        ["to_concept_id"],
        unique=False,
    )

    op.create_table(
        "concept_links",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("concept_id", sa.Integer(), nullable=False),
        sa.Column("target_type", sa.String(length=30), nullable=False),
        sa.Column("target_id", sa.Integer(), nullable=False),
        sa.Column("link_type", sa.String(length=30), nullable=False),
        sa.Column("created_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_concept_links_user_id"),
        sa.ForeignKeyConstraint(
            ["concept_id"],
            ["concepts.id"],
            name="fk_concept_links_concept_id",
            ondelete="CASCADE",
        ),
        sa.PrimaryKeyConstraint("id", name="pk_concept_links"),
        sa.UniqueConstraint(
            "user_id",
            "concept_id",
            "target_type",
            "target_id",
            name="uq_concept_links_target",
        ),
    )
    op.create_index("ix_concept_links_user_id", "concept_links", ["user_id"], unique=False)
    op.create_index("ix_concept_links_concept_id", "concept_links", ["concept_id"], unique=False)
    op.create_index("ix_concept_links_target_id", "concept_links", ["target_id"], unique=False)

    op.create_table(
        "note_quote_usages",
        sa.Column("id", sa.Integer(), autoincrement=True, nullable=False),
        sa.Column("user_id", sa.Integer(), nullable=False),
        sa.Column("note_id", sa.Integer(), nullable=True),
        sa.Column("excerpt_hash", sa.String(length=64), nullable=False),
        sa.Column("excerpt_preview", sa.String(length=200), nullable=True),
        sa.Column("channel", sa.String(length=40), nullable=False),
        sa.Column("nudge_id", sa.String(length=40), nullable=True),
        sa.Column("feedback_outcome", sa.String(length=40), nullable=True),
        sa.Column("quoted_at", sa.DateTime(), server_default=sa.func.now(), nullable=False),
        sa.ForeignKeyConstraint(["user_id"], ["users.id"], name="fk_note_quote_usages_user_id"),
        sa.PrimaryKeyConstraint("id", name="pk_note_quote_usages"),
    )
    op.create_index("ix_note_quote_usages_user_id", "note_quote_usages", ["user_id"], unique=False)
    op.create_index("ix_note_quote_usages_note_id", "note_quote_usages", ["note_id"], unique=False)
    op.create_index(
        "ix_note_quote_usages_excerpt_hash",
        "note_quote_usages",
        ["excerpt_hash"],
        unique=False,
    )
    op.create_index("ix_note_quote_usages_nudge_id", "note_quote_usages", ["nudge_id"], unique=False)
    op.create_index("ix_note_quote_usages_quoted_at", "note_quote_usages", ["quoted_at"], unique=False)

    for table_name in ("anki_cards", "review_schedule"):
        op.add_column(table_name, sa.Column("stability", sa.Float(), nullable=True))
        op.add_column(table_name, sa.Column("difficulty", sa.Float(), nullable=True))
        op.add_column(table_name, sa.Column("fsrs_state", sa.Integer(), nullable=True))
        op.add_column(table_name, sa.Column("fsrs_step", sa.Integer(), nullable=True))
        op.add_column(table_name, sa.Column("last_review_at", sa.DateTime(), nullable=True))

    op.add_column("wrong_questions", sa.Column("concept_id", sa.Integer(), nullable=True))
    _create_wrong_question_concept_foreign_key()
    op.create_index("ix_wrong_questions_concept_id", "wrong_questions", ["concept_id"], unique=False)

    op.add_column("notes", sa.Column("source_path", sa.String(length=500), nullable=True))
    op.create_index("ix_notes_source_path", "notes", ["source_path"], unique=False)


def downgrade() -> None:
    """Avoid a data-losing automatic downgrade of the knowledge layer."""
    raise NotImplementedError("The Phase 1 knowledge migration is intentionally irreversible.")
