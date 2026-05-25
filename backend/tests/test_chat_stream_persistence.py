import sqlite3
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.exc import OperationalError
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatConversation, ChatMessage
from app.models.user import User
from app.routers.chat import ChatRequest, _persist_streamed_chat_turn


class ChatStreamPersistenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "chat_stream.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_conversation(self):
        async with self.sessionmaker() as session:
            user = User(username="chat-user", email="chat@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            conversation = ChatConversation(user_id=user.id, title="新对话")
            session.add(conversation)
            await session.flush()
            user_id = int(user.id)
            conversation_id = int(conversation.id)
            await session.commit()
            return user_id, conversation_id

    async def test_core_messages_persist_even_when_chat_enrichment_fails(self):
        user_id, conversation_id = await self._create_conversation()
        body = ChatRequest(
            message="解释一下梯度下降",
            conversation_id=conversation_id,
            history=[],
        )

        with patch(
            "app.routers.chat.upsert_conversation_summary",
            side_effect=RuntimeError("summary service unavailable"),
        ):
            await _persist_streamed_chat_turn(
                body=body,
                full_reply="梯度下降是一种迭代优化方法。",
                user_id=user_id,
                sessionmaker=self.sessionmaker,
            )

        async with self.sessionmaker() as session:
            conversation = await session.get(ChatConversation, conversation_id)
            self.assertEqual(conversation.title, "解释一下梯度下降")

            result = await session.execute(
                select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.id)
            )
            messages = result.scalars().all()

        self.assertEqual([message.role for message in messages], ["user", "assistant"])
        self.assertEqual(messages[0].content, "解释一下梯度下降")
        self.assertEqual(messages[1].content, "梯度下降是一种迭代优化方法。")

    async def test_persisted_chat_turn_updates_existing_conversation_timestamp(self):
        user_id, conversation_id = await self._create_conversation()
        old_time = datetime.now() - timedelta(days=7)
        async with self.sessionmaker() as session:
            conversation = await session.get(ChatConversation, conversation_id)
            conversation.title = "历史对话"
            conversation.updated_at = old_time
            await session.commit()

        body = ChatRequest(
            message="继续聊这个知识点",
            conversation_id=conversation_id,
            history=[],
        )

        with (
            patch("app.routers.chat.upsert_conversation_summary", AsyncMock()),
            patch("app.routers.chat.upsert_user_memories_from_turn", AsyncMock()),
        ):
            await _persist_streamed_chat_turn(
                body=body,
                full_reply="好的，我们继续。",
                user_id=user_id,
                sessionmaker=self.sessionmaker,
            )

        async with self.sessionmaker() as session:
            conversation = await session.get(ChatConversation, conversation_id)
            result = await session.execute(
                select(ChatMessage).where(ChatMessage.conversation_id == conversation_id).order_by(ChatMessage.id)
            )
            messages = result.scalars().all()

        self.assertGreater(conversation.updated_at, old_time)
        self.assertEqual([message.role for message in messages], ["user", "assistant"])
        self.assertEqual(messages[0].content, "继续聊这个知识点")
        self.assertEqual(messages[1].content, "好的，我们继续。")

    async def test_core_message_persistence_retries_when_sqlite_is_locked(self):
        user_id, conversation_id = await self._create_conversation()
        body = ChatRequest(
            message="hello",
            conversation_id=conversation_id,
            history=[],
        )
        locked_error = OperationalError("INSERT", {}, sqlite3.OperationalError("database is locked"))

        with (
            patch("app.routers.chat._persist_streamed_chat_turn_once", new_callable=AsyncMock) as persist_once,
            patch("app.routers.chat.asyncio.sleep", new_callable=AsyncMock) as sleep_mock,
            patch("app.routers.chat.upsert_conversation_summary", AsyncMock()),
            patch("app.routers.chat.upsert_user_memories_from_turn", AsyncMock()),
        ):
            persist_once.side_effect = [locked_error, None]

            await _persist_streamed_chat_turn(
                body=body,
                full_reply="ok",
                user_id=user_id,
                sessionmaker=self.sessionmaker,
            )

        self.assertEqual(persist_once.await_count, 2)
        sleep_mock.assert_awaited_once_with(0.25)


if __name__ == "__main__":
    unittest.main()
