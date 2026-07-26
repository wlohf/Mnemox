import tempfile
import unittest
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatConversation, ChatMessage
from app.models.user import User
from app.routers.conversations import get_conversation


class ConversationDetailTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "conversation_detail.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> User:
        async with self.sessionmaker() as session:
            user = User(
                username=username,
                email=f"{username}@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return User(
                id=user_id,
                username=username,
                email=f"{username}@example.com",
                hashed_password="hash",
                is_active=True,
            )

    async def test_get_conversation_tolerates_invalid_image_data_json(self):
        owner = await self._create_user("detail_owner")
        async with self.sessionmaker() as session:
            conv = ChatConversation(user_id=owner.id, title="带图对话")
            session.add(conv)
            await session.flush()
            conv_id = int(conv.id)
            session.add(
                ChatMessage(
                    conversation_id=conv_id,
                    role="user",
                    content="看这张图",
                    image_data="not-a-json-array",
                )
            )
            session.add(
                ChatMessage(
                    conversation_id=conv_id,
                    role="assistant",
                    content="我看到了",
                    image_data='["data:image/png;base64,abc"]',
                )
            )
            await session.commit()

        async with self.sessionmaker() as session:
            detail = await get_conversation(
                conversation_id=conv_id,
                limit=100,
                offset=0,
                db=session,
                current_user=owner,
            )

        self.assertEqual(detail["id"], conv_id)
        self.assertEqual(len(detail["messages"]), 2)
        self.assertIsNone(detail["messages"][0]["image_data"])
        self.assertEqual(detail["messages"][1]["image_data"], ["data:image/png;base64,abc"])
        self.assertEqual(detail["total_messages"], 2)


if __name__ == "__main__":
    unittest.main()
