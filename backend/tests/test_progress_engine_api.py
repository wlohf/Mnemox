"""Regression tests for GET /api/learning/progress-engine.

The endpoint used to crash with NameError (`quiz_records` was never bound)
as soon as one material passed the textbook filter, which made the whole
progress page unusable.
"""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

from sqlalchemy import event
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, _configure_sqlite_connection
from app.models.material import Chapter, Material
from app.models.progress import MaterialProfile
from app.models.question import Question, QuizRecord
from app.models.user import User
from app.routers.learning import get_progress_engine

WEIGHTS = {"w_chapter": 0.4, "w_quiz": 0.25, "w_wrong": 0.2, "w_output": 0.15}


class ProgressEngineApiTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        database = Path(self.tmpdir.name) / "progress.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{database}")
        event.listen(self.engine.sync_engine, "connect", _configure_sqlite_connection)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as session:
            user = User(username="progress-owner", email="progress@example.com", hashed_password="hash", is_active=True)
            other = User(username="progress-other", email="other@example.com", hashed_password="hash", is_active=True)
            session.add_all([user, other])
            await session.commit()
            self.user = User(id=int(user.id), username=user.username, email=user.email, hashed_password="hash", is_active=True)
            self.other_id = int(other.id)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _textbook(self, session, owner_id: int, title: str) -> tuple[Material, Chapter]:
        material = Material(user_id=owner_id, title=title, content="第一章 导论")
        session.add(material)
        await session.flush()
        session.add(MaterialProfile(material_id=int(material.id), is_textbook=True, confidence=0.9, source="manual"))
        chapter = Chapter(material_id=int(material.id), title="第一章", content="导论", order_index=1, mastery_level=60.0)
        session.add(chapter)
        await session.flush()
        return material, chapter

    async def test_textbook_material_with_quiz_records_does_not_crash(self):
        async with self.sessions() as session:
            material, chapter = await self._textbook(session, int(self.user.id), "线性代数")
            q1 = Question(user_id=int(self.user.id), chapter_id=int(chapter.id), question_type="choice", content="Q1")
            q2 = Question(user_id=int(self.user.id), chapter_id=int(chapter.id), question_type="choice", content="Q2")
            session.add_all([q1, q2])
            await session.flush()
            session.add_all([
                QuizRecord(question_id=int(q1.id), user_answer="A", is_correct=True),
                QuizRecord(question_id=int(q2.id), user_answer="B", is_correct=False),
            ])
            await session.flush()

            result = await get_progress_engine(include_non_textbook=False, db=session, current_user=self.user, **WEIGHTS)

        self.assertEqual(result["material_count"], 1)
        item = result["materials"][0]
        self.assertEqual(item["material_id"], int(material.id))
        self.assertEqual(item["practice_correct_rate"], 50.0)
        self.assertEqual(item["chapter_progress"], 60.0)

    async def test_quiz_records_of_other_users_are_ignored(self):
        async with self.sessions() as session:
            _, chapter = await self._textbook(session, int(self.user.id), "概率论")
            _, foreign_chapter = await self._textbook(session, self.other_id, "外部教材")
            mine = Question(user_id=int(self.user.id), chapter_id=int(chapter.id), question_type="choice", content="mine")
            theirs = Question(user_id=self.other_id, chapter_id=int(foreign_chapter.id), question_type="choice", content="theirs")
            session.add_all([mine, theirs])
            await session.flush()
            session.add_all([
                QuizRecord(question_id=int(mine.id), user_answer="A", is_correct=True),
                QuizRecord(question_id=int(theirs.id), user_answer="B", is_correct=False),
            ])
            await session.flush()

            result = await get_progress_engine(include_non_textbook=False, db=session, current_user=self.user, **WEIGHTS)

        self.assertEqual(result["material_count"], 1)
        self.assertEqual(result["materials"][0]["practice_correct_rate"], 100.0)

    async def test_empty_library_returns_zero_progress(self):
        async with self.sessions() as session:
            result = await get_progress_engine(include_non_textbook=True, db=session, current_user=self.user, **WEIGHTS)
        self.assertEqual(result["material_count"], 0)
        self.assertEqual(result["materials"], [])


if __name__ == "__main__":
    unittest.main()
