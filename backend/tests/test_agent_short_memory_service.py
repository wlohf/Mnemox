import json
import tempfile
import unittest
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.goal import Goal, Task
from app.models.memory import ConversationSummary
from app.models.user import User
from app.services.agent_short_memory_service import build_short_memory
from app.services.learning_event_service import record_learning_event


class AgentShortMemoryServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "short_memory.sqlite3"
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

    async def test_short_memory_combines_summary_events_goal_and_temporary_preferences(self):
        user_id = await self._create_user("owner")
        async with self.sessionmaker() as session:
            goal = Goal(user_id=user_id, title="英语听力", status="active")
            session.add(goal)
            await session.flush()
            task = Task(goal_id=goal.id, title="精听20分钟", status="pending")
            session.add(task)
            await session.flush()
            session.add(
                ConversationSummary(
                    user_id=user_id,
                    conversation_id=7,
                    summary="用户正在拆解英语听力目标",
                    key_points=json.dumps(["听力", "短任务"], ensure_ascii=False),
                    todo_items=json.dumps(["先定计划"], ensure_ascii=False),
                    message_count=4,
                )
            )
            await record_learning_event(
                session,
                user_id,
                "task.created",
                source="test",
                payload={"title": task.title},
                goal_id=int(goal.id),
                task_id=int(task.id),
            )
            await session.commit()

        async with self.sessionmaker() as session:
            memory = await build_short_memory(
                session,
                user_id,
                conversation_id=7,
                goal_id=goal.id,
                query="先不要创建任务，只讨论方案，短一点",
            )

        self.assertEqual(memory["conversation_summary"]["summary"], "用户正在拆解英语听力目标")
        self.assertEqual(memory["recent_events"][0]["event_type"], "task.created")
        self.assertEqual(memory["active_goal_context"]["active_goal"]["title"], "英语听力")
        self.assertTrue(any("不要执行写入" in item or "不想创建" in item for item in memory["temporary_preferences"]))
        self.assertTrue(any("简短" in item for item in memory["temporary_preferences"]))


if __name__ == "__main__":
    unittest.main()
