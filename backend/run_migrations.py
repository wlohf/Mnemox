"""Run the versioned database migration entrypoint.

SQLite remains a local-development convenience backed by ``init_db``. Every
non-SQLite environment must use Alembic revisions; the legacy SQL files are
kept only as historical references and are no longer a second migration path.
"""
from __future__ import annotations

import asyncio
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from alembic import command
from alembic.config import Config
from sqlalchemy import inspect, text
from sqlalchemy.ext.asyncio import AsyncConnection

from app.config import settings
from app.database import engine, init_db


V13_BASELINE_REVISION = "20260801_00"
# Serializes the complete PostgreSQL migration decision path across application
# replicas. It is a stable, application-specific signed BIGINT advisory key.
POSTGRES_MIGRATION_LOCK_KEY = 0x4D4E454D4F58

# This is deliberately a frozen fingerprint of the v1.3 production schema.
# A database without alembic_version is stamped only when it has every table
# from that release and the selected columns that distinguish it from older,
# partial hand-maintained deployments.
V13_REQUIRED_TABLES = frozenset(
    {
        "agent_execution_logs",
        "agent_jobs",
        "ai_provider_settings",
        "ai_routing_settings",
        "ai_search_settings",
        "anki_cards",
        "chapters",
        "chat_conversations",
        "chat_messages",
        "chat_project_materials",
        "chat_projects",
        "coach_events",
        "coach_nudges",
        "coach_preferences",
        "coach_skill_stats",
        "coach_workflows",
        "conversation_summaries",
        "conversations",
        "daily_plans",
        "daily_stats",
        "goals",
        "learning_events",
        "material_profiles",
        "materials",
        "motivation_quotes",
        "motivation_settings",
        "note_links",
        "notes",
        "output_evaluations",
        "pomodoros",
        "questions",
        "quiz_records",
        "review_schedule",
        "study_sessions",
        "tasks",
        "user_memories",
        "user_profiles",
        "users",
        "web_search_cache",
        "wrong_questions",
    }
)

V13_REQUIRED_COLUMNS = {
    "users": frozenset({"id", "username", "email", "hashed_password"}),
    "anki_cards": frozenset({"user_id", "due_at", "interval_days", "ease_factor", "repetitions"}),
    "review_schedule": frozenset({"user_id", "status", "is_archived"}),
    "wrong_questions": frozenset(
        {"user_id", "question_id", "knowledge_point", "recall_difficulty", "mastery_score"}
    ),
    "notes": frozenset({"user_id", "note_type", "material_id", "chapter_id", "tags", "updated_at"}),
    "learning_events": frozenset(
        {"user_id", "source", "dedupe_key", "goal_id", "task_id", "note_id", "wrong_question_id"}
    ),
    "agent_jobs": frozenset({"user_id", "payload", "result", "summary", "updated_at"}),
    "coach_skill_stats": frozenset(
        {"user_id", "skill_id", "channel", "event_type", "shown_count", "lifetime_score"}
    ),
    "user_memories": frozenset(
        {"user_id", "source_type", "source_id", "evidence", "expires_at", "review_status"}
    ),
}

HEAD_ONLY_TABLES = frozenset(
    {
        "concepts",
        "concept_edges",
        "concept_links",
        "note_quote_usages",
        "learner_evidence",
        "user_concept_state",
        "projection_outbox",
    }
)
HEAD_ONLY_COLUMNS = {
    "anki_cards": frozenset({"stability", "difficulty", "fsrs_state", "fsrs_step", "last_review_at"}),
    "review_schedule": frozenset({"stability", "difficulty", "fsrs_state", "fsrs_step", "last_review_at"}),
    "wrong_questions": frozenset({"concept_id"}),
    "notes": frozenset({"source_path"}),
}


def _is_sqlite_url(database_url: str) -> bool:
    return database_url.startswith("sqlite")


def _alembic_config() -> Config:
    backend_dir = Path(__file__).resolve().parent
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    config.set_main_option("sqlalchemy.url", settings.DATABASE_URL)
    return config


def _upgrade_to_head() -> None:
    command.upgrade(_alembic_config(), "head")


def _stamp_v13_baseline() -> None:
    command.stamp(_alembic_config(), V13_BASELINE_REVISION)


