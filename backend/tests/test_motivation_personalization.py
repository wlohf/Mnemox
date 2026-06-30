import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.note import Note
from app.models.user import User
from app.routers.motivation import generate_quote


class FakeMotivationProvider:
    def __init__(self, reply: str):
        self.reply = reply
        self.messages = None
        self.system_prompt = None

    async def chat(self, messages, system_prompt=None, temperature=0.7):
        self.messages = messages
        self.system_prompt = system_prompt
        return self.reply


class MotivationPersonalizationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "motivation.sqlite3"
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

    async def _create_note(self, user: User, title: str, content: str) -> None:
        async with self.sessionmaker() as session:
            session.add(Note(user_id=user.id, title=title, content=content, note_type="general"))
            await session.commit()

    async def test_generate_quote_includes_recent_note_context_in_prompt(self):
        user = await self._create_user("motivation_note_user")
        await self._create_note(
            user,
            "读书笔记",
            "坚持从来不是在你想做的时候去做，而是在你不想做的时候仍然去做。",
        )
        provider = FakeMotivationProvider("先把今天的第一步做完。")

        async with self.sessionmaker() as session:
            with patch("app.routers.motivation.AIProviderFactory.create_provider", return_value=provider):
                quote = await generate_quote(db=session, current_user=user)

        self.assertEqual(quote.source_type, "ai")
        self.assertEqual(quote.author, "AI")
        self.assertIn("用户最近笔记摘录", provider.messages[0]["content"])
        self.assertIn("读书笔记", provider.messages[0]["content"])
        self.assertIn("坚持从来不是", provider.messages[0]["content"])

    async def test_generate_quote_falls_back_to_note_based_text_when_ai_unavailable(self):
        user = await self._create_user("motivation_fallback_user")
        await self._create_note(
            user,
            "自我提醒",
            "坚持从来不是在你想做的时候去做，而是在你不想做的时候仍然去做。",
        )

        async with self.sessionmaker() as session:
            with patch("app.routers.motivation.AIProviderFactory.create_provider", side_effect=RuntimeError("provider down")):
                quote = await generate_quote(db=session, current_user=user)

        self.assertEqual(quote.source_type, "ai")
        self.assertEqual(quote.author, "系统")
        self.assertIn("坚持从来不是", quote.content)

    async def test_generate_quote_only_uses_current_users_notes(self):
        owner = await self._create_user("motivation_owner")
        viewer = await self._create_user("motivation_viewer")
        await self._create_note(owner, "别人的笔记", "这是其他用户的私有摘录，不应该出现在当前 prompt。")
        provider = FakeMotivationProvider("先做眼前这一小步。")

        async with self.sessionmaker() as session:
            with patch("app.routers.motivation.AIProviderFactory.create_provider", return_value=provider):
                await generate_quote(db=session, current_user=viewer)

        self.assertNotIn("别人的笔记", provider.messages[0]["content"])
        self.assertNotIn("私有摘录", provider.messages[0]["content"])


if __name__ == "__main__":
    unittest.main()
