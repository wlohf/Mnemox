import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.goal import Goal, Task
from app.models.note import Note, NoteLink
from app.models.user import User
from app.services.goal_context_service import build_goal_context
from app.services.learning_event_service import record_learning_event


class GoalContextServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "goal_context.sqlite3"
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

    async def test_goal_context_selects_due_task_and_linked_notes(self):
        user_id = await self._create_user("owner")
        today = date(2026, 6, 23)
        async with self.sessionmaker() as session:
            goal = Goal(user_id=user_id, title="两周提升英语听力", status="active", deadline=today + timedelta(days=7))
            other_goal = Goal(user_id=user_id, title="低优先目标", status="active", deadline=today + timedelta(days=30))
            session.add_all([goal, other_goal])
            await session.flush()
            due_task = Task(goal_id=goal.id, title="每天精听20分钟", status="pending", planned_date=today)
            later_task = Task(goal_id=other_goal.id, title="随手整理资料", status="pending", planned_date=today + timedelta(days=5))
            note = Note(user_id=user_id, title="英语听力复盘", content="听力转折词容易漏掉", note_type="review")
            session.add_all([due_task, later_task, note])
            await session.flush()
            session.add(NoteLink(note_id=note.id, link_type="goal", link_id=goal.id))
            await record_learning_event(
                session,
                user_id,
                "task.created",
                source="test",
                payload={"title": due_task.title},
                goal_id=int(goal.id),
                task_id=int(due_task.id),
            )
            await session.commit()

        async with self.sessionmaker() as session:
            context = await build_goal_context(session, user_id, now=datetime(2026, 6, 23, 9, 0, 0))

        self.assertEqual(context["active_goal"]["title"], "两周提升英语听力")
        self.assertEqual(context["today_focus"]["title"], "每天精听20分钟")
        self.assertEqual(context["today_focus"]["action_id"], "start_today_focus")
        self.assertEqual(context["active_goal"]["progress"]["today_task_count"], 1)
        self.assertEqual(context["supporting_context"]["notes"][0]["title"], "英语听力复盘")
        self.assertTrue(any("今日任务" in item for item in context["evidence"]))

    async def test_no_goals_returns_creation_path(self):
        user_id = await self._create_user("empty")
        async with self.sessionmaker() as session:
            context = await build_goal_context(session, user_id, now=datetime(2026, 6, 23, 9, 0, 0))

        self.assertIsNone(context["active_goal"])
        self.assertEqual(context["today_focus"]["action_id"], "goal_context_create_goal")
        self.assertTrue(context["goal_creation"]["requires_confirmation"])

    async def test_goal_context_is_user_scoped(self):
        owner_id = await self._create_user("owner")
        other_id = await self._create_user("other")
        today = date(2026, 6, 23)
        async with self.sessionmaker() as session:
            owner_goal = Goal(user_id=owner_id, title="Owner goal", status="active")
            other_goal = Goal(user_id=other_id, title="Other goal", status="active")
            session.add_all([owner_goal, other_goal])
            await session.flush()
            session.add_all(
                [
                    Task(goal_id=owner_goal.id, title="Owner task", status="pending", planned_date=today),
                    Task(goal_id=other_goal.id, title="Other task", status="pending", planned_date=today),
                    Note(user_id=other_id, title="Other note", content="should not leak", note_type="review"),
                ]
            )
            await session.commit()

        async with self.sessionmaker() as session:
            context = await build_goal_context(session, owner_id, now=datetime(2026, 6, 23, 9, 0, 0))

        self.assertEqual(context["active_goal"]["title"], "Owner goal")
        self.assertEqual(context["today_focus"]["title"], "Owner task")
        note_titles = {item["title"] for item in context["supporting_context"]["notes"]}
        self.assertNotIn("Other note", note_titles)


if __name__ == "__main__":
    unittest.main()
