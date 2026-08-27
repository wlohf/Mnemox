"""Regression coverage for the versioned PostgreSQL migration design.

The runtime test uses SQLite so it can run locally.  The same Alembic revision
chain is used in production with PostgreSQL, including SQLite batch mode for
the legacy ``wrong_questions`` foreign key.
"""
from __future__ import annotations

import asyncio
from contextlib import asynccontextmanager
from io import StringIO
from pathlib import Path
from unittest.mock import patch

import pytest
from alembic import command
from alembic.config import Config
from sqlalchemy import create_engine, inspect, text
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import create_async_engine

from app.database import Base, _run_lightweight_migrations
import run_migrations as migration_runner
from run_migrations import (
    HEAD_ONLY_COLUMNS,
    HEAD_ONLY_TABLES,
    V13_REQUIRED_COLUMNS,
    V13_REQUIRED_TABLES,
    _legacy_v13_mismatches,
)


BACKEND_DIR = Path(__file__).resolve().parents[1]
V13_BASELINE_REVISION = "20260801_00"
PHASE1_HEAD_REVISION = "20260801_01"
LEARNER_MODEL_REVISION = "20260804_01"
PROJECTION_OUTBOX_REVISION = "20260804_02"
CURRENT_HEAD_REVISION = "20260826_14"


def _run_postgresql_migration_with_fake_lock(events: list[str], upgrade) -> None:
    class FakeConnection:
        async def execution_options(self, **options):
            events.append(f"options:{options['isolation_level']}")
            return self

        async def execute(self, statement, parameters):
            sql = str(statement)
            if "pg_advisory_lock" in sql:
                events.append(f"lock:{parameters['key']}")
            elif "pg_advisory_unlock" in sql:
                events.append(f"unlock:{parameters['key']}")
            else:
                raise AssertionError(f"unexpected SQL: {sql}")

    class FakeEngine:
        @asynccontextmanager
        async def connect(self):
            yield FakeConnection()

    async def fingerprint(connection):
        assert isinstance(connection, FakeConnection)
        events.append("fingerprint")
        return frozenset(), {}, frozenset({CURRENT_HEAD_REVISION})

    async def run() -> None:
        with (
            patch.object(migration_runner, "engine", FakeEngine()),
            patch.object(migration_runner, "_read_schema_fingerprint", fingerprint),
            patch.object(migration_runner, "_upgrade_to_head", upgrade),
        ):
            await migration_runner._run_postgresql_migrations()

    asyncio.run(run())


def _alembic_config(database_path: Path) -> Config:
    config = Config(str(BACKEND_DIR / "alembic.ini"))
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option("sqlalchemy.url", f"sqlite+aiosqlite:///{database_path.as_posix()}")
    return config


def _seed_v13_rows(connection) -> None:
    connection.execute(
        text(
            "INSERT INTO users (id, username, email, hashed_password) "
            "VALUES (1, 'migration-user', 'migration@example.test', 'hash')"
        )
    )
    connection.execute(
        text("INSERT INTO materials (id, user_id, title) VALUES (1, 1, 'Migration material')")
    )
    connection.execute(
        text("INSERT INTO chapters (id, material_id, title) VALUES (1, 1, 'Migration chapter')")
    )
    connection.execute(
        text(
            "INSERT INTO questions (id, user_id, chapter_id, content) "
            "VALUES (1, 1, 1, 'Migration question')"
        )
    )
    connection.execute(
        text(
            "INSERT INTO wrong_questions (id, user_id, question_id, knowledge_point, mastery_score) "
            "VALUES (1, 1, 1, 'legacy point', 12.5)"
        )
    )
    connection.execute(
        text("INSERT INTO notes (id, user_id, title, content) VALUES (1, 1, 'Legacy note', 'body')")
    )
    connection.execute(
        text(
            "INSERT INTO anki_cards "
            "(id, user_id, front, back, interval_days, ease_factor, repetitions) "
            "VALUES (1, 1, 'front', 'back', 3, 250, 2)"
        )
    )
    connection.execute(
        text("INSERT INTO review_schedule (id, user_id, is_archived) VALUES (1, 1, 0)")
    )


