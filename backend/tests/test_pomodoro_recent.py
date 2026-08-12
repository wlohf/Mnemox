import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.pomodoro import Pomodoro
from app.models.user import User
from app.routers.pomodoro import (
    PomodoroCreate,
    PomodoroUpdate,
    complete_pomodoro,
    get_recent_pomodoros,
    start_pomodoro,
)


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

    async def test_start_rolls_back_pomodoro_when_event_recording_fails(self):
        async with self.sessionmaker() as session:
            user = User(
                username="atomic-owner",
                email="atomic-owner@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.commit()
            user_id = int(user.id)

        current_user = User(
            id=user_id,
            username="atomic-owner",
            email="atomic-owner@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            with patch(
                "app.routers.pomodoro.EventTracker.track",
                new=AsyncMock(side_effect=RuntimeError("event persistence failed")),
            ):
                with self.assertRaisesRegex(RuntimeError, "event persistence failed"):
                    await start_pomodoro(
                        PomodoroCreate(task_name="Atomic task", duration=25),
                        db=session,
                        current_user=current_user,
                    )
            await session.rollback()

        async with self.sessionmaker() as session:
            count = await session.scalar(
                select(func.count()).select_from(Pomodoro).where(Pomodoro.user_id == user_id)
            )
        self.assertEqual(count, 0)

    async def test_completion_rolls_back_pomodoro_when_event_recording_fails(self):
        async with self.sessionmaker() as session:
            user = User(
                username="atomic-complete-owner",
                email="atomic-complete-owner@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            pomodoro = Pomodoro(
                user_id=int(user.id),
                task_name="Atomic completion",
                started_at=datetime.now(),
                duration=25,
                completed=False,
            )
            session.add(pomodoro)
            await session.commit()
            user_id = int(user.id)
            pomodoro_id = int(pomodoro.id)

        current_user = User(
            id=user_id,
            username="atomic-complete-owner",
            email="atomic-complete-owner@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            with patch(
                "app.routers.pomodoro.EventTracker.track",
                new=AsyncMock(side_effect=RuntimeError("event persistence failed")),
            ):
                with self.assertRaisesRegex(RuntimeError, "event persistence failed"):
                    await complete_pomodoro(
                        pomodoro_id,
                        PomodoroUpdate(completed=True),
                        background_tasks=BackgroundTasks(),
                        db=session,
                        current_user=current_user,
                    )
            await session.rollback()

        async with self.sessionmaker() as session:
            persisted = await session.get(Pomodoro, pomodoro_id)
        self.assertIsNotNone(persisted)
        self.assertFalse(persisted.completed)
        self.assertIsNone(persisted.ended_at)

    async def test_completion_queues_profile_refresh_until_after_the_request(self):
        async with self.sessionmaker() as session:
            user = User(
                username="profile-refresh-owner",
                email="profile-refresh-owner@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            pomodoro = Pomodoro(
                user_id=int(user.id),
                task_name="Profile refresh",
                started_at=datetime.now(),
                duration=25,
                completed=False,
            )
            session.add(pomodoro)
            await session.commit()
            user_id = int(user.id)
            pomodoro_id = int(pomodoro.id)

        current_user = User(
            id=user_id,
            username="profile-refresh-owner",
            email="profile-refresh-owner@example.com",
            hashed_password="hash",
            is_active=True,
        )
        background_tasks = BackgroundTasks()
        async with self.sessionmaker() as session:
            with patch(
                "app.routers.pomodoro._refresh_profile_after_commit",
                new=AsyncMock(),
            ) as refresh:
                await complete_pomodoro(
                    pomodoro_id,
                    PomodoroUpdate(completed=True),
                    background_tasks=background_tasks,
                    db=session,
                    current_user=current_user,
                )
                refresh.assert_not_awaited()
                self.assertEqual(len(background_tasks.tasks), 1)
                await background_tasks()
                refresh.assert_awaited_once_with(user_id)


if __name__ == "__main__":
    unittest.main()
