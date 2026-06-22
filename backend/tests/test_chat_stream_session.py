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
        self.system_prompt = None
        self.messages = None
        self.max_context_tokens = None

    def supports_web_search(self):
        return False

    async def chat_stream(self, **kwargs):
        self.chat_stream_called = True
        self.system_prompt = kwargs.get("system_prompt")
        self.messages = kwargs.get("messages")
        yield "ok"


class _FakeWebSearchProvider(_FakeProvider):
    def supports_web_search(self):
        return True

    async def chat_stream_with_web_search(self, **_kwargs):
        self.web_search_called = True
        yield "web"


class _UnsupportedHostedWebSearchProvider(_FakeProvider):
    def supports_web_search(self):
        return True

    async def chat_stream_with_web_search(self, **_kwargs):
        self.web_search_called = True
        raise ValueError("当前供应商不支持 OpenAI 内置联网搜索，请切换到官方 OpenAI。")
        yield ""


class _OpenAICompatibleProvider(_FakeProvider):
    def supports_web_search(self):
        return True

    def _uses_official_openai_api(self):
        return False

    async def chat_stream_with_web_search(self, **_kwargs):
        self.web_search_called = True
        yield "web"


class _SearchSummaryProvider(_FakeProvider):
    def supports_web_search(self):
        return True

    async def chat_stream_with_web_search(self, **_kwargs):
        self.web_search_called = True
        yield (
            '{"summary":"Mythos 是 Anthropic 的一个 AI 项目。",'
            '"sources":[{"title":"Official","url":"https://example.com/mythos","snippet":"summary"}]}'
        )