def test_alembic_upgrades_v13_rows_to_phase1_without_data_loss(tmp_path: Path):
    database_path = tmp_path / "legacy-v13.db"
    config = _alembic_config(database_path)

    command.upgrade(config, V13_BASELINE_REVISION)

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with engine.begin() as connection:
            _seed_v13_rows(connection)

        command.upgrade(config, PHASE1_HEAD_REVISION)
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO concepts "
                    "(id, user_id, name, name_normalized, mastery, source) "
                    "VALUES (1, 1, 'Legacy concept', 'legacy concept', 72.5, 'backfill')"
                )
            )

        command.upgrade(config, "head")

        inspector = inspect(engine)
        assert {
            "concepts",
            "concept_edges",
            "concept_links",
            "concept_aliases",
            "concept_source_evidence",
            "concept_audit_events",
            "note_quote_usages",
            "prompt_templates",
            "learner_evidence",
            "user_concept_state",
            "projection_outbox",
            "projection_outbox_worker_heartbeats",
            "projection_outbox_retry_policy",
            "memory_declarations",
            "retrieval_projections",
            "retrieval_projection_chunks",
        }.issubset(inspector.get_table_names())

        assert {"stability", "difficulty", "fsrs_state", "fsrs_step", "last_review_at"}.issubset(
            {column["name"] for column in inspector.get_columns("anki_cards")}
        )
        assert {"stability", "difficulty", "fsrs_state", "fsrs_step", "last_review_at"}.issubset(
            {column["name"] for column in inspector.get_columns("review_schedule")}
        )
        assert {
            "source_path",
            "source_vault_id",
            "source_file_id",
            "source_sync_hash",
            "source_sync_state",
            "source_conflict_title",
            "source_conflict_content",
            "source_conflict_hash",
            "source_conflict_vault_id",
            "source_conflict_file_id",
        }.issubset({column["name"] for column in inspector.get_columns("notes")})
        assert {
            "ix_notes_source_path",
            "ix_notes_source_vault_id",
            "ix_notes_source_file_id",
            "ix_notes_source_sync_state",
        }.issubset({
            index["name"] for index in inspector.get_indexes("notes")
        })
        note_indexes = {
            index["name"]: index for index in inspector.get_indexes("notes")
        }
        assert bool(note_indexes["uq_notes_source_identity"]["unique"])
        assert "ix_wrong_questions_concept_id" in {
            index["name"] for index in inspector.get_indexes("wrong_questions")
        }
        assert "review_status" in {column["name"] for column in inspector.get_columns("concepts")}
        assert "review_status" in {column["name"] for column in inspector.get_columns("concept_edges")}
        assert {"attempt_count", "correct_count", "hint_count"}.issubset(
            {column["name"] for column in inspector.get_columns("user_concept_state")}
        )
        assert "ix_concept_aliases_user_concept" in {
            index["name"] for index in inspector.get_indexes("concept_aliases")
        }
        assert "ix_concept_source_evidence_user_source" in {
            index["name"] for index in inspector.get_indexes("concept_source_evidence")
        }
        assert "ix_concept_audit_events_user_concept" in {
            index["name"] for index in inspector.get_indexes("concept_audit_events")
        }
        assert "uq_learning_events_user_type_dedupe" in {
            index["name"] for index in inspector.get_indexes("learning_events")
        }
        assert "dead_lettered_at" in {
            column["name"] for column in inspector.get_columns("projection_outbox")
        }
        assert {
            "user_id",
            "memory_id",
            "subject",
            "predicate",
            "fact_key",
            "value",
            "valid_from",
            "valid_to",
            "observed_at",
            "confidence",
            "review_status",
            "source_type",
            "created_by",
            "supersedes_id",
            "conflicts_with_id",
            "resolution_reason",
        }.issubset(
            {column["name"] for column in inspector.get_columns("memory_declarations")}
        )
        assert {
            "ix_memory_declarations_user_memory_observed",
            "ix_memory_declarations_user_review_observed",
            "ix_memory_declarations_user_fact_review_valid",
            "ix_memory_declarations_conflicts_with_id",
            "uq_memory_declarations_user_fact_current",
        }.issubset(
            {index["name"] for index in inspector.get_indexes("memory_declarations")}
        )
        assert {
            "source_type",
            "source_id",
            "backend",
            "status",
            "source_version",
            "indexed_version",
            "configuration_fingerprint",
            "last_error",
        }.issubset({column["name"] for column in inspector.get_columns("retrieval_projections")})
        assert {"started_count", "abandoned_count"}.issubset(
            {column["name"] for column in inspector.get_columns("coach_skill_stats")}
        )
        assert {
            "id",
            "user_id",
            "nudge_id",
            "action_type",
            "action_payload",
            "status",
            "linked_event_id",
            "outcome_source",
        }.issubset({column["name"] for column in inspector.get_columns("coach_action_attempts")})
        assert "coach_action_attempt_id" in {
            column["name"] for column in inspector.get_columns("pomodoros")
        }
        assert "ix_coach_action_attempts_user_nudge_status" in {
            index["name"] for index in inspector.get_indexes("coach_action_attempts")
        }
        assert "ix_pomodoros_coach_action_attempt_id" in {
            index["name"] for index in inspector.get_indexes("pomodoros")
        }
        assert "ix_retrieval_projections_user_status" in {
            index["name"] for index in inspector.get_indexes("retrieval_projections")
        }
        assert "ix_retrieval_projection_chunks_user_source" in {
            index["name"] for index in inspector.get_indexes("retrieval_projection_chunks")
        }
        assert "ix_projection_outbox_dead_lettered_at" in {
            index["name"] for index in inspector.get_indexes("projection_outbox")
        }
        assert {
            "worker_id",
            "started_at",
            "last_heartbeat_at",
            "last_poll_at",
            "last_success_at",
            "last_error_at",
            "last_projection_failure_at",
            "stopped_at",
            "created_at",
            "updated_at",
        }.issubset(
            {column["name"] for column in inspector.get_columns("projection_outbox_worker_heartbeats")}
        )
        assert "ix_projection_outbox_worker_heartbeats_last_heartbeat_at" in {
            index["name"] for index in inspector.get_indexes("projection_outbox_worker_heartbeats")
        }
        assert {
            "id",
            "max_attempts",
            "policy_version",
            "created_at",
            "updated_at",
        }.issubset(
            {
                column["name"]
                for column in inspector.get_columns("projection_outbox_retry_policy")
            }
        )
        assert any(
            foreign_key["referred_table"] == "concepts"
            and foreign_key["constrained_columns"] == ["concept_id"]
            for foreign_key in inspector.get_foreign_keys("wrong_questions")
        )
        assert "uq_concepts_user_name" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("concepts")
        }
        assert "uq_concept_edges_pair" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("concept_edges")
        }
        assert "uq_concept_links_target" in {
            constraint["name"] for constraint in inspector.get_unique_constraints("concept_links")
        }

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT knowledge_point, mastery_score, concept_id FROM wrong_questions WHERE id = 1")
            ).one() == ("legacy point", 12.5, None)
            assert connection.execute(
                text("SELECT title, content, source_path FROM notes WHERE id = 1")
            ).one() == ("Legacy note", "body", None)
            assert connection.execute(
                text("SELECT interval_days, repetitions, stability FROM anki_cards WHERE id = 1")
            ).one() == (3, 2, None)
            assert connection.execute(
                text("SELECT interval_days, is_archived, stability FROM review_schedule WHERE id = 1")
            ).one() == (None, 0, None)
            assert connection.execute(
                text("SELECT mastery FROM concepts WHERE id = 1")
            ).scalar_one() == 72.5
            assert connection.execute(
                text(
                    "SELECT evidence_type, evidence_category, score, reliability, source_type "
                    "FROM learner_evidence WHERE user_id = 1 AND concept_id = 1"
                )
            ).one() == ("legacy_mastery", "legacy", 0.725, 0.35, "legacy")
            assert connection.execute(
                text(
                    "SELECT mastery_estimate, confidence, model_version "
                    "FROM user_concept_state WHERE user_id = 1 AND concept_id = 1"
                )
            ).one() == (72.5, 0.35, "legacy-concept-mastery-v1")
            assert connection.execute(text("SELECT version_num FROM alembic_version")).scalar_one() == CURRENT_HEAD_REVISION

        command.upgrade(config, "head")
        command.check(config)

        with engine.connect() as connection:
            assert connection.execute(text("SELECT COUNT(*) FROM wrong_questions")).scalar_one() == 1
    finally:
        engine.dispose()


