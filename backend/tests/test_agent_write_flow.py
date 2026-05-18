import tempfile
import unittest
from datetime import date
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatConversation, ChatMessage
from app.models.daily_plan import DailyPlan
from app.models.goal import Goal, Task
from app.models.note import Note
from app.models.user import User
from app.routers.conversations import ConversationMessageCreate, append_conversation_messages
from app.services.agent_service import _heuristic_write_intent, build_agent_write_draft, execute_agent_write_draft


class AgentWriteFlowTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "agent_write.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self) -> int:
        async with self.sessionmaker() as session:
            user = User(username="tester", email="tester@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return user_id

    def test_heuristic_detects_note_and_split_tasks(self):
        note = _heuristic_write_intent("记一个灵感到笔记里：把这个想法记下来", date(2026, 5, 2))
        self.assertEqual(note["intent"], "create_note")
        self.assertIn("灵感", note["draft"]["tags"])

        tasks = _heuristic_write_intent("把英语阅读 2 篇精读、2 篇精听拆成任务", date(2026, 5, 2))
        self.assertEqual(tasks["intent"], "create_goal_tasks")
        self.assertEqual(tasks["draft"]["goal_title"], "英语学习计划")
        self.assertEqual(len(tasks["draft"]["tasks"]), 2)
        self.assertTrue(all("拆成任务" not in item["title"] for item in tasks["draft"]["tasks"]))

    def test_heuristic_detects_daily_plan_and_classified_note(self):
        plan = _heuristic_write_intent("今天的任务是 背单词，复习数学错题", date(2026, 5, 2))
        self.assertEqual(plan["intent"], "add_daily_plan_items")
        self.assertEqual(plan["draft"]["date"], "2026-05-02")
        self.assertEqual([item["title"] for item in plan["draft"]["items"]], ["背单词", "复习数学错题"])

        note = _heuristic_write_intent("临时有个想法：用费曼法复盘错题", date(2026, 5, 2))
        self.assertEqual(note["intent"], "create_note")
        self.assertIn(note["draft"]["note_type"], {"idea", "method"})
        self.assertTrue({"灵感", "学习方法"}.intersection(set(note["draft"]["tags"])))

    def test_heuristic_handles_more_natural_daily_plan_phrases(self):
        plan = _heuristic_write_intent("帮我安排到今天：刷两套真题，然后总结错题", date(2026, 5, 2))
        self.assertEqual(plan["intent"], "add_daily_plan_items")
        titles = [item["title"] for item in plan["draft"]["items"]]
        self.assertIn("刷两套真题", titles)
        self.assertIn("然后总结错题", titles)
        self.assertNotIn("安排到今天：刷两套真题", titles)

        tomorrow = _heuristic_write_intent("明天的计划是 复习英语阅读", date(2026, 5, 2))
        self.assertEqual(tomorrow["draft"]["date"], "2026-05-03")
        self.assertEqual(tomorrow["draft"]["items"][0]["planned_date"], "2026-05-03")

    async def test_daily_plan_items_are_appended_and_deduplicated(self):
        user_id = await self._create_user()
        today = date.today().isoformat()
        async with self.sessionmaker() as session:
            session.add(DailyPlan(user_id=user_id, date=today, content=f"# {today} 学习计划\n- [ ] 📝 背单词"))
            await session.commit()

        async with self.sessionmaker() as session:
            draft = await build_agent_write_draft(session, user_id, "今天的任务是 背单词，复习数学错题")
        self.assertEqual(draft["intent"], "add_daily_plan_items")
        self.assertTrue(draft["draft"].get("existing_plan_id"))
        self.assertTrue(draft["draft"]["items"][0].get("duplicate"))
        self.assertFalse(draft["draft"]["items"][1].get("duplicate", False))

        async with self.sessionmaker() as session:
            result = await execute_agent_write_draft(session, user_id, draft["intent"], draft["draft"])
            await session.commit()
        self.assertEqual(result["status"], "created")
        self.assertEqual(len(result["created"]["items"]), 1)
        self.assertEqual(len(result["created"]["skipped_items"]), 1)

        async with self.sessionmaker() as session:
            row = (await session.execute(select(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.date == today))).scalar_one()
            self.assertIn("背单词", row.content)
            self.assertIn("复习数学错题", row.content)
            self.assertEqual(row.content.count("背单词"), 1)

    async def test_duplicate_note_is_skipped(self):
        user_id = await self._create_user()
        async with self.sessionmaker() as session:
            session.add(
                Note(
                    user_id=user_id,
                    title="把这个想法记下来",
                    content="把这个想法记下来",
                    note_type="general",
                )
            )
            await session.commit()

        async with self.sessionmaker() as session:
            draft = await build_agent_write_draft(session, user_id, "记一个灵感到笔记里：把这个想法记下来")
        self.assertEqual(draft["intent"], "create_note")
        self.assertIsNotNone(draft["draft"].get("duplicate_note_id"))

        async with self.sessionmaker() as session:
            result = await execute_agent_write_draft(session, user_id, draft["intent"], draft["draft"])
            await session.commit()

        self.assertEqual(result["status"], "skipped_duplicate")
        self.assertIn("已存在笔记", result["message"])

    async def test_duplicate_tasks_are_skipped(self):
        user_id = await self._create_user()
        today = date.today()
        goal_id = None
        async with self.sessionmaker() as session:
            goal = Goal(user_id=user_id, title="英语学习计划", description="旧计划", status="active")
            session.add(goal)
            await session.flush()
            goal_id = goal.id
            session.add(
                Task(
                    goal_id=goal.id,
                    title="英语阅读 2 篇精读",
                    description="旧任务",
                    task_type="learn",
                    planned_date=today,
                    status="pending",
                )
            )
            session.add(
                Task(
                    goal_id=goal.id,
                    title="2 篇精听",
                    description="旧任务",
                    task_type="learn",
                    planned_date=today,
                    status="pending",
                )
            )
            await session.commit()

        async with self.sessionmaker() as session:
            draft = await build_agent_write_draft(session, user_id, "把英语阅读 2 篇精读、2 篇精听拆成任务")
        self.assertEqual(draft["intent"], "create_goal_tasks")
        self.assertEqual(draft["draft"].get("existing_goal_id"), goal_id)
        self.assertTrue(all(item.get("duplicate") for item in draft["draft"]["tasks"]))

        async with self.sessionmaker() as session:
            result = await execute_agent_write_draft(session, user_id, draft["intent"], draft["draft"])
            await session.commit()

        self.assertEqual(result["status"], "skipped_duplicate")
        self.assertEqual(result["created"]["tasks"], [])
        self.assertEqual(len(result["created"]["skipped_tasks"]), 2)

    async def test_append_conversation_messages_persists_agent_confirmation(self):
        user_id = await self._create_user()
        async with self.sessionmaker() as session:
            conv = ChatConversation(user_id=user_id, title="新对话")
            session.add(conv)
            await session.flush()
            conversation_id = int(conv.id)

            await append_conversation_messages(
                conversation_id,
                [
                    ConversationMessageCreate(role="user", content="记一个灵感到笔记里：把这个想法记下来"),
                    ConversationMessageCreate(role="assistant", content="已创建笔记：把这个想法记下来"),
                ],
                session,
                User(id=user_id, username="tester", email="tester@example.com", hashed_password="hash", is_active=True),
            )
            await session.commit()

        async with self.sessionmaker() as session:
            conv = await session.get(ChatConversation, conversation_id)
            self.assertEqual(conv.title, "记一个灵感到笔记里：把这个想法记下来")

            result = await session.execute(
                select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.id)
            )
            messages = result.scalars().all()
            self.assertEqual([m.role for m in messages], ["user", "assistant"])
            self.assertEqual(messages[1].content, "已创建笔记：把这个想法记下来")


if __name__ == "__main__":
    unittest.main()
