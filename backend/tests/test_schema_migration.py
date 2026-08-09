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
CURRENT_HEAD_REVISION = "20260809_04"


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
            "note_quote_usages",
            "prompt_templates",
            "learner_evidence",
            "user_concept_state",
            "projection_outbox",
        }.issubset(inspector.get_table_names())

        assert {"stability", "difficulty", "fsrs_state", "fsrs_step", "last_review_at"}.issubset(
            {column["name"] for column in inspector.get_columns("anki_cards")}
        )
        assert {"stability", "difficulty", "fsrs_state", "fsrs_step", "last_review_at"}.issubset(
            {column["name"] for column in inspector.get_columns("review_schedule")}
        )
        assert "source_path" in {column["name"] for column in inspector.get_columns("notes")}
        assert "ix_notes_source_path" in {
            index["name"] for index in inspector.get_indexes("notes")
        }
        assert "ix_wrong_questions_concept_id" in {
            index["name"] for index in inspector.get_indexes("wrong_questions")
        }
        assert "uq_learning_events_user_type_dedupe" in {
            index["name"] for index in inspector.get_indexes("learning_events")
        }
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
        | {"learner_evidence", "user_concept_state", "projection_outbox"}
    )

    mismatches = _legacy_v13_mismatches(table_names, valid_columns)

    assert any("learner_evidence" in mismatch for mismatch in mismatches)
    assert any("user_concept_state" in mismatch for mismatch in mismatches)
    assert any("projection_outbox" in mismatch for mismatch in mismatches)


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


def test_postgresql_offline_ddl_includes_the_concept_foreign_key():
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
    assert "CREATE TABLE learner_evidence" in ddl
    assert "CREATE TABLE user_concept_state" in ddl
    assert "CREATE TABLE projection_outbox" in ddl
    assert "fk_wrong_questions_concept_id" in ddl
    assert "fk_learner_evidence_source_event_id" in ddl
    assert "fk_projection_outbox_source_event_id" in ddl
    assert "FOREIGN KEY(concept_id) REFERENCES concepts" in ddl


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