def test_v13_fingerprint_accepts_only_the_supported_pre_alembic_shape():
    valid_columns = {
        table_name: frozenset(required_columns)
        for table_name, required_columns in V13_REQUIRED_COLUMNS.items()
    }
    assert _legacy_v13_mismatches(frozenset(V13_REQUIRED_TABLES), valid_columns) == []

    changed_shape = set(V13_REQUIRED_TABLES) | set(HEAD_ONLY_TABLES)
    changed_columns = dict(valid_columns)
    changed_columns["notes"] = valid_columns["notes"] | HEAD_ONLY_COLUMNS["notes"]
    mismatches = _legacy_v13_mismatches(frozenset(changed_shape), changed_columns)

    assert any("post-v1.3 tables" in mismatch for mismatch in mismatches)
    assert any("post-v1.3 columns" in mismatch for mismatch in mismatches)


def test_v13_fingerprint_rejects_unversioned_learner_projection_tables():
    valid_columns = {
        table_name: frozenset(required_columns)
        for table_name, required_columns in V13_REQUIRED_COLUMNS.items()
    }
    table_names = frozenset(
        set(V13_REQUIRED_TABLES)
        | {
            "learner_evidence",
            "user_concept_state",
            "projection_outbox",
            "projection_outbox_worker_heartbeats",
            "projection_outbox_retry_policy",
        }
    )

    mismatches = _legacy_v13_mismatches(table_names, valid_columns)

    assert any("learner_evidence" in mismatch for mismatch in mismatches)
    assert any("user_concept_state" in mismatch for mismatch in mismatches)
    assert any("projection_outbox" in mismatch for mismatch in mismatches)
    assert any("projection_outbox_worker_heartbeats" in mismatch for mismatch in mismatches)
    assert any("projection_outbox_retry_policy" in mismatch for mismatch in mismatches)


