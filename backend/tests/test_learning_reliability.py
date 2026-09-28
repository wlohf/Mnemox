import uuid
import unittest
from datetime import datetime
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy import select, func
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker

from app.database import Base
import app.models
from app.models.user import User
from app.models.material import Material, Chapter
from app.models.goal import Goal, Task
from app.models.question import ReviewSchedule
from app.models.progress import OutputEvaluation
from app.routers.goals import delete_goal
from app.routers.learning import evaluate_output, OutputEvaluateRequest
from app.routers.review import submit_review_answers, ReviewSubmitRequest
from app.routers.chat import chat_send, ChatRequest


class LearningReliabilityTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.db = self.sessions()
        self.user = User(username="test", email="test@example.test", hashed_password="hash")
        self.db.add(self.user)
        await self.db.flush()
        self.material = Material(user_id=self.user.id, title="material")
        self.db.add(self.material)
        await self.db.flush()
        self.chapter = Chapter(material_id=self.material.id, title="chapter", mastery_level=42)
        self.goals = [Goal(user_id=self.user.id, title=f"goal {i}", material_id=self.material.id) for i in range(2)]
        self.db.add_all([self.chapter, *self.goals])
        await self.db.flush()
        self.tasks = [Task(goal_id=goal.id, chapter_id=self.chapter.id, title="task") for goal in self.goals]
        self.review = ReviewSchedule(user_id=self.user.id, item_type="chapter", item_id=self.chapter.id,
            scheduled_date=datetime(2026, 9, 1), repetitions=5, stability=12, is_archived=True)
        self.db.add_all([*self.tasks, self.review])
        await self.db.commit()

    async def asyncTearDown(self):
        await self.db.close()
        await self.engine.dispose()

    async def test_deleting_goal_preserves_shared_review_and_archive_state(self):
        await delete_goal(self.goals[0].id, if_match='"1"', idempotency_key=None, db=self.db, current_user=self.user)
        await self.db.commit()
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(Task)), 1)
        await self.db.refresh(self.review)
        self.assertEqual((self.review.repetitions, self.review.stability, self.review.is_archived), (5, 12, True))

    async def test_output_evaluation_accepts_owned_task_and_persists_real_score(self):
        provider = SimpleNamespace(chat=AsyncMock(return_value='{"score":85,"strengths":["clear"],"gaps":[],"next_actions":[],"verdict":"通过"}'))
        with patch("app.routers.learning.AIProviderFactory.create_provider", new=AsyncMock(return_value=provider)):
            result = await evaluate_output(OutputEvaluateRequest(task_id=self.tasks[0].id, output_text="answer", mark_task_completed=True), self.db, self.user)
        self.assertEqual(result["score"], 85)
        self.assertEqual(self.tasks[0].status, "completed")
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(OutputEvaluation)), 1)

    async def test_evaluation_outages_and_missing_scores_do_not_change_learning_state(self):
        actor = SimpleNamespace(id=self.user.id)
        for reply in (ConnectionError("provider unavailable"), "{}", "not json", '{"score":120,"feedback":"invalid"}'):
            provider = SimpleNamespace(chat=AsyncMock(side_effect=reply) if isinstance(reply, Exception) else AsyncMock(return_value=reply))
            with patch("app.ai.factory.AIProviderFactory.create_provider", new=AsyncMock(return_value=provider)):
                with self.assertRaises(HTTPException) as error:
                    await submit_review_answers(self.review.id, ReviewSubmitRequest(attempt_id=uuid.uuid4(), answers=[{"question":"q", "answer":"I do not know"}]), self.db, actor)
                self.assertEqual(error.exception.status_code, 503)
                await self.db.refresh(self.user)
                await self.db.refresh(self.tasks[0])
                await self.db.refresh(self.review)
                await self.db.refresh(self.chapter)
                with self.assertRaises(HTTPException):
                    await evaluate_output(OutputEvaluateRequest(task_id=self.tasks[0].id, output_text="long answer " * 300, mark_task_completed=True), self.db, self.user)
        self.assertEqual((self.review.repetitions, self.review.stability, self.chapter.mastery_level), (5, 12, 42))
        self.assertEqual(self.tasks[0].status, "pending")
        self.assertEqual(await self.db.scalar(select(func.count()).select_from(OutputEvaluation)), 0)

    async def test_web_search_uses_scalar_user_id_after_real_orm_rollback(self):
        async def stream(**kwargs):
            yield "answer"
        provider = SimpleNamespace(chat_stream=stream, supports_web_search=lambda: False)
        search = AsyncMock(return_value=("context", []))
        uid = self.user.id
        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", new=AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", new=AsyncMock(return_value=[])),
            patch("app.routers.chat.AIProviderFactory.create_provider", new=AsyncMock(return_value=provider)),
            patch("app.routers.chat.get_search_settings_dict", new=AsyncMock(return_value={})),
            patch("app.routers.chat._build_external_web_search_prompt", new=search),
            patch("app.routers.chat.detect_progress_feedback", new=AsyncMock(return_value=None)),
            patch("app.routers.chat._persist_streamed_chat_turn", new=AsyncMock()),
        ):
            response = await chat_send(ChatRequest(message="search", web_search_enabled=True, web_search_mode="app_search"), self.db, self.user)
            chunks = [chunk async for chunk in response.body_iterator]
        search.assert_awaited_once()
        self.assertEqual(search.await_args.kwargs["user_id"], uid)
        self.assertTrue(any("answer" in chunk for chunk in chunks))
