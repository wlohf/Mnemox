"""Align verified v1.3 databases with the current model metadata.

Revision ID: 20260804_03
Revises: 20260804_02

Some pre-Alembic SQLite databases contain an invalid foreign key from
``ai_routing_settings.provider_name`` to a non-unique provider name, a shorter
encrypted API key column, and lightweight-only memory indexes.  Apply only the
differences actually present so clean PostgreSQL and fresh databases are no-op.
"""
from __future__ import annotations

from alembic import context, op
import sqlalchemy as sa

revision = "20260804_03"
down_revision = "20260804_02"
branch_labels = None
depends_on = None


def _column(table_name: str, column_name: str) -> dict | None:
    inspector = sa.inspect(op.get_bind())
    return next(
        (item for item in inspector.get_columns(table_name) if item["name"] == column_name),
        None,
    )


def _provider_name_foreign_keys() -> list[dict]:
    inspector = sa.inspect(op.get_bind())
    return [
        item
        for item in inspector.get_foreign_keys("ai_routing_settings")
        if item.get("constrained_columns") == ["provider_name"]
        and item.get("referred_table") == "ai_provider_settings"
    ]


def _align_sqlite() -> None:
    api_key = _column("ai_provider_settings", "api_key")
    if api_key is not None and getattr(api_key["type"], "length", None) != 2000:
        with op.batch_alter_table("ai_provider_settings", recreate="always") as batch_op:
            batch_op.alter_column(
                "api_key",
                existing_type=api_key["type"],
                type_=sa.String(length=2000),
                existing_nullable=api_key.get("nullable", True),
            )

    if _provider_name_foreign_keys():
        naming_convention = {
            "fk": "fk_%(table_name)s_%(column_0_name)s_%(referred_table_name)s"
        }
        with op.batch_alter_table(
            "ai_routing_settings",
            recreate="always",
            naming_convention=naming_convention,
        ) as batch_op:
            batch_op.drop_constraint(
                "fk_ai_routing_settings_provider_name_ai_provider_settings",
                type_="foreignkey",
            )


def _align_postgresql() -> None:
    api_key = _column("ai_provider_settings", "api_key")
    if api_key is not None and getattr(api_key["type"], "length", None) != 2000:
        op.alter_column(
            "ai_provider_settings",
            "api_key",
            existing_type=api_key["type"],
            type_=sa.String(length=2000),
            existing_nullable=api_key.get("nullable", True),
        )

    for foreign_key in _provider_name_foreign_keys():
        if foreign_key.get("name"):
            op.drop_constraint(
                foreign_key["name"],
                "ai_routing_settings",
                type_="foreignkey",
            )


def _align_user_memory_indexes() -> None:
    indexes = {
        item["name"]
        for item in sa.inspect(op.get_bind()).get_indexes("user_memories")
    }
    for legacy_name in ("ix_user_memories_user_review_status", "ix_user_memories_user_source"):
        if legacy_name in indexes:
            op.drop_index(legacy_name, table_name="user_memories")
    if "ix_user_memories_review_status" not in indexes:
        op.create_index(
            "ix_user_memories_review_status",
            "user_memories",
            ["review_status"],
            unique=False,
        )


def upgrade() -> None:
    if context.is_offline_mode():
        # Offline output is PostgreSQL-only in this project. IF EXISTS keeps
        # this compatible with both a clean frozen baseline and an older
        # hand-managed v1.3 deployment.
        op.execute(
            "ALTER TABLE ai_provider_settings ALTER COLUMN api_key TYPE VARCHAR(2000)"
        )
        op.execute(
            "ALTER TABLE ai_routing_settings DROP CONSTRAINT IF EXISTS "
            "ai_routing_settings_provider_name_fkey"
        )
        op.execute("DROP INDEX IF EXISTS ix_user_memories_user_review_status")
        op.execute("DROP INDEX IF EXISTS ix_user_memories_user_source")
        op.execute(
            "CREATE INDEX IF NOT EXISTS ix_user_memories_review_status "
            "ON user_memories (review_status)"
        )
        return
    dialect = op.get_bind().dialect.name
    if dialect == "sqlite":
        _align_sqlite()
    else:
        _align_postgresql()
    _align_user_memory_indexes()


def downgrade() -> None:
    raise NotImplementedError("Legacy schema alignment is intentionally irreversible.")
