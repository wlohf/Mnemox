"""Owner-scoped rows never fall back to user 1 or to another account."""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatConversation, ChatMessage
from app.models.goal import Goal
from app.models.material import Material
from app.models.memory import ConversationSummary
from app.models.user import User


class OwnerScopingTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'owners.db'}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            # User 1 exists so a silent fallback to it would not fail on the FK.
            first = User(username="first", email="first@example.test", hashed_password="hash")
            owner = User(username="owner", email="owner@example.test", hashed_password="hash")
            intruder = User(username="intruder", email="intruder@example.test", hashed_password="hash")
            db.add_all([first, owner, intruder])
            await db.commit()
            self.first, self.owner, self.intruder = int(first.id), int(owner.id), int(intruder.id)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def test_owner_scoped_row_without_user_id_fails_before_insert(self) -> None:
        async with self.sessions() as db:
            db.add(Material(title="orphan", content="text"))
            with self.assertRaisesRegex(ValueError, "Material.user_id is required"):
                await db.flush()

    async def test_reflection_summary_belongs_to_the_conversation_owner(self) -> None:
        from app.services.memory_service import run_conversation_reflection

        class Provider:
            async def chat(self, **_kwargs):
                return json.dumps({
                    "summary": "讨论了贝叶斯定理",
                    "questions_asked": [],
                    "confusions": [],
                    "misconceptions": [],
                    "memory_candidates": [],
                    "review_prompts": [],
                }, ensure_ascii=False)

        async with self.sessions() as db:
            conversation = ChatConversation(user_id=self.owner, title="贝叶斯")
            db.add(conversation)
            await db.flush()
            db.add_all([
                ChatMessage(conversation_id=conversation.id, role="user" if index % 2 == 0 else "assistant",
                            content=f"第 {index} 条消息")
                for index in range(10)
            ])
            await db.commit()
            with patch("app.ai.factory.AIProviderFactory.create_provider", AsyncMock(return_value=Provider())):
                await run_conversation_reflection(int(conversation.id), db, user_id=self.owner)
            await db.commit()
            summary = await db.scalar(
                select(ConversationSummary).where(ConversationSummary.conversation_id == conversation.id)
            )

        self.assertIsNotNone(summary)
        self.assertEqual(summary.user_id, self.owner)

    async def test_auto_goal_creation_ignores_other_users_materials(self) -> None:
        from app.routers.learning import _auto_create_goal_and_tasks

        async with self.sessions() as db:
            material = Material(user_id=self.owner, title="线性代数", content="矩阵")
            db.add(material)
            await db.commit()

            foreign = await _auto_create_goal_and_tasks(int(material.id), db, user_id=self.intruder)
            goals_after_foreign = await db.scalar(select(func.count()).select_from(Goal))
            own_goal_id, _ = await _auto_create_goal_and_tasks(int(material.id), db, user_id=self.owner)
            own_goal = await db.get(Goal, own_goal_id)

        self.assertEqual(foreign, (None, 0))
        self.assertEqual(goals_after_foreign, 0)
        self.assertEqual(own_goal.user_id, self.owner)

    async def test_material_service_reads_and_deletes_only_owned_materials(self) -> None:
        from app.services.material_service import MaterialService

        async with self.sessions() as db:
            material = Material(user_id=self.owner, title="私有资料", content="secret")
            db.add(material)
            await db.commit()
            service = MaterialService(db)

            self.assertIsNone(await service.get_material(int(material.id), user_id=self.intruder))
            self.assertFalse(await service.delete_material(int(material.id), self.intruder))
            self.assertEqual(await service.list_materials(user_id=self.intruder), [])
            self.assertIsNotNone(await db.get(Material, int(material.id)))


if __name__ == "__main__":
    unittest.main()
