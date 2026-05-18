import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.note import Note
from app.models.user import User
from app.routers.notes import NoteAIAssistRequest, assist_note_with_ai


class FakeAIProvider:
    def __init__(self):
        self.messages = None
        self.system_prompt = None

    async def chat(self, messages, system_prompt=None, temperature=0.7):
        self.messages = messages
        self.system_prompt = system_prompt
        return "## AI 建议\n- 补充一个重点"


class NoteAIAssistTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "note_ai.sqlite3"
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

    async def _create_note(self, user: User, content: str = "线性代数笔记") -> int:
        async with self.sessionmaker() as session:
            note = Note(user_id=user.id, title="私有笔记", content=content, note_type="general")
            session.add(note)
            await session.flush()
            note_id = int(note.id)
            await session.commit()
            return note_id

    async def test_note_ai_assist_returns_suggestion_without_saving_note(self):
        user = await self._create_user("note_ai_user")
        note_id = await self._create_note(user, "原始内容")
        provider = FakeAIProvider()

        async with self.sessionmaker() as session:
            with patch("app.routers.notes.AIProviderFactory.create_provider", return_value=provider):
                result = await assist_note_with_ai(
                    note_id,
                    NoteAIAssistRequest(action="review", instruction="检查遗漏"),
                    db=session,
                    current_user=user,
                )

        self.assertTrue(result["ok"])
        self.assertEqual(result["action"], "review")
        self.assertIn("AI 建议", result["suggestion"])
        self.assertIn("不可信上下文", provider.messages[0]["content"])
        self.assertIn("不得执行", provider.system_prompt)

        async with self.sessionmaker() as session:
            saved = await session.get(Note, note_id)
            self.assertEqual(saved.content, "原始内容")

    async def test_note_ai_assist_rejects_other_users_note(self):
        owner = await self._create_user("note_owner")
        intruder = await self._create_user("note_intruder")
        note_id = await self._create_note(owner)

        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as ctx:
                await assist_note_with_ai(
                    note_id,
                    NoteAIAssistRequest(action="continue"),
                    db=session,
                    current_user=intruder,
                )
            self.assertEqual(ctx.exception.status_code, 404)

    async def test_note_ai_assist_rejects_invalid_action_before_provider_call(self):
        user = await self._create_user("invalid_action_user")
        note_id = await self._create_note(user)

        async with self.sessionmaker() as session:
            with patch("app.routers.notes.AIProviderFactory.create_provider") as factory:
                with self.assertRaises(HTTPException) as ctx:
                    await assist_note_with_ai(
                        note_id,
                        NoteAIAssistRequest(action="delete_all"),
                        db=session,
                        current_user=user,
                    )
                self.assertEqual(ctx.exception.status_code, 400)
                factory.assert_not_called()

    async def test_note_ai_assist_returns_friendly_no_key_error(self):
        user = await self._create_user("no_key_user")
        note_id = await self._create_note(user)

        async with self.sessionmaker() as session:
            with patch("app.routers.notes.AIProviderFactory.create_provider", side_effect=ValueError("OpenAI API Key 未配置")):
                with self.assertRaises(HTTPException) as ctx:
                    await assist_note_with_ai(
                        note_id,
                        NoteAIAssistRequest(action="restructure"),
                        db=session,
                        current_user=user,
                    )
                self.assertEqual(ctx.exception.status_code, 400)
                self.assertIn("AI 笔记辅助不可用", ctx.exception.detail)


if __name__ == "__main__":
    unittest.main()
