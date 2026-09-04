import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.agents.manager import agent_manager
from app.database import Base
from app.models.agent import AgentExecutionLog, AgentJob
from app.models.note import Note
from app.models.user import User
from app.models.user_profile import UserProfile
from app.services.learning_snapshot_service import build_learning_snapshot
from app.services.profile_service import compute_and_save_profile


class CountingAsyncSession(AsyncSession):
    commit_calls: int

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.commit_calls = 0

    async def commit(self) -> None:
        self.commit_calls += 1
        await super().commit()


class ProfileTransactionContractTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        database_path = Path(self.tmpdir.name) / "profile_transaction.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database_path}", future=True)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(
            self.engine,
            class_=CountingAsyncSession,
            expire_on_commit=False,
        )
        async with self.sessions() as session:
            user = User(
                username="profile-transaction",
                email="profile-transaction@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.commit()
            self.user_id = int(user.id)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def test_profile_projection_never_commits_its_callers_transaction(self):
        async with self.sessions() as session:
            session.add(
                Note(
                    user_id=self.user_id,
                    title="与画像同一事务",
                    content="如果调用方回滚，这条笔记和画像都必须回滚。",
                )
            )
            profile = await compute_and_save_profile(session, self.user_id)

            self.assertEqual(profile.user_id, self.user_id)
            self.assertEqual(session.commit_calls, 0)
            await session.rollback()

        async with self.sessions() as session:
            note_count = int(
                (await session.execute(select(func.count(Note.id)))).scalar_one()
            )
            stored_profile = await session.get(UserProfile, self.user_id)

        self.assertEqual(note_count, 0)
        self.assertIsNone(stored_profile)

    async def test_explicit_caller_commit_persists_the_projection(self):
        async with self.sessions() as session:
            await compute_and_save_profile(session, self.user_id)
            self.assertEqual(session.commit_calls, 0)
            await session.commit()
            self.assertEqual(session.commit_calls, 1)

        async with self.sessions() as session:
            stored_profile = await session.get(UserProfile, self.user_id)

        self.assertIsNotNone(stored_profile)

    async def test_supported_database_uses_atomic_profile_upsert(self):
        statements: list[str] = []

        def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(str(statement))

        event.listen(self.engine.sync_engine, "before_cursor_execute", capture_statement)
        try:
            async with self.sessions() as session:
                await compute_and_save_profile(session, self.user_id)
                await session.commit()
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", capture_statement)

        profile_inserts = [
            statement.upper()
            for statement in statements
            if "INSERT INTO USER_PROFILES" in statement.upper()
        ]
        self.assertEqual(len(profile_inserts), 1)
        self.assertIn("ON CONFLICT", profile_inserts[0])
        self.assertIn("DO UPDATE", profile_inserts[0])

    async def test_profile_upsert_preserves_fields_owned_by_other_producers(self):
        async with self.sessions() as session:
            session.add(
                UserProfile(
                    user_id=self.user_id,
                    learning_style="visual",
                    ai_assessment="由其他画像生产者维护",
                )
            )
            await session.commit()

        async with self.sessions() as session:
            profile = await compute_and_save_profile(session, self.user_id)
            await session.commit()

            self.assertEqual(profile.learning_style, "visual")
            self.assertEqual(profile.ai_assessment, "由其他画像生产者维护")

        async with self.sessions() as session:
            count = int(
                (await session.execute(select(func.count(UserProfile.user_id)))).scalar_one()
            )
            stored = await session.get(UserProfile, self.user_id)

        self.assertEqual(count, 1)
        self.assertEqual(stored.learning_style, "visual")
        self.assertEqual(stored.ai_assessment, "由其他画像生产者维护")

    async def test_learning_snapshot_does_not_create_a_missing_profile(self):
        async with self.sessions() as session:
            snapshot = await build_learning_snapshot(
                session,
                self.user_id,
                include_memories=False,
            )
            self.assertEqual(snapshot["profile"], {})
            self.assertEqual(session.commit_calls, 0)
            await session.rollback()

        async with self.sessions() as session:
            stored_profile = await session.get(UserProfile, self.user_id)

        self.assertIsNone(stored_profile)

    async def test_read_only_agent_tool_does_not_commit_pending_state(self):
        async with self.sessions() as session:
            session.add(
                Note(
                    user_id=self.user_id,
                    title="未提交的 Kernel 上下文",
                    content="只读工具不能替调用方提交。",
                )
            )
            result = await agent_manager.call_chat_tool(
                session,
                self.user_id,
                "get_profile",
                "",
                5,
            )

            self.assertIsNone(result["profile"])
            self.assertEqual(session.commit_calls, 0)
            await session.rollback()

        async with self.sessions() as session:
            note_count = int(
                (await session.execute(select(func.count(Note.id)))).scalar_one()
            )
            log_count = int(
                (await session.execute(select(func.count(AgentExecutionLog.id)))).scalar_one()
            )

        self.assertEqual(note_count, 0)
        self.assertEqual(log_count, 0)

    async def test_failed_agent_job_persists_only_a_redacted_error_summary(self):
        failing_agent = AsyncMock()
        failing_agent.run.side_effect = RuntimeError(
            "provider rejected Authorization: Bearer persisted-secret"
        )

        with patch.dict(agent_manager.agents, {"chat": failing_agent}):
            async with self.sessions() as session:
                with self.assertRaises(RuntimeError):
                    await agent_manager.trigger(session, self.user_id, "chat", "run")

        async with self.sessions() as session:
            job = await session.scalar(
                select(AgentJob).where(AgentJob.user_id == self.user_id)
            )
            log = await session.scalar(
                select(AgentExecutionLog)
                .where(AgentExecutionLog.user_id == self.user_id, AgentExecutionLog.status == "failed")
            )

        self.assertIsNotNone(job)
        self.assertIsNotNone(log)
        self.assertIn("RuntimeError", job.summary)
        self.assertIn("[REDACTED]", job.summary)
        self.assertNotIn("persisted-secret", job.summary)
        self.assertNotIn("persisted-secret", log.message)
        self.assertEqual(job.result["error_code"], "agent.execution_failed")
        self.assertRegex(job.result["error_fingerprint"], r"^[0-9a-f]{16}$")
        self.assertNotIn("persisted-secret", job.result["error_summary"])


if __name__ == "__main__":
    unittest.main()
