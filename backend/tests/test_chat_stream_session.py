import unittest
import json
from unittest.mock import AsyncMock, patch

from app.models.user import User
from app.routers.chat import ChatRequest, chat_send


class _FakeScalarResult:
    def scalar_one_or_none(self):
        return object()


class _FakeDb:
    def __init__(self):
        self.rollback = AsyncMock()

    async def execute(self, *_args, **_kwargs):
        return _FakeScalarResult()


class _FakeProvider:
    def __init__(self):
        self.chat_stream_called = False
        self.web_search_called = False

    def supports_web_search(self):
        return False

    async def chat_stream(self, **_kwargs):
        self.chat_stream_called = True
        yield "ok"


class _FakeWebSearchProvider(_FakeProvider):
    def supports_web_search(self):
        return True

    async def chat_stream_with_web_search(self, **_kwargs):
        self.web_search_called = True
        yield "web"


class ChatStreamSessionTests(unittest.IsolatedAsyncioTestCase):
    async def test_chat_send_releases_request_db_session_before_streaming(self):
        db = _FakeDb()
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(message="hello", conversation_id=1, history=[])

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=_FakeProvider())),
        ):
            response = await chat_send(body, db=db, current_user=current_user)

        self.assertEqual(response.media_type, "text/event-stream")
        db.rollback.assert_awaited_once()

    async def test_chat_send_uses_normal_stream_when_web_search_disabled(self):
        db = _FakeDb()
        provider = _FakeWebSearchProvider()
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(message="hello", conversation_id=1, history=[], web_search_enabled=False)

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat._persist_streamed_chat_turn", AsyncMock()),
            patch("app.routers.chat.detect_progress_feedback", AsyncMock(return_value=None)),
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=provider)),
        ):
            response = await chat_send(body, db=db, current_user=current_user)
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertTrue(provider.chat_stream_called)
        self.assertFalse(provider.web_search_called)
        self.assertTrue(any("ok" in chunk for chunk in chunks))

    async def test_chat_send_uses_web_search_stream_when_enabled_and_supported(self):
        db = _FakeDb()
        provider = _FakeWebSearchProvider()
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(message="search this", conversation_id=1, history=[], web_search_enabled=True)

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat._persist_streamed_chat_turn", AsyncMock()),
            patch("app.routers.chat.detect_progress_feedback", AsyncMock(return_value=None)),
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=provider)),
        ):
            response = await chat_send(body, db=db, current_user=current_user)
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertFalse(provider.chat_stream_called)
        self.assertTrue(provider.web_search_called)
        self.assertTrue(any("web" in chunk for chunk in chunks))

    async def test_chat_send_returns_sse_error_when_web_search_unsupported(self):
        db = _FakeDb()
        provider = _FakeProvider()
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(message="search this", conversation_id=1, history=[], web_search_enabled=True)

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat._persist_streamed_chat_turn", AsyncMock()) as persist_mock,
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=provider)),
        ):
            response = await chat_send(body, db=db, current_user=current_user)
            chunks = [chunk async for chunk in response.body_iterator]

        payloads = [chunk.removeprefix("data: ").strip() for chunk in chunks if chunk.startswith("data: {")]
        errors = [json.loads(payload)["error"] for payload in payloads if "error" in json.loads(payload)]
        self.assertEqual(errors, ["当前供应商不支持 OpenAI 内置联网搜索，请切换到官方 OpenAI。"])
        persist_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
