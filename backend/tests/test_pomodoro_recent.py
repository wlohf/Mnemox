import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.pomodoro import Pomodoro
from app.models.user import User
from app.routers.pomodoro import get_recent_pomodoros


class PomodoroRecentTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "pomodoro_recent.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def test_recent_allows_restoring_large_local_history(self):
        async with self.sessionmaker() as session:
            user = User(username="owner", email="owner@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            user_id = int(user.id)

            base_time = datetime(2026, 5, 23, 8, 0, 0)
            for idx in range(75):
                started_at = base_time + timedelta(minutes=idx * 30)
                session.add(
                    Pomodoro(
                        user_id=user_id,
                        task_name=f"Task {idx}",
                        started_at=started_at,
                        ended_at=started_at + timedelta(minutes=25),
                        duration=25,
                        completed=True,
                    )
                )
            await session.commit()

        current_user = User(
            id=user_id,
            username="owner",
            email="owner@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            records = await get_recent_pomodoros(limit=500, db=session, current_user=current_user)

        self.assertEqual(len(records), 75)
        self.assertEqual(records[0].task_name, "Task 74")


if __name__ == "__main__":
    unittest.main()
