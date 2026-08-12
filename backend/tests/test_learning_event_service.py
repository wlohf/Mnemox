import tempfile
import unittest
from datetime import datetime
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select
from sqlalchemy.exc import IntegrityError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.learning_event import LearningEvent
from app.models.user import User
from app.services.learning_event_service import list_recent_learning_events, record_learning_event


class LearningEventServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "learning_events.sqlite3"
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

    async def test_record_normalizes_and_dedupes_learning_event(self):
        user_id = await self._create_user("owner")
        async with self.sessionmaker() as session:
            first = await record_learning_event(
                session,
                user_id,
                "note_created",
                source="test",
                payload={"title": "线性代数"},
                note_id=12,
                dedupe_key="same-note",
            )
            second = await record_learning_event(
                session,
                user_id,
                "note.created",
                source="test",
                payload={"title": "线性代数"},
                note_id=12,
                dedupe_key="same-note",
            )
            await session.commit()

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["event_type"], "note.created")
        self.assertEqual(first["event_category"], "study")
        self.assertEqual(first["source"], "test")
        self.assertEqual(first["note_id"], 12)

        async with self.sessionmaker() as session:
            rows = (await session.execute(select(LearningEvent))).scalars().all()
        self.assertEqual(len(rows), 1)

    async def test_recent_events_are_user_scoped_newest_first(self):
        owner_id = await self._create_user("owner")
        other_id = await self._create_user("other")
        async with self.sessionmaker() as session:
            first = await record_learning_event(session, owner_id, "task.completed", source="test", payload={"title": "A"})
            await record_learning_event(session, other_id, "task.completed", source="test", payload={"title": "Other"})
            second = await record_learning_event(session, owner_id, "note.updated", source="test", payload={"title": "B"})
            await session.commit()

        async with self.sessionmaker() as session:
            events = await list_recent_learning_events(session, owner_id)

        self.assertEqual([item["id"] for item in events], [second["id"], first["id"]])
        self.assertEqual({item["user_id"] for item in events}, {owner_id})
        self.assertEqual([item["payload"]["title"] for item in events], ["B", "A"])

    async def test_same_user_type_and_dedupe_key_have_database_uniqueness(self):
        user_id = await self._create_user("dedupe-owner")
        async with self.sessionmaker() as session:
            session.add(
                LearningEvent(
                    user_id=user_id,
                    event_type="note.created",
                    event_category="study",
                    source="test",
                    dedupe_key="same-note",
                    timestamp=datetime.now(),
                )
            )
            await session.commit()

        async with self.sessionmaker() as session:
            session.add(
                LearningEvent(
                    user_id=user_id,
                    event_type="note.created",
                    event_category="study",
                    source="test",
                    dedupe_key="same-note",
                    timestamp=datetime.now(),
                )
            )
            with self.assertRaises(IntegrityError):
                await session.flush()

    async def test_record_returns_existing_event_after_dedupe_insert_race(self):
        user_id = await self._create_user("race-owner")
        async with self.sessionmaker() as session:
            original_flush = session.flush
            raced = False

            async def flush_after_competitor(*args, **kwargs):
                nonlocal raced
                if not raced:
                    raced = True
                    async with self.sessionmaker() as competitor:
                        competitor.add(
                            LearningEvent(
                                user_id=user_id,
                                event_type="note.created",
                                event_category="study",
                                source="competitor",
                                dedupe_key="race-note",
                                timestamp=datetime.now(),
                            )
                        )
                        await competitor.commit()
                return await original_flush(*args, **kwargs)

            with patch.object(session, "flush", new=flush_after_competitor):
                event = await record_learning_event(
                    session,
                    user_id,
                    "note.created",
                    source="test",
                    payload={"title": "Race"},
                    dedupe_key="race-note",
                )
            await session.commit()

        self.assertEqual(event["event_type"], "note.created")
        self.assertEqual(event["dedupe_key"], "race-note")
        async with self.sessionmaker() as session:
            rows = (await session.execute(select(LearningEvent))).scalars().all()
        self.assertEqual(len(rows), 1)


if __name__ == "__main__":
    unittest.main()