def test_postgresql_migration_runner_serializes_full_upgrade_path():
    events: list[str] = []

    def upgrade() -> None:
        events.append("upgrade")

    _run_postgresql_migration_with_fake_lock(events, upgrade)

    lock_key = str(migration_runner.POSTGRES_MIGRATION_LOCK_KEY)
    assert events == [
        "options:AUTOCOMMIT",
        f"lock:{lock_key}",
        "fingerprint",
        "upgrade",
        f"unlock:{lock_key}",
    ]


def test_postgresql_migration_runner_releases_lock_after_upgrade_failure():
    events: list[str] = []

    def broken_upgrade() -> None:
        events.append("upgrade")
        raise RuntimeError("migration failed")

    with pytest.raises(RuntimeError, match="migration failed"):
        _run_postgresql_migration_with_fake_lock(events, broken_upgrade)

    lock_key = str(migration_runner.POSTGRES_MIGRATION_LOCK_KEY)
    assert events == [
        "options:AUTOCOMMIT",
        f"lock:{lock_key}",
        "fingerprint",
        "upgrade",
        f"unlock:{lock_key}",
    ]


def test_postgresql_offline_ddl_includes_the_required_foreign_keys():
    output = StringIO()
    config = Config(str(BACKEND_DIR / "alembic.ini"), output_buffer=output)
    config.set_main_option("script_location", str(BACKEND_DIR / "alembic"))
    config.set_main_option(
        "sqlalchemy.url",
        "postgresql+asyncpg://postgres:password@localhost:5432/mnemox_test",
    )

    command.upgrade(config, "head", sql=True)

    ddl = output.getvalue()
    assert "CREATE TABLE concepts" in ddl
    assert "CREATE TABLE concept_edges" in ddl
    assert "CREATE TABLE concept_links" in ddl
    assert "CREATE TABLE concept_aliases" in ddl
    assert "CREATE TABLE concept_source_evidence" in ddl
    assert "CREATE TABLE concept_audit_events" in ddl
    assert "ALTER TABLE concepts ADD COLUMN review_status" in ddl
    assert "ALTER TABLE user_concept_state ADD COLUMN attempt_count" in ddl
    assert "CREATE TABLE learner_evidence" in ddl
    assert "CREATE TABLE user_concept_state" in ddl
    assert "CREATE TABLE projection_outbox" in ddl
    assert "ALTER TABLE projection_outbox ADD COLUMN dead_lettered_at" in ddl
    assert "CREATE INDEX ix_projection_outbox_dead_lettered_at" in ddl
    assert "CREATE INDEX ix_projection_outbox_operations_active" in ddl
    assert "CREATE TABLE projection_outbox_worker_heartbeats" in ddl
    assert "ix_projection_outbox_worker_heartbeats_last_heartbeat_at" in ddl
    assert "CREATE TABLE projection_outbox_retry_policy" in ddl
    assert "fk_wrong_questions_concept_id" in ddl
    assert "fk_learner_evidence_source_event_id" in ddl
    assert "fk_projection_outbox_source_event_id" in ddl
    assert "FOREIGN KEY(concept_id) REFERENCES concepts" in ddl
    assert "ALTER TABLE notes ADD COLUMN source_vault_id" in ddl
    assert "ALTER TABLE notes ADD COLUMN source_file_id" in ddl
    assert "ALTER TABLE notes ADD COLUMN source_sync_state" in ddl
    assert "CREATE UNIQUE INDEX uq_notes_source_identity" in ddl
    assert "ALTER TABLE notes ADD COLUMN source_conflict_vault_id" in ddl
    assert "ALTER TABLE notes ADD COLUMN source_conflict_file_id" in ddl
    assert "CREATE TABLE memory_declarations" in ddl
    assert "CREATE TABLE retrieval_projections" in ddl
    assert "CREATE TABLE retrieval_projection_chunks" in ddl
    assert "CREATE INDEX ix_retrieval_projections_user_status" in ddl
    assert "CREATE INDEX ix_retrieval_projection_chunks_user_source" in ddl
    assert "FOREIGN KEY(user_id) REFERENCES users" in ddl
    assert "FOREIGN KEY(memory_id) REFERENCES user_memories" in ddl
    assert "CREATE INDEX ix_memory_declarations_user_memory_observed" in ddl
    assert "ALTER TABLE memory_declarations ADD COLUMN fact_key" in ddl
    assert "ALTER TABLE coach_skill_stats ADD COLUMN started_count" in ddl
    assert "ALTER TABLE coach_skill_stats ADD COLUMN abandoned_count" in ddl
    assert "CREATE TABLE coach_action_attempts" in ddl
    assert "fk_coach_action_attempts_nudge_id" in ddl
    assert "ALTER TABLE pomodoros ADD COLUMN coach_action_attempt_id" in ddl
    assert "CREATE INDEX ix_pomodoros_coach_action_attempt_id" in ddl
    assert "CREATE INDEX ix_memory_declarations_user_fact_review_valid" in ddl
    assert "CREATE UNIQUE INDEX uq_memory_declarations_user_fact_current" in ddl


