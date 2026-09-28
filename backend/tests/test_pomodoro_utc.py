"""Run on SQLite by default, or an isolated schema in MNEMOX_TEST_POSTGRES_URL."""
import os
import unittest
import uuid
from datetime import datetime
from types import SimpleNamespace

from sqlalchemy import text, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base
import app.models
from app.models.user import User
from app.models.pomodoro import Pomodoro
from app.routers.pomodoro import batch_create_pomodoros, PomodorosBatchCreate, get_recent_pomodoros


class PomodoroUtcTests(unittest.IsolatedAsyncioTestCase):
    async def test_browser_iso_timestamps_are_normalized_at_database_and_api_boundaries(self):
        url = os.environ.get("MNEMOX_TEST_POSTGRES_URL")
        schema = f"test_pomodoro_{uuid.uuid4().hex}"
        kwargs = {"connect_args": {"server_settings": {"search_path": schema}}} if url else {}
        engine = create_async_engine(url or "sqlite+aiosqlite:///:memory:", **kwargs)
        try:
            async with engine.begin() as conn:
                if url:
                    await conn.execute(text(f'CREATE SCHEMA "{schema}"'))
                await conn.run_sync(Base.metadata.create_all)
            sessions = async_sessionmaker(engine, expire_on_commit=False)
            async with sessions() as db:
                user = User(username="utc", email="utc@example.test", hashed_password="hash")
                db.add(user)
                await db.commit()
                actor = SimpleNamespace(id=user.id)
                result = await batch_create_pomodoros(PomodorosBatchCreate(
                    records=[{"task_name": "focus", "duration": 25}],
                    completed_ats=["2026-09-25T17:00:00+08:00"],
                ), db, actor)
                db.expire_all()
                row = await db.get(Pomodoro, result.ids[0])
                self.assertEqual(row.ended_at, datetime(2026, 9, 25, 9, 0))
                self.assertEqual(row.started_at, datetime(2026, 9, 25, 8, 35))
                response = await get_recent_pomodoros(limit=10, db=db, current_user=actor)
                self.assertEqual(response[0].ended_at, "2026-09-25T09:00:00Z")
                self.assertEqual(response[0].started_at, "2026-09-25T08:35:00Z")
        finally:
            if url:
                async with engine.begin() as conn:
                    await conn.execute(text(f'DROP SCHEMA IF EXISTS "{schema}" CASCADE'))
            await engine.dispose()
