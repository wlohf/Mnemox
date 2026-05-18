import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatConversation
from app.models.daily_plan import DailyPlan
from app.models.ai_settings import AIProviderSetting
from app.models.material import Material
from app.models.note import Note
from app.models.user import User
from app.routers.ai_settings import ProviderCreate, create_provider, list_providers
from app.routers.agent import AgentWriteExecuteRequest, execute_agent_write
from app.routers.conversations import delete_conversation
from app.routers.materials import delete_material, get_material, search_materials
from app.routers.notes import delete_note, get_note
from app.utils.secret_crypto import is_encrypted_secret


class MultiUserIsolationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "multi_user.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> User:
        async with self.sessionmaker() as session:
            user = User(username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return User(id=user_id, username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)

    async def test_note_routes_do_not_expose_other_users_notes(self):
        owner = await self._create_user("owner")
        intruder = await self._create_user("intruder")
        async with self.sessionmaker() as session:
            note = Note(user_id=owner.id, title="私有笔记", content="secret", note_type="general")
            session.add(note)
            await session.flush()
            note_id = int(note.id)
            await session.commit()

        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as ctx:
                await get_note(note_id, db=session, current_user=intruder)
            self.assertEqual(ctx.exception.status_code, 404)

        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as ctx:
                await delete_note(note_id, db=session, current_user=intruder)
            self.assertEqual(ctx.exception.status_code, 404)

        async with self.sessionmaker() as session:
            self.assertIsNotNone(await session.get(Note, note_id))

    async def test_conversation_delete_is_user_scoped(self):
        owner = await self._create_user("conv_owner")
        intruder = await self._create_user("conv_intruder")
        async with self.sessionmaker() as session:
            conv = ChatConversation(user_id=owner.id, title="私有对话")
            session.add(conv)
            await session.flush()
            conv_id = int(conv.id)
            await session.commit()

        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as ctx:
                await delete_conversation(conv_id, db=session, current_user=intruder)
            self.assertEqual(ctx.exception.status_code, 404)

        async with self.sessionmaker() as session:
            self.assertIsNotNone(await session.get(ChatConversation, conv_id))

    async def test_material_routes_do_not_expose_other_users_materials(self):
        owner = await self._create_user("material_owner")
        intruder = await self._create_user("material_intruder")
        async with self.sessionmaker() as session:
            material = Material(
                user_id=owner.id,
                title="私有资料",
                content="secret learning material",
                file_type="md",
                content_status="ready",
            )
            session.add(material)
            await session.flush()
            material_id = int(material.id)
            await session.commit()

        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as ctx:
                await get_material(material_id, db=session, current_user=intruder)
            self.assertEqual(ctx.exception.status_code, 404)

        async with self.sessionmaker() as session:
            with patch("app.routers.materials.settings.RAG_ENABLED", False):
                results = await search_materials("secret", db=session, current_user=intruder)
            self.assertEqual(results, [])

        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as ctx:
                await delete_material(material_id, db=session, current_user=intruder)
            self.assertEqual(ctx.exception.status_code, 404)

        async with self.sessionmaker() as session:
            self.assertIsNotNone(await session.get(Material, material_id))

    async def test_ai_provider_key_is_encrypted_and_user_scoped(self):
        owner = await self._create_user("ai_owner")
        intruder = await self._create_user("ai_intruder")

        async with self.sessionmaker() as session:
            out = await create_provider(
                ProviderCreate(
                    display_name="Private OpenAI",
                    provider_name="private-openai",
                    provider_type="openai",
                    api_key="sk-test-secret",
                    base_url="https://example.test/v1",
                    model="test-model",
                ),
                db=session,
                current_user=owner,
            )
            self.assertNotIn("sk-test-secret", out.api_key_masked)

        async with self.sessionmaker() as session:
            rows = (
                await session.execute(select(AIProviderSetting).where(AIProviderSetting.user_id == owner.id))
            ).scalars().all()
            stored = next(row for row in rows if row.display_name == "Private OpenAI")
            self.assertTrue(is_encrypted_secret(stored.api_key))
            self.assertNotEqual(stored.api_key, "sk-test-secret")

        async with self.sessionmaker() as session:
            intruder_providers = await list_providers(db=session, current_user=intruder)
            self.assertFalse(any(row.display_name == "Private OpenAI" for row in intruder_providers))

    async def test_agent_daily_plan_execute_cannot_modify_other_users_plan(self):
        owner = await self._create_user("plan_owner")
        intruder = await self._create_user("plan_intruder")
        plan_date = "2026-05-02"
        async with self.sessionmaker() as session:
            plan = DailyPlan(user_id=owner.id, date=plan_date, content="# owner\n- [ ] 背单词")
            session.add(plan)
            await session.commit()

        async with self.sessionmaker() as session:
            result = await execute_agent_write(
                AgentWriteExecuteRequest(
                    intent="add_daily_plan_items",
                    draft={"date": plan_date, "items": [{"title": "复习数学错题"}]},
                ),
                db=session,
                current_user=intruder,
            )
            await session.commit()
            self.assertEqual(result["status"], "created")

        async with self.sessionmaker() as session:
            rows = (await session.execute(select(DailyPlan).where(DailyPlan.date == plan_date))).scalars().all()
            self.assertEqual(len(rows), 2)
            owner_plan = next(row for row in rows if row.user_id == owner.id)
            intruder_plan = next(row for row in rows if row.user_id == intruder.id)
            self.assertNotIn("复习数学错题", owner_plan.content)
            self.assertIn("复习数学错题", intruder_plan.content)


if __name__ == "__main__":
    unittest.main()
