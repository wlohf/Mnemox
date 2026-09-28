import asyncio
import tempfile
import unittest
import uuid
import json
from datetime import datetime
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import BackgroundTasks, HTTPException
from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base, _configure_sqlite_connection
import app.models
from app.models.user import User
from app.models.material import Material, Chapter
from app.models.question import Question, QuizRecord, WrongQuestion, ReviewSchedule
from app.models.pomodoro import Pomodoro
from app.models.goal import Goal, Task
from app.models.note import Note
from app.models.learning_event import LearningEvent
from app.routers.pomodoro import (PomodoroCreate, PomodoroUpdate, PomodorosBatchCreate,
                                 start_pomodoro, complete_pomodoro, batch_create_pomodoros)
from app.services.material_service import MaterialService
from scripts.repair_pomodoro_times import make_plan, apply_plan, convert
from app.services.review_schedule_identity import ensure_review_schedule
from app.routers.review import ReviewCompleteRequest, complete_review_task


class RemainingReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.tmp.name}/test.db")
        event.listen(self.engine.sync_engine, "connect", _configure_sqlite_connection)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            user = User(username="owner", email="owner@test.invalid", hashed_password="hash")
            db.add(user)
            await db.commit()
            self.actor = SimpleNamespace(id=user.id)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_parallel_start_and_lost_response_batch_retry_have_one_identity_and_outcome(self):
        body = PomodoroCreate(task_name="focus", duration=25, client_record_id="one-focus",
                              started_at=datetime(2026, 9, 25, 9))
        async def start():
            async with self.sessions() as db:
                result = await start_pomodoro(body, db, self.actor)
                await db.commit()
                return result.id
        ids = await asyncio.gather(start(), start())
        self.assertEqual(ids[0], ids[1])
        batch = PomodorosBatchCreate(records=[dict(task_name="focus", duration=5,
            client_record_id="one-focus", completed=False, stop_reason="distracted")],
            completed_ats=["2026-09-25T17:05:00+08:00"])
        async def sync():
            async with self.sessions() as db:
                response = await batch_create_pomodoros(batch, db, self.actor)
                await db.commit()
                return response.ids
        self.assertEqual(await asyncio.gather(sync(), sync()), [ids[:1], ids[:1]])
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(Pomodoro)), 1)
            row = await db.get(Pomodoro, ids[0])
            self.assertFalse(row.completed)
            self.assertEqual((row.stop_reason, row.duration), ("distracted", 5))
            self.assertEqual(await db.scalar(select(func.count()).select_from(LearningEvent)), 2)
            with self.assertRaises(HTTPException) as error:
                await complete_pomodoro(row.id, PomodoroUpdate(completed=True), BackgroundTasks(), db, self.actor)
            self.assertEqual(error.exception.status_code, 409)

    async def test_batch_invalid_task_rolls_back_whole_batch(self):
        async with self.sessions() as db:
            with self.assertRaises(HTTPException):
                await batch_create_pomodoros(PomodorosBatchCreate(records=[
                    dict(task_name="valid", duration=5, client_record_id="first"),
                    dict(task_name="invalid", duration=5, task_id=999, client_record_id="second"),
                ], completed_ats=["2026-09-25T09:00:00Z"] * 2), db, self.actor)
            await db.rollback()
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(Pomodoro)), 0)
            self.assertEqual(await db.scalar(select(func.count()).select_from(LearningEvent)), 0)

    async def test_historical_time_plan_is_explicit_repeatable_and_snapshot_checked(self):
        async with self.sessions() as db:
            rows = [Pomodoro(user_id=self.actor.id, task_name="legacy", duration=5,
                started_at=datetime(2026, 9, 25, 17), ended_at=datetime(2026, 9, 25, 17, 5),
                time_basis="legacy", completed=True),
                Pomodoro(user_id=self.actor.id, task_name="mixed", duration=5,
                started_at=datetime(2026, 9, 25, 17), ended_at=datetime(2026, 9, 25, 9, 5),
                time_basis="mixed", completed=True)]
            db.add_all(rows)
            await db.commit()
            plan = await make_plan(db, [r.id for r in rows], "Asia/Shanghai")
            self.assertEqual(rows[0].started_at.hour, 17)
            self.assertEqual(await apply_plan(db, plan), 2)
            await db.commit()
            self.assertEqual(await apply_plan(db, plan), 0)
            for row in rows:
                self.assertEqual((row.started_at.hour, row.ended_at.hour), (9, 9))
            with self.assertRaises(ValueError):
                convert(datetime(2026, 11, 1, 1, 30), "America/New_York")

    async def test_material_deletion_with_quiz_fk_preserves_notes_and_other_goal(self):
        async with self.sessions() as db:
            material = Material(user_id=self.actor.id, title="remove")
            other = Material(user_id=self.actor.id, title="retain")
            db.add_all([material, other])
            await db.flush()
            chapter = Chapter(material_id=material.id, title="chapter")
            goal = Goal(user_id=self.actor.id, material_id=material.id, title="linked")
            keep_goal = Goal(user_id=self.actor.id, material_id=other.id, title="independent")
            db.add_all([chapter, goal, keep_goal])
            await db.flush()
            task = Task(goal_id=goal.id, chapter_id=chapter.id, title="linked task")
            keep_task = Task(goal_id=keep_goal.id, chapter_id=chapter.id, title="retain task")
            question = Question(user_id=self.actor.id, chapter_id=chapter.id, content="question")
            note = Note(user_id=self.actor.id, material_id=material.id, chapter_id=chapter.id, content="retain note")
            db.add_all([task, keep_task, question, note])
            await db.flush()
            wrong = WrongQuestion(user_id=self.actor.id, question_id=question.id)
            db.add(wrong)
            await db.flush()
            db.add_all([QuizRecord(question_id=question.id, user_answer="answer"),
                ReviewSchedule(user_id=self.actor.id, item_type="question", item_id=wrong.id),
                ReviewSchedule(user_id=self.actor.id, item_type="chapter", item_id=chapter.id),
                Pomodoro(user_id=self.actor.id, chapter_id=chapter.id, task_id=task.id, duration=5)])
            ids = (material.id, note.id, keep_task.id, other.id)
            await db.commit()
        async with self.sessions() as db:
            service = MaterialService.__new__(MaterialService)
            service.db = db
            service.projections = SimpleNamespace(prepare_forget=AsyncMock(), forget=AsyncMock(return_value={"status":"deleted"}))
            with patch("app.services.material_service.settings.KNOWLEDGE_V2_ENABLED", False):
                self.assertTrue(await service.delete_material(ids[0], self.actor.id))
        async with self.sessions() as db:
            for model in (Question, WrongQuestion, QuizRecord, ReviewSchedule):
                self.assertEqual(await db.scalar(select(func.count()).select_from(model)), 0)
            note = await db.get(Note, ids[1])
            self.assertEqual(note.content, "retain note")
            self.assertIsNone(note.material_id)
            self.assertIsNone((await db.get(Task, ids[2])).chapter_id)
            self.assertIsNotNone(await db.get(Material, ids[3]))
            timer = await db.scalar(select(Pomodoro))
            self.assertEqual(timer.duration, 5)
            self.assertIsNone(timer.task_id)

    async def test_concurrent_schedule_creation_preserves_archive_and_fsrs_state(self):
        async def ensure():
            async with self.sessions() as db:
                row, created = await ensure_review_schedule(db, user_id=self.actor.id,
                    item_type="chapter", item_id=123, repetitions=0, stability=1, status="pending")
                await db.commit()
                return row.id, created
        results = await asyncio.gather(ensure(), ensure())
        self.assertEqual(results[0][0], results[1][0])
        self.assertEqual(sum(int(created) for _, created in results), 1)
        async with self.sessions() as db:
            row = await db.get(ReviewSchedule, results[0][0])
            row.repetitions, row.stability, row.is_archived = 7, 25, True
            await db.commit()
        await ensure()
        async with self.sessions() as db:
            row = await db.get(ReviewSchedule, results[0][0])
            self.assertEqual((row.repetitions, row.stability, row.is_archived), (7, 25, True))

    async def test_retried_review_updates_mastery_fsrs_and_events_only_once(self):
        async with self.sessions() as db:
            material = Material(user_id=self.actor.id, title="review")
            db.add(material)
            await db.flush()
            chapter = Chapter(material_id=material.id, title="chapter", mastery_level=0)
            db.add(chapter)
            await db.flush()
            schedule, _ = await ensure_review_schedule(db, user_id=self.actor.id, item_type="chapter",
                item_id=chapter.id, scheduled_date=datetime(2026, 9, 1), repetitions=0)
            sid, cid = schedule.id, chapter.id
            await db.commit()
        body = ReviewCompleteRequest(attempt_id=uuid.uuid4(), quality=5)
        async def submit():
            async with self.sessions() as db:
                result = await complete_review_task(sid, body, db, self.actor)
                await db.commit()
                return json.loads(result.body) if hasattr(result, "body") else result
        results = await asyncio.gather(submit(), submit())
        self.assertEqual(results[0], results[1])
        async with self.sessions() as db:
            self.assertEqual((await db.get(Chapter, cid)).mastery_level, 14)
            self.assertEqual((await db.get(ReviewSchedule, sid)).repetitions, 1)
            self.assertEqual(await db.scalar(select(func.count()).select_from(LearningEvent)
                .where(LearningEvent.event_type == "review.completed")), 1)
            with self.assertRaises(HTTPException) as error:
                await complete_review_task(sid, body.model_copy(update={"quality": 0}), db, self.actor)
            self.assertEqual(error.exception.status_code, 409)

    async def test_offline_anki_review_retry_and_stale_device_are_distinct(self):
        from app.models.anki import AnkiCard
        from app.routers.anki import AnkiCardReview, review_card
        from app.utils.utc import utc_now_db
        async with self.sessions() as db:
            card = AnkiCard(user_id=self.actor.id, front="front", back="back")
            db.add(card)
            await db.flush()
            card_id = card.id
            await db.commit()
        body = AnkiCardReview(attempt_id=uuid.uuid4(), quality=4, expected_version=1, reviewed_at=utc_now_db())
        async def submit(payload):
            async with self.sessions() as db:
                result = await review_card(card_id, payload, db, self.actor)
                await db.commit()
                return json.loads(result.body) if hasattr(result, "body") else result
        responses = await asyncio.gather(submit(body), submit(body))
        self.assertEqual(responses[0], responses[1])
        self.assertEqual(responses[0]["sync_version"], 2)
        with self.assertRaises(HTTPException) as error:
            await submit(body.model_copy(update={"attempt_id": uuid.uuid4()}))
        self.assertEqual(error.exception.status_code, 409)
        async with self.sessions() as db:
            self.assertEqual((await db.get(AnkiCard, card_id)).repetitions, 1)
            self.assertEqual(await db.scalar(select(func.count()).select_from(LearningEvent)
                .where(LearningEvent.event_type == "review.completed")), 1)

    async def test_card_cursor_reads_every_row_when_earlier_rows_are_deleted(self):
        from app.models.anki import AnkiCard
        from app.routers.anki import list_cards
        async with self.sessions() as db:
            db.add_all(AnkiCard(user_id=self.actor.id, front=str(i), back="back") for i in range(205))
            await db.commit()
            first = await list_cards("all", 200, db, self.actor, after_id=0)
            await db.delete(await db.get(AnkiCard, first[0]["id"]))
            await db.commit()
            second = await list_cards("all", 200, db, self.actor, after_id=first[-1]["id"])
            self.assertEqual(len(first) + len(second), 205)
            self.assertEqual(second[0]["front"], "200")