def test_projection_outbox_operations_migration_defers_legacy_terminal_classification(tmp_path: Path):
    database_path = tmp_path / "legacy-projection-outbox.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "20260809_04")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    """
                    INSERT INTO projection_outbox (
                        id, user_id, source_event_id, idempotency_key, projection_type,
                        model_version, payload_version, payload, status, attempts,
                        available_at, updated_at
                    ) VALUES
                        (1, 1, 1, 'terminal', 'learner_state', 'v1', 1, '{}',
                         'failed', 5, CURRENT_TIMESTAMP, '2026-08-01 12:34:56'),
                        (2, 1, 2, 'retryable', 'learner_state', 'v1', 1, '{}',
                         'failed', 4, CURRENT_TIMESTAMP, '2026-08-01 12:34:56')
                    """
                )
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            assert connection.execute(
                text("SELECT dead_lettered_at FROM projection_outbox WHERE id = 1")
            ).scalar_one() is None
            assert connection.execute(
                text("SELECT dead_lettered_at FROM projection_outbox WHERE id = 2")
            ).scalar_one() is None
    finally:
        engine.dispose()


def test_projection_outbox_operations_performance_migration_adds_active_queue_index(tmp_path: Path):
    database_path = tmp_path / "projection-outbox-operations-performance.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "20260809_05")
    command.upgrade(config, "head")

    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with engine.connect() as connection:
            definition = connection.execute(
                text(
                    "SELECT sql FROM sqlite_master "
                    "WHERE type = 'index' AND name = 'ix_projection_outbox_operations_active'"
                )
            ).scalar_one()
    finally:
        engine.dispose()

    assert "WHERE status IN ('pending', 'processing', 'failed')" in definition


def test_sqlite_lightweight_migration_upgrades_legacy_outbox_operations_schema(tmp_path: Path):
    database_path = tmp_path / "legacy-local-projection-outbox.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "20260809_04")

    async def _run() -> tuple[set[str], set[str], set[str], set[str], str | None]:
        async_engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True
        )
        try:
            async with async_engine.begin() as connection:
                await connection.execute(
                    text(
                        """
                        INSERT INTO projection_outbox (
                            id, user_id, source_event_id, idempotency_key, projection_type,
                            model_version, payload_version, payload, status, attempts,
                            available_at, updated_at
                        ) VALUES
                            (1, 1, 1, 'terminal', 'learner_state', 'v1', 1, '{}',
                             'failed', 5, CURRENT_TIMESTAMP, '2026-08-01 12:34:56')
                        """
                    )
                )
                await _run_lightweight_migrations(connection)
                tables = await connection.run_sync(
                    lambda sync_connection: set(inspect(sync_connection).get_table_names())
                )
                outbox_columns = await connection.run_sync(
                    lambda sync_connection: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns("projection_outbox")
                    }
                )
                outbox_indexes = await connection.run_sync(
                    lambda sync_connection: {
                        index["name"]
                        for index in inspect(sync_connection).get_indexes("projection_outbox")
                    }
                )
                heartbeat_indexes = await connection.run_sync(
                    lambda sync_connection: {
                        index["name"]
                        for index in inspect(sync_connection).get_indexes(
                            "projection_outbox_worker_heartbeats"
                        )
                    }
                )
                heartbeat_columns = await connection.run_sync(
                    lambda sync_connection: {
                        column["name"]: column
                        for column in inspect(sync_connection).get_columns(
                            "projection_outbox_worker_heartbeats"
                        )
                    }
                )
                retry_policy_columns = await connection.run_sync(
                    lambda sync_connection: {
                        column["name"]
                        for column in inspect(sync_connection).get_columns(
                            "projection_outbox_retry_policy"
                        )
                    }
                )
                assert heartbeat_columns["worker_id"]["nullable"] is False
                with pytest.raises(IntegrityError):
                    await connection.execute(
                        text(
                            """
                            INSERT INTO projection_outbox_worker_heartbeats (
                                worker_id, started_at, last_heartbeat_at
                            ) VALUES (NULL, CURRENT_TIMESTAMP, CURRENT_TIMESTAMP)
                            """
                        )
                    )
                dead_lettered_at = await connection.scalar(
                    text("SELECT dead_lettered_at FROM projection_outbox WHERE id = 1")
                )
                return (
                    tables,
                    outbox_columns,
                    outbox_indexes | heartbeat_indexes,
                    retry_policy_columns,
                    dead_lettered_at,
                )
        finally:
            await async_engine.dispose()

    tables, outbox_columns, indexes, retry_policy_columns, dead_lettered_at = asyncio.run(_run())
    assert "projection_outbox_worker_heartbeats" in tables
    assert "projection_outbox_retry_policy" in tables
    assert "dead_lettered_at" in outbox_columns
    assert "ix_projection_outbox_dead_lettered_at" in indexes
    assert "ix_projection_outbox_operations_active" in indexes
    assert "ix_projection_outbox_worker_heartbeats_last_heartbeat_at" in indexes
    assert {"id", "max_attempts", "policy_version"}.issubset(retry_policy_columns)
    assert dead_lettered_at is None


def test_sqlite_lightweight_migration_upgrades_legacy_notes_with_vault_sync_state(tmp_path: Path):
    database_path = tmp_path / "legacy-local-notes.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "20260812_06")

    async def _run() -> tuple[set[str], set[str]]:
        async_engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True
        )
        try:
            async with async_engine.begin() as connection:
                await _run_lightweight_migrations(connection)
                return await connection.run_sync(
                    lambda sync_connection: (
                        {
                            column["name"]
                            for column in inspect(sync_connection).get_columns("notes")
                        },
                        {
                            index["name"]
                            for index in inspect(sync_connection).get_indexes("notes")
                        },
                    )
                )
        finally:
            await async_engine.dispose()

    columns, indexes = asyncio.run(_run())
    assert {
        "source_vault_id",
        "source_file_id",
        "source_sync_hash",
        "source_sync_state",
        "source_conflict_title",
        "source_conflict_content",
        "source_conflict_hash",
        "source_conflict_vault_id",
        "source_conflict_file_id",
    }.issubset(columns)
    assert {
        "ix_notes_source_vault_id",
        "ix_notes_source_file_id",
        "ix_notes_source_sync_state",
        "uq_notes_source_identity",
    }.issubset(indexes)


def test_sqlite_lightweight_migration_adds_memory_declaration_audit_table(tmp_path: Path):
    database_path = tmp_path / "legacy-local-memories.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "20260816_08")

    async def _run() -> tuple[set[str], set[str]]:
        async_engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True
        )
        try:
            async with async_engine.begin() as connection:
                await _run_lightweight_migrations(connection)
                return await connection.run_sync(
                    lambda sync_connection: (
                        {
                            column["name"]
                            for column in inspect(sync_connection).get_columns("memory_declarations")
                        },
                        {
                            index["name"]
                            for index in inspect(sync_connection).get_indexes("memory_declarations")
                        },
                    )
                )
        finally:
            await async_engine.dispose()

    columns, indexes = asyncio.run(_run())
    assert {
        "user_id",
        "memory_id",
        "subject",
        "predicate",
        "fact_key",
        "value",
        "valid_from",
        "valid_to",
        "observed_at",
        "confidence",
        "review_status",
        "source_type",
        "created_by",
        "supersedes_id",
        "conflicts_with_id",
        "resolution_reason",
    }.issubset(columns)
    assert {
        "ix_memory_declarations_user_memory_observed",
        "ix_memory_declarations_user_review_observed",
        "ix_memory_declarations_user_fact_review_valid",
        "ix_memory_declarations_conflicts_with_id",
        "uq_memory_declarations_user_fact_current",
    }.issubset(indexes)


def test_temporal_memory_migration_backfills_existing_fact_identity(tmp_path: Path):
    database_path = tmp_path / "legacy-temporal-memory.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "20260822_11")
    engine = create_engine(f"sqlite:///{database_path.as_posix()}")
    try:
        with engine.begin() as connection:
            connection.execute(
                text(
                    "INSERT INTO users (id, username, email, hashed_password) "
                    "VALUES (1, 'memory-migration', 'memory-migration@example.test', 'hash')"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO user_memories "
                    "(id, user_id, memory_key, memory_value, category, status, review_status, is_locked) "
                    "VALUES "
                    "(7, 1, 'current_learning_goal', '用户锁定的学习目标', 'goal', 'active', 'confirmed', 1), "
                    "(8, 1, 'current_learning_goal', '较新的自动冲突目标', 'goal', 'active', 'confirmed', 0)"
                )
            )
            connection.execute(
                text(
                    "INSERT INTO memory_declarations "
                    "(id, user_id, memory_id, subject, predicate, value, valid_from, observed_at, confidence, "
                    "review_status, source_type, created_by) VALUES "
                    "(9, 1, 7, 'user:1', 'goal', '用户锁定的学习目标', "
                    "'2026-08-22 10:00:00', '2026-08-22 10:00:00', 0.9, "
                    "'confirmed', 'manual', 'user'), "
                    "(10, 1, 8, 'user:1', 'goal', '较新的自动冲突目标', "
                    "'2026-08-22 11:00:00', '2026-08-22 11:00:00', 0.9, "
                    "'confirmed', 'learning_event', 'agent')"
                )
            )

        command.upgrade(config, "head")

        with engine.connect() as connection:
            fact = connection.execute(
                text(
                    "SELECT fact_key, conflicts_with_id, resolution_reason "
                    "FROM memory_declarations WHERE id = 9"
                )
            ).one()
            duplicate = connection.execute(
                text(
                    "SELECT fact_key, review_status, resolution_reason "
                    "FROM memory_declarations WHERE id = 10"
                )
            ).one()
            duplicate_projection_status = connection.execute(
                text("SELECT status FROM user_memories WHERE id = 8")
            ).scalar_one()
        assert tuple(fact) == ("current_learning_goal", None, None)
        assert tuple(duplicate) == (
            "current_learning_goal",
            "superseded",
            "migration_reconciled_duplicate_fact",
        )
        assert duplicate_projection_status == "superseded"
    finally:
        engine.dispose()


def test_sqlite_lightweight_migration_adds_rebuildable_retrieval_manifests(tmp_path: Path):
    database_path = tmp_path / "legacy-local-retrieval.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "20260816_09")

    async def _run() -> tuple[set[str], set[str], set[str]]:
        async_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
        try:
            async with async_engine.begin() as connection:
                await _run_lightweight_migrations(connection)
                await _run_lightweight_migrations(connection)
                return await connection.run_sync(
                    lambda sync_connection: (
                        {column["name"] for column in inspect(sync_connection).get_columns("retrieval_projections")},
                        {index["name"] for index in inspect(sync_connection).get_indexes("retrieval_projections")},
                        {
                            index["name"]
                            for index in inspect(sync_connection).get_indexes("retrieval_projection_chunks")
                        },
                    )
                )
        finally:
            await async_engine.dispose()

    columns, indexes, chunk_indexes = asyncio.run(_run())
    assert {"source_id", "status", "source_version", "last_error", "deleted_at"}.issubset(columns)
    assert "ix_retrieval_projections_user_status" in indexes
    assert "ix_retrieval_projection_chunks_user_source" in chunk_indexes


def test_sqlite_lightweight_migration_adds_reviewable_concept_provenance(tmp_path: Path):
    database_path = tmp_path / "legacy-local-concept-provenance.db"
    config = _alembic_config(database_path)
    command.upgrade(config, "20260822_10")

    async def _run() -> tuple[set[str], set[str], set[str], set[str]]:
        async_engine = create_async_engine(f"sqlite+aiosqlite:///{database_path.as_posix()}")
        try:
            async with async_engine.begin() as connection:
                await _run_lightweight_migrations(connection)
                await _run_lightweight_migrations(connection)
                return await connection.run_sync(
                    lambda sync_connection: (
                        set(inspect(sync_connection).get_table_names()),
                        {column["name"] for column in inspect(sync_connection).get_columns("concepts")},
                        {column["name"] for column in inspect(sync_connection).get_columns("user_concept_state")},
                        {
                            index["name"]
                            for index in inspect(sync_connection).get_indexes("concept_source_evidence")
                        },
                    )
                )
        finally:
            await async_engine.dispose()

    tables, concept_columns, state_columns, evidence_indexes = asyncio.run(_run())
    assert {"concept_aliases", "concept_source_evidence", "concept_audit_events"}.issubset(tables)
    assert "review_status" in concept_columns
    assert {"attempt_count", "correct_count", "hint_count"}.issubset(state_columns)
    assert "ix_concept_source_evidence_user_source" in evidence_indexes


def test_sqlite_lightweight_migration_backfills_legacy_mastery_idempotently(tmp_path: Path):
    database_path = tmp_path / "legacy-local.db"

    async def _run() -> tuple[int, int, float, int]:
        import app.models  # noqa: F401

        async_engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True
        )
        try:
            async with async_engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.execute(
                    text(
                        "INSERT INTO users (id, username, email, hashed_password) "
                        "VALUES (1, 'local-user', 'local@example.test', 'hash')"
                    )
                )
                await connection.execute(
                    text(
                        "INSERT INTO concepts "
                        "(id, user_id, name, name_normalized, mastery, source) "
                        "VALUES (1, 1, 'Local concept', 'local concept', 61.0, 'backfill')"
                    )
                )
                await _run_lightweight_migrations(connection)
                await connection.execute(
                    text(
                        "INSERT INTO concepts "
                        "(id, user_id, name, name_normalized, mastery, source) "
                        "VALUES (2, 1, 'Post rollout concept', 'post rollout concept', 90.0, 'extract')"
                    )
                )
                await _run_lightweight_migrations(connection)
                evidence_count = int(
                    (await connection.execute(text("SELECT COUNT(*) FROM learner_evidence"))).scalar_one()
                )
                state_count = int(
                    (await connection.execute(text("SELECT COUNT(*) FROM user_concept_state"))).scalar_one()
                )
                mastery = float(
                    (
                        await connection.execute(
                            text(
                                "SELECT mastery_estimate FROM user_concept_state "
                                "WHERE user_id = 1 AND concept_id = 1"
                            )
                        )
                    ).scalar_one()
                )
                post_rollout_count = int(
                    (
                        await connection.execute(
                            text(
                                "SELECT COUNT(*) FROM learner_evidence "
                                "WHERE concept_id = 2"
                            )
                        )
                    ).scalar_one()
                )
                return evidence_count, state_count, mastery, post_rollout_count
        finally:
            await async_engine.dispose()

    assert asyncio.run(_run()) == (1, 1, 61.0, 0)


def test_sqlite_lightweight_migration_restores_event_dedupe_index(tmp_path: Path):
    database_path = tmp_path / "legacy-event-dedupe.db"

    async def _run() -> tuple[int, int, bool]:
        import app.models  # noqa: F401

        async_engine = create_async_engine(
            f"sqlite+aiosqlite:///{database_path.as_posix()}", future=True
        )
        try:
            async with async_engine.begin() as connection:
                await connection.run_sync(Base.metadata.create_all)
                await connection.execute(text("DROP INDEX uq_learning_events_user_type_dedupe"))
                await connection.execute(
                    text(
                        "INSERT INTO users (id, username, email, hashed_password) "
                        "VALUES (1, 'dedupe-user', 'dedupe@example.test', 'hash')"
                    )
                )
                for event_id in (1, 2):
                    await connection.execute(
                        text(
                            "INSERT INTO learning_events "
                            "(id, user_id, event_type, dedupe_key, timestamp) "
                            "VALUES (:event_id, 1, 'note.created', 'legacy-duplicate', CURRENT_TIMESTAMP)"
                        ),
                        {"event_id": event_id},
                    )

                await _run_lightweight_migrations(connection)
                remaining_keys = int(
                    (
                        await connection.execute(
                            text(
                                "SELECT COUNT(*) FROM learning_events "
                                "WHERE dedupe_key = 'legacy-duplicate'"
                            )
                        )
                    ).scalar_one()
                )
                event_count = int(
                    (await connection.execute(text("SELECT COUNT(*) FROM learning_events"))).scalar_one()
                )
                indexes = await connection.run_sync(
                    lambda sync_connection: {
                        item["name"]
                        for item in inspect(sync_connection).get_indexes("learning_events")
                    }
                )
                return event_count, remaining_keys, "uq_learning_events_user_type_dedupe" in indexes
        finally:
            await async_engine.dispose()

    assert asyncio.run(_run()) == (2, 1, True)