class _BrokenProvider(_FakeProvider):
    async def chat_stream(self, **_kwargs):
        raise AttributeError("'str' object has no attribute 'choices'")
        yield ""


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

    async def test_chat_send_trims_old_history_when_context_token_budget_is_set(self):
        db = _FakeDb()
        provider = _FakeProvider()
        provider.max_context_tokens = 100
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(
            message="current question",
            conversation_id=1,
            history=[
                {"role": "user", "content": "older user context " + ("x " * 1200)},
                {"role": "assistant", "content": "older assistant context " + ("y " * 1200)},
                {"role": "user", "content": "recent user context"},
                {"role": "assistant", "content": "recent assistant context"},
            ],
            web_search_enabled=False,
        )

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat._persist_streamed_chat_turn", AsyncMock()),
            patch("app.routers.chat.detect_progress_feedback", AsyncMock(return_value=None)),
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=provider)),
        ):
            response = await chat_send(body, db=db, current_user=current_user)
            chunks = [chunk async for chunk in response.body_iterator]

        sent_text = "\n".join(str(message.get("content")) for message in provider.messages)
        self.assertTrue(any("ok" in chunk for chunk in chunks))
        self.assertIn("current question", sent_text)
        self.assertIn("recent user context", sent_text)
        self.assertNotIn("older user context", sent_text)
        self.assertNotIn("older assistant context", sent_text)

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

    async def test_chat_send_uses_provider_hosted_search_for_openai_compatible_provider(self):
        db = _FakeDb()
        provider = _OpenAICompatibleProvider()
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

    async def test_chat_send_uses_external_search_context_when_hosted_web_search_unsupported(self):
        db = _FakeDb()
        provider = _FakeProvider()
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(message="search this", conversation_id=1, history=[], web_search_enabled=True)

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat._persist_streamed_chat_turn", AsyncMock()) as persist_mock,
            patch("app.routers.chat.search_web", AsyncMock(return_value=[
                type("Result", (), {"title": "Result A", "url": "https://example.com/a", "snippet": "summary"})()
            ])),
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=provider)),
        ):
            response = await chat_send(body, db=db, current_user=current_user)
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertTrue(provider.chat_stream_called)
        self.assertIn("https://example.com/a", provider.system_prompt)
        self.assertTrue(any("web_search_results" in chunk for chunk in chunks))
        self.assertTrue(any("ok" in chunk for chunk in chunks))
        persist_mock.assert_awaited_once()

    async def test_chat_send_uses_external_search_when_app_search_mode_is_selected(self):
        db = _FakeDb()
        provider = _OpenAICompatibleProvider()
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(
            message="search this",
            conversation_id=1,
            history=[],
            web_search_enabled=True,
            web_search_mode="app_search",
        )

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat._persist_streamed_chat_turn", AsyncMock()) as persist_mock,
            patch("app.routers.chat.search_web", AsyncMock(return_value=[
                type("Result", (), {"title": "Result A", "url": "https://example.com/a", "snippet": "summary"})()
            ])),
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=provider)),
            patch("app.routers.chat.detect_progress_feedback", AsyncMock(return_value=None)),
        ):
            response = await chat_send(body, db=db, current_user=current_user)
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertTrue(provider.chat_stream_called)
        self.assertFalse(provider.web_search_called)
        self.assertIn("https://example.com/a", provider.system_prompt)
        self.assertTrue(any("web_search_results" in chunk for chunk in chunks))
        self.assertTrue(any("ok" in chunk for chunk in chunks))
        persist_mock.assert_awaited_once()

    async def test_chat_send_uses_grok_summary_mode_with_dedicated_provider(self):
        db = _FakeDb()
        main_provider = _FakeProvider()
        search_provider = _SearchSummaryProvider()
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(
            message="search this",
            conversation_id=1,
            history=[],
            web_search_enabled=True,
            web_search_mode="grok_summary",
            web_search_provider_name="openai-grok",
        )

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat._persist_streamed_chat_turn", AsyncMock()) as persist_mock,
            patch("app.routers.chat.detect_progress_feedback", AsyncMock(return_value=None)),
            patch(
                "app.routers.chat.AIProviderFactory.create_provider",
                AsyncMock(side_effect=[main_provider, search_provider]),
            ),
        ):
            response = await chat_send(body, db=db, current_user=current_user)
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertTrue(main_provider.chat_stream_called)
        self.assertTrue(search_provider.web_search_called)
        self.assertIn("https://example.com/mythos", main_provider.system_prompt)
        self.assertIn("Anthropic", main_provider.system_prompt)
        self.assertTrue(any("web_search_results" in chunk for chunk in chunks))
        self.assertTrue(any("ok" in chunk for chunk in chunks))
        persist_mock.assert_awaited_once()

    async def test_chat_send_falls_back_when_hosted_web_search_raises_unsupported(self):
        db = _FakeDb()
        provider = _UnsupportedHostedWebSearchProvider()
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(message="search this", conversation_id=1, history=[], web_search_enabled=True)

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat._persist_streamed_chat_turn", AsyncMock()) as persist_mock,
            patch("app.routers.chat.search_web", AsyncMock(return_value=[
                type("Result", (), {"title": "Result A", "url": "https://example.com/a", "snippet": "summary"})()
            ])),
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=provider)),
        ):
            response = await chat_send(body, db=db, current_user=current_user)
            chunks = [chunk async for chunk in response.body_iterator]

        self.assertTrue(provider.web_search_called)
        self.assertTrue(provider.chat_stream_called)
        self.assertIn("https://example.com/a", provider.system_prompt)
        self.assertTrue(any("web_search_results" in chunk for chunk in chunks))
        self.assertTrue(any("ok" in chunk for chunk in chunks))
        self.assertFalse(any("当前供应商不支持 OpenAI 内置联网搜索" in chunk for chunk in chunks))
        persist_mock.assert_awaited_once()

    async def test_chat_send_returns_user_readable_provider_error(self):
        db = _FakeDb()
        current_user = User(id=1, username="u", email="u@example.com", hashed_password="x")
        body = ChatRequest(message="hello", conversation_id=1, history=[])

        with (
            patch("app.routers.chat._resolve_materials_and_build_prompt", AsyncMock(return_value=("", [], []))),
            patch("app.routers.chat.get_relevant_memories", AsyncMock(return_value=[])),
            patch("app.routers.chat._persist_streamed_chat_turn", AsyncMock()) as persist_mock,
            patch("app.routers.chat.AIProviderFactory.create_provider", AsyncMock(return_value=_BrokenProvider())),
        ):
            response = await chat_send(body, db=db, current_user=current_user)
            chunks = [chunk async for chunk in response.body_iterator]

        payloads = [chunk.removeprefix("data: ").strip() for chunk in chunks if chunk.startswith("data: {")]
        errors = [json.loads(payload)["error"] for payload in payloads if "error" in json.loads(payload)]
        self.assertEqual(
            errors,
            ["AI 回复失败：供应商返回的数据格式不对。请检查 Base URL 是否是 OpenAI 兼容的 /v1 地址，模型是否支持聊天接口。"],
        )
        persist_mock.assert_not_awaited()


if __name__ == "__main__":
    unittest.main()
