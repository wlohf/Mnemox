import tempfile
import unittest
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.memory import UserMemory
from app.models.user import User
from app.services.agent_memory_learning_service import CHECKPOINT_KEY, run_agent_memory_learning
from app.services.learning_event_service import record_learning_event


class AgentMemoryLearningServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "agent_memory_learning.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> int:
        async with self.sessionmaker() as session:
            user = User(username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return user_id

    async def test_learning_stages_subjective_candidates_auto_confirms_aggregates_and_updates_checkpoint(self):
        user_id = await self._create_user("owner")
        other_id = await self._create_user("other")

        async with self.sessionmaker() as session:
            await record_learning_event(
                session,
                user_id,
                "pomodoro.completed",
                source="test",
                payload={"title": "专注学习"},
                duration=1500,
            )
            note_event = await record_learning_event(
                session,
                user_id,
                "note.created",
                source="test",
                payload={"title": "线性代数错题总结", "content": "raw note body should not be copied"},
                note_id=12,
            )
            await record_learning_event(
                session,
                other_id,
                "note.created",
                source="test",
                payload={"title": "其他用户笔记"},
                note_id=99,
            )
            await session.commit()

        async with self.sessionmaker() as session:
            result = await run_agent_memory_learning(session, user_id)
            await session.commit()

        self.assertEqual(result["processed_event_count"], 2)
        self.assertGreaterEqual(result["auto_confirmed_count"], 1)
        self.assertEqual(result["staged_count"], 1)
        self.assertEqual(result["checkpoint"]["last_event_id"], note_event["id"])

        async with self.sessionmaker() as session:
            rows = (
                await session.execute(
                    select(UserMemory).where(UserMemory.user_id == user_id).order_by(UserMemory.memory_key)
                )
            ).scalars().all()
            other_rows = (
                await session.execute(select(UserMemory).where(UserMemory.user_id == other_id))
            ).scalars().all()

        staged = [row for row in rows if row.review_status == "staged"]
        confirmed = [row for row in rows if row.review_status == "confirmed" and row.status == "active"]
        self.assertEqual(len(staged), 1)
        self.assertEqual(staged[0].status, "staged")
        self.assertIn("线性代数错题总结", staged[0].memory_value)
        self.assertNotIn("raw note body", staged[0].memory_value)
        self.assertTrue(any(row.memory_key == "agent_recent_learning_activity" for row in confirmed))
        self.assertTrue(any(row.memory_key == "agent_core_profile" for row in confirmed))
        self.assertEqual(other_rows, [])

        async with self.sessionmaker() as session:
            second = await run_agent_memory_learning(session, user_id)
            await session.commit()
        self.assertEqual(second["processed_event_count"], 0)
        self.assertEqual(second["auto_confirmed_count"], 0)
        self.assertEqual(second["staged_count"], 0)

    async def test_learning_with_no_events_creates_hidden_locked_checkpoint(self):
        user_id = await self._create_user("owner")
        async with self.sessionmaker() as session:
            result = await run_agent_memory_learning(session, user_id)
            await session.commit()

        self.assertEqual(result["processed_event_count"], 0)
        async with self.sessionmaker() as session:
            row = (
                await session.execute(
                    select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.memory_key == CHECKPOINT_KEY)
                )
            ).scalar_one()
        self.assertEqual(row.status, "ignored")
        self.assertEqual(row.is_locked, 1)
        self.assertEqual(row.category, "system")


if __name__ == "__main__":
    unittest.main()
