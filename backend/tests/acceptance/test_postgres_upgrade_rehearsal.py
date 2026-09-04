"""Data-preservation checks for the historical PostgreSQL release rehearsal."""
from __future__ import annotations

import os
import unittest
from pathlib import Path

from alembic.config import Config
from alembic.script import ScriptDirectory
from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine


DATABASE_URL = os.environ.get("POSTGRES_UPGRADE_REHEARSAL_DATABASE_URL", "").strip()
POSTGRES_URL_CONFIGURED = DATABASE_URL.startswith("postgresql+asyncpg://")


def _expected_alembic_head() -> str:
    backend_dir = Path(__file__).resolve().parents[2]
    config = Config(str(backend_dir / "alembic.ini"))
    config.set_main_option("script_location", str(backend_dir / "alembic"))
    revision = ScriptDirectory.from_config(config).get_current_head()
    if revision is None:
        raise RuntimeError("Alembic revision graph has no head")
    return revision


@unittest.skipUnless(
    POSTGRES_URL_CONFIGURED,
    "set POSTGRES_UPGRADE_REHEARSAL_DATABASE_URL to run the upgrade rehearsal",
)
class PostgresUpgradeRehearsalTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(DATABASE_URL, pool_pre_ping=True)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def test_historical_rows_and_current_schema_survive_dump_restore_upgrade(self) -> None:
        async with self.sessions() as session:
            server_version = int(await session.scalar(text("SHOW server_version_num")))
            revision = await session.scalar(text("SELECT version_num FROM alembic_version"))
            user = (
                await session.execute(
                    text(
                        "SELECT username, email, token_version, failed_login_count, "
                        "login_failed_window_started_at, login_locked_until "
                        "FROM users WHERE id = 91001"
                    )
                )
            ).one()
            material = (
                await session.execute(
                    text("SELECT title, content FROM materials WHERE id = 92001")
                )
            ).one()
            note = (
                await session.execute(
                    text(
                        "SELECT title, content, source_vault_id, source_file_id, "
                        "source_sync_state FROM notes WHERE id = 93001"
                    )
                )
            ).one()
            event = (
                await session.execute(
                    text(
                        "SELECT event_type, source, dedupe_key, material_id, note_id "
                        "FROM learning_events WHERE id = 95001"
                    )
                )
            ).one()
            evidence = (
                await session.execute(
                    text(
                        "SELECT evidence_type, evidence_category, score, reliability, source_type "
                        "FROM learner_evidence "
                        "WHERE user_id = 91001 AND concept_id = 94001"
                    )
                )
            ).one()
            state = (
                await session.execute(
                    text(
                        "SELECT mastery_estimate, confidence, model_version "
                        "FROM user_concept_state "
                        "WHERE user_id = 91001 AND concept_id = 94001"
                    )
                )
            ).one()
            current_tables = set(
                (
                    await session.execute(
                        text(
                            "SELECT table_name FROM information_schema.tables "
                            "WHERE table_schema = 'public'"
                        )
                    )
                ).scalars()
            )

        self.assertGreaterEqual(server_version, 160000)
        self.assertLess(server_version, 170000)
        self.assertEqual(revision, _expected_alembic_head())
        self.assertEqual(
            user,
            (
                "pg-upgrade-user",
                "pg-upgrade@example.test",
                0,
                0,
                None,
                None,
            ),
        )
        self.assertEqual(
            material,
            ("Historical PostgreSQL material", "preserve this material"),
        )
        self.assertEqual(
            note,
            ("Historical PostgreSQL note", "preserve this note", None, None, None),
        )
        self.assertEqual(
            event,
            (
                "practice.answer",
                "postgres-upgrade-rehearsal",
                "pg-upgrade-rehearsal:95001",
                92001,
                93001,
            ),
        )
        self.assertEqual(
            evidence,
            ("legacy_mastery", "legacy", 0.725, 0.35, "legacy"),
        )
        self.assertEqual(
            state,
            (72.5, 0.35, "legacy-concept-mastery-v1"),
        )
        self.assertTrue(
            {
                "coach_action_attempts",
                "memory_declarations",
                "projection_outbox",
                "retrieval_projections",
            }.issubset(current_tables)
        )
