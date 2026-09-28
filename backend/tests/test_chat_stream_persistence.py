import sqlite3
import tempfile
import unittest
import asyncio
import json
from contextlib import ExitStack
from types import SimpleNamespace
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
from app.routers.chat import chat_send
from app.services.background_runner import chat_turn_enrichment_runner
from app.services.chat_progress import save_chat_progress
from fastapi import HTTPException


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
            enrichment = await _persist_streamed_chat_turn(
                body=body,
                full_reply="梯度下降是一种迭代优化方法。",
                user_id=user_id,
                sessionmaker=self.sessionmaker,
            )
            await enrichment

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
            enrichment = await _persist_streamed_chat_turn(
                body=body,
                full_reply="好的，我们继续。",
                user_id=user_id,
                sessionmaker=self.sessionmaker,
            )
            await enrichment

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

            enrichment = await _persist_streamed_chat_turn(
                body=body,
                full_reply="ok",
                user_id=user_id,
                sessionmaker=self.sessionmaker,
            )
            await enrichment

        self.assertEqual(persist_once.await_count, 2)
        sleep_mock.assert_awaited_once_with(0.25)

    async def test_partial_reply_is_durable_before_yield_and_survives_cancellation(self):
        user_id, conversation_id = await self._create_conversation()
        body = ChatRequest(message="durable input", conversation_id=conversation_id)
        waiting = asyncio.Event()

        class Provider:
            max_context_tokens = None
            async def chat_stream(self, **kwargs):
                yield "已生成的第一段"
                waiting.set()
                await asyncio.Event().wait()

        with ExitStack() as stack:
            for name, replacement in (
                ("app.database.async_session_maker", self.sessionmaker),
                ("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
                ("app.routers.chat.search_note_context", AsyncMock(return_value=[])),
                ("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
                ("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=Provider())),
            ):
                stack.enter_context(patch(name, replacement))
            async with self.sessionmaker() as db:
                response = await chat_send(body, db, SimpleNamespace(id=user_id))
                first = await anext(response.body_iterator)
                self.assertIn("已生成的第一段", first)
                # This query precedes cancellation: it also covers abrupt process death.
                async with self.sessionmaker() as saved:
                    rows = (await saved.scalars(select(ChatMessage).order_by(ChatMessage.id))).all()
                    self.assertEqual([r.content for r in rows], [body.message, "已生成的第一段"])
                    self.assertEqual(rows[-1].status, "streaming")
                task = asyncio.create_task(anext(response.body_iterator))
                await asyncio.wait_for(waiting.wait(), 2)
                task.cancel()
                with self.assertRaises(asyncio.CancelledError):
                    await task
            async with self.sessionmaker() as db:
                rows = (await db.scalars(select(ChatMessage).order_by(ChatMessage.id))).all()
                self.assertEqual(rows[-1].status, "interrupted")
                # A retry with the same turn cannot run another generation or duplicate rows.
                response = await chat_send(body, db, SimpleNamespace(id=user_id))
                replay = [chunk async for chunk in response.body_iterator]
                self.assertTrue(any("已生成的第一段" in chunk for chunk in replay))
                self.assertFalse(any("[DONE]" in chunk for chunk in replay))
                self.assertEqual(len((await db.scalars(select(ChatMessage))).all()), 2)

    async def test_turn_replay_and_deleted_conversation_never_recreate_history(self):
        user_id, conversation_id = await self._create_conversation()
        body = ChatRequest(message="hello", conversation_id=conversation_id)
        async def save(**kwargs):
            return await save_chat_progress(body=body, user_id=user_id, sessionmaker=self.sessionmaker, **kwargs)
        starts = await asyncio.gather(save(), save())
        self.assertEqual(sum(not row["existed"] for row in starts), 1)
        await save(content="finished", status="completed")
        self.assertEqual((await save(content="stale", status="interrupted"))["content"], "finished")
        changed = body.model_copy(update={"message": "different"})
        with self.assertRaises(HTTPException) as error:
            await save_chat_progress(body=changed, user_id=user_id, sessionmaker=self.sessionmaker)
        self.assertEqual(error.exception.status_code, 409)
        async with self.sessionmaker() as db:
            await db.delete(await db.get(ChatConversation, conversation_id))
            await db.commit()
        with self.assertRaises(HTTPException) as error:
            await save(content="late")
        self.assertEqual(error.exception.status_code, 404)

    async def test_failed_final_checkpoint_never_emits_success(self):
        user_id, conversation_id = await self._create_conversation()
        body = ChatRequest(message="hello", conversation_id=conversation_id)
        class Provider:
            max_context_tokens = None
            async def chat_stream(self, **kwargs):
                yield "partial"
        with (
            patch("app.database.async_session_maker", self.sessionmaker),
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.search_note_context", AsyncMock(return_value=[])),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat.detect_progress_feedback", AsyncMock(return_value=None)),
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=Provider())),
            patch("app.routers.chat._persist_streamed_chat_turn", AsyncMock(side_effect=RuntimeError("disk full"))),
        ):
            async with self.sessionmaker() as db:
                response = await chat_send(body, db, SimpleNamespace(id=user_id))
                events = [chunk async for chunk in response.body_iterator]
            self.assertFalse(any("[DONE]" in event for event in events))
            async with self.sessionmaker() as db:
                assistant = await db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
                self.assertEqual((assistant.content, assistant.status), ("partial", "interrupted"))

    def _patch_stream_dependencies(self, stack: ExitStack, provider) -> None:
        for name, replacement in (
            ("app.database.async_session_maker", self.sessionmaker),
            ("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            ("app.routers.chat.search_note_context", AsyncMock(return_value=[])),
            ("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            ("app.routers.chat.detect_progress_feedback", AsyncMock(return_value=None)),
            ("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=provider)),
        ):
            stack.enter_context(patch(name, replacement))

    async def test_done_does_not_wait_for_enrichment_and_disconnect_cannot_cancel_it(self):
        user_id, conversation_id = await self._create_conversation()
        body = ChatRequest(message="什么是正则化", conversation_id=conversation_id)
        release = asyncio.Event()
        finished = []

        async def slow_enrichment(**kwargs):
            await release.wait()
            finished.append(kwargs["conversation_id"])

        class Provider:
            max_context_tokens = None
            async def chat_stream(self, **kwargs):
                yield "正则化用于抑制过拟合。"

        with ExitStack() as stack:
            self._patch_stream_dependencies(stack, Provider())
            stack.enter_context(patch("app.routers.chat._enrich_streamed_chat_turn", slow_enrichment))
            async with self.sessionmaker() as db:
                response = await chat_send(body, db, SimpleNamespace(id=user_id))
                events = []

                async def read_until_done():
                    async for chunk in response.body_iterator:
                        events.append(chunk)
                        if "[DONE]" in chunk:
                            return

                # [DONE] must arrive while enrichment is still blocked.
                await asyncio.wait_for(read_until_done(), timeout=5)
                # The client leaves right after [DONE].
                await response.body_iterator.aclose()
            self.assertTrue(any("[DONE]" in event for event in events))
            self.assertEqual(finished, [])
            self.assertEqual(chat_turn_enrichment_runner.pending_count, 1)
            release.set()
            await chat_turn_enrichment_runner.drain(timeout=5)

        self.assertEqual(finished, [conversation_id])
        async with self.sessionmaker() as db:
            assistant = await db.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
            self.assertEqual((assistant.content, assistant.status), ("正则化用于抑制过拟合。", "completed"))

    async def test_stream_checkpoints_are_batched_and_reuse_one_request_hash(self):
        user_id, conversation_id = await self._create_conversation()
        body = ChatRequest(message="batch", conversation_id=conversation_id)
        pieces = [f"片段{index};" for index in range(40)]
        checkpoints = []

        class Provider:
            max_context_tokens = None
            async def chat_stream(self, **kwargs):
                for piece in pieces:
                    yield piece

        async def recording_save(**kwargs):
            checkpoints.append(kwargs)
            return await save_chat_progress(**kwargs)

        with ExitStack() as stack:
            self._patch_stream_dependencies(stack, Provider())
            stack.enter_context(patch("app.routers.chat.save_chat_progress", recording_save))
            stack.enter_context(patch("app.routers.chat._enrich_streamed_chat_turn", AsyncMock()))
            async with self.sessionmaker() as db:
                response = await chat_send(body, db, SimpleNamespace(id=user_id))
                events = [chunk async for chunk in response.body_iterator]
            await chat_turn_enrichment_runner.drain(timeout=5)

        payloads = [json.loads(event[len("data: "):]) for event in events if event.startswith("data: {")]
        streamed = "".join(payload["content"] for payload in payloads if "content" in payload)
        self.assertEqual(streamed, "".join(pieces))
        self.assertTrue(any("[DONE]" in event for event in events))
        streaming_calls = [call for call in checkpoints if call.get("status", "streaming") == "streaming"]
        partial_writes = [call for call in streaming_calls if call.get("content") is not None]
        # Forty chunks arriving together: the first is committed alone, the rest batched.
        self.assertLessEqual(len(partial_writes), 3)
        request_hashes = {call.get("request_hash") for call in streaming_calls}
        self.assertEqual(len(request_hashes), 1)
        self.assertIsNotNone(next(iter(request_hashes)))

    async def test_held_text_is_released_when_the_provider_pauses(self):
        user_id, conversation_id = await self._create_conversation()
        body = ChatRequest(message="pause", conversation_id=conversation_id)
        resume = asyncio.Event()

        class Provider:
            max_context_tokens = None
            async def chat_stream(self, **kwargs):
                yield "第一段"
                yield "第二段"
                await resume.wait()  # e.g. a hosted web search between chunks
                yield "第三段"

        with ExitStack() as stack:
            self._patch_stream_dependencies(stack, Provider())
            stack.enter_context(patch("app.routers.chat._PROGRESS_FLUSH_INTERVAL_SECONDS", 0.05))
            stack.enter_context(patch("app.routers.chat._enrich_streamed_chat_turn", AsyncMock()))
            async with self.sessionmaker() as db:
                response = await chat_send(body, db, SimpleNamespace(id=user_id))
                first = await anext(response.body_iterator)
                self.assertIn("第一段", first)
                # The second chunk was held for batching; the flush deadline must
                # commit and release it although the provider produces nothing more.
                second = await asyncio.wait_for(anext(response.body_iterator), timeout=2)
                self.assertIn("第二段", second)
                async with self.sessionmaker() as saved:
                    assistant = await saved.scalar(select(ChatMessage).where(ChatMessage.role == "assistant"))
                    self.assertEqual((assistant.content, assistant.status), ("第一段第二段", "streaming"))
                resume.set()
                rest = [chunk async for chunk in response.body_iterator]
            await chat_turn_enrichment_runner.drain(timeout=5)

        self.assertTrue(any("第三段" in chunk for chunk in rest))
        self.assertTrue(any("[DONE]" in chunk for chunk in rest))

    async def test_intermediate_checkpoints_do_not_touch_the_conversation_row(self):
        user_id, conversation_id = await self._create_conversation()
        body = ChatRequest(message="hello", conversation_id=conversation_id)

        async def save(**kwargs):
            return await save_chat_progress(body=body, user_id=user_id, sessionmaker=self.sessionmaker, **kwargs)

        await save()
        old_time = datetime.now() - timedelta(days=3)
        async with self.sessionmaker() as db:
            conversation = await db.get(ChatConversation, conversation_id)
            conversation.updated_at = old_time
            await db.commit()

        await save(content="partial")
        async with self.sessionmaker() as db:
            self.assertEqual((await db.get(ChatConversation, conversation_id)).updated_at, old_time)

        await save(content="final", status="completed")
        async with self.sessionmaker() as db:
            self.assertGreater((await db.get(ChatConversation, conversation_id)).updated_at, old_time)


if __name__ == "__main__":
    unittest.main()