async def _read_schema_fingerprint(
    connection: AsyncConnection | None = None,
) -> tuple[
    frozenset[str], dict[str, frozenset[str]], frozenset[str]
]:
    """Read the unmanaged database shape without changing it."""
    def _inspect_schema(sync_connection):
        inspector = inspect(sync_connection)
        table_names = frozenset(inspector.get_table_names())
        columns = {
            table_name: frozenset(column["name"] for column in inspector.get_columns(table_name))
            for table_name in V13_REQUIRED_COLUMNS
            if table_name in table_names
        }
        revision_rows = frozenset()
        if "alembic_version" in table_names:
            revision_rows = frozenset(
                str(version)
                for version in sync_connection.exec_driver_sql(
                    "SELECT version_num FROM alembic_version"
                ).scalars()
            )
        return table_names, columns, revision_rows

    if connection is not None:
        return await connection.run_sync(_inspect_schema)
    async with engine.connect() as fresh_connection:
        return await fresh_connection.run_sync(_inspect_schema)


def _legacy_v13_mismatches(
    table_names: frozenset[str],
    columns_by_table: dict[str, frozenset[str]],
) -> list[str]:
    """Return the reasons an unmanaged database cannot be safely stamped."""
    mismatches: list[str] = []
    missing_tables = sorted(V13_REQUIRED_TABLES - table_names)
    if missing_tables:
        mismatches.append(f"missing tables: {', '.join(missing_tables)}")

    for table_name, required_columns in V13_REQUIRED_COLUMNS.items():
        missing_columns = sorted(required_columns - columns_by_table.get(table_name, frozenset()))
        if missing_columns:
            mismatches.append(f"{table_name} missing columns: {', '.join(missing_columns)}")

    unexpected_tables = sorted(HEAD_ONLY_TABLES & table_names)
    if unexpected_tables:
        mismatches.append(f"already contains post-v1.3 tables: {', '.join(unexpected_tables)}")

    for table_name, post_v13_columns in HEAD_ONLY_COLUMNS.items():
        present_columns = sorted(post_v13_columns & columns_by_table.get(table_name, frozenset()))
        if present_columns:
            mismatches.append(f"{table_name} already contains post-v1.3 columns: {', '.join(present_columns)}")
    return mismatches


async def _run_postgresql_migrations() -> None:
    """Serialize schema inspection, baseline stamping, and Alembic upgrades."""
    async with engine.connect() as lock_connection:
        # Session advisory locks survive the separate Alembic connection, while
        # AUTOCOMMIT avoids holding an idle transaction during a long upgrade.
        lock_connection = await lock_connection.execution_options(
            isolation_level="AUTOCOMMIT"
        )
        lock_params = {"key": POSTGRES_MIGRATION_LOCK_KEY}
        await lock_connection.execute(
            text("SELECT pg_advisory_lock(CAST(:key AS BIGINT))"),
            lock_params,
        )
        try:
            table_names, columns_by_table, current_revisions = await _read_schema_fingerprint(
                lock_connection
            )
            if not current_revisions:
                business_tables = table_names - {"alembic_version"}
                if not business_tables:
                    print("检测到空 PostgreSQL 数据库，执行 Alembic 基线迁移。")
                else:
                    mismatches = _legacy_v13_mismatches(table_names, columns_by_table)
                    if mismatches:
                        detail = "; ".join(mismatches)
                        raise RuntimeError(
                            "Unmanaged PostgreSQL schema does not match the supported v1.3 baseline. "
                            f"Refusing to stamp it automatically: {detail}. "
                            "Back up the database and complete a manual schema reconciliation before rerunning migrations."
                        )
                    print("检测到已验证的 v1.3 PostgreSQL 数据库，写入 Alembic 基线版本。")
                    await asyncio.to_thread(_stamp_v13_baseline)

            await asyncio.to_thread(_upgrade_to_head)
        finally:
            await lock_connection.execute(
                text("SELECT pg_advisory_unlock(CAST(:key AS BIGINT))"),
                lock_params,
            )


async def run_migrations() -> None:
    """Run migrations for the configured database."""

    if _is_sqlite_url(settings.DATABASE_URL):
        print("检测到 SQLite，执行 Base.metadata.create_all + 轻量迁移。")
        await init_db()
        print("SQLite 迁移检查完成。")
        return

    await _run_postgresql_migrations()
    print("Alembic 已升级到 head。")


if __name__ == "__main__":
    asyncio.run(run_migrations())
