import unittest
from copy import deepcopy
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.ai.openai_provider import OpenAIProvider
from app.services.web_search import WebSearchResult


class _FakeResponsesStream:
    def __init__(self, events):
        self.events = events

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return None

    def __aiter__(self):
        self._iter = iter(self.events)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _FakeResponses:
    def __init__(self, events):
        self.events = events
        self.kwargs = None

    def stream(self, **kwargs):
        self.kwargs = kwargs
        return _FakeResponsesStream(self.events)


class _FakeChatCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return self.responses.pop(0)


def _chat_response(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class OpenAIProviderWebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_search_stream_yields_only_output_text_delta(self):
        provider = OpenAIProvider(api_key="test", model="gpt-4o-mini")
        fake_responses = _FakeResponses([
            SimpleNamespace(type="response.web_search_call.searching"),
            SimpleNamespace(type="response.output_text.delta", delta="hello"),
            SimpleNamespace(type="response.output_text.delta", delta=" world"),
            SimpleNamespace(type="response.completed"),
        ])
        provider.client.responses = fake_responses

        chunks = [
            chunk
            async for chunk in provider.chat_stream_with_web_search(
                messages=[{"role": "user", "content": "search"}],
                system_prompt="be brief",
                temperature=0.2,
            )
        ]

        self.assertEqual(chunks, ["hello", " world"])
        self.assertEqual(fake_responses.kwargs["tools"], [{"type": "web_search", "search_context_size": "medium"}])
        self.assertEqual(fake_responses.kwargs["include"], ["web_search_call.action.sources"])
        self.assertEqual(fake_responses.kwargs["instructions"], "be brief")
        self.assertEqual(fake_responses.kwargs["input"][0]["content"], "search")

    def test_supports_web_search_for_official_and_openai_compatible_base_url(self):
        self.assertTrue(OpenAIProvider(api_key="test").supports_web_search())
        self.assertTrue(
            OpenAIProvider(
                api_key="test",
                base_url="https://api.openai.com/v1/",
            ).supports_web_search()
        )
        self.assertTrue(
            OpenAIProvider(
                api_key="test",
                base_url="https://example.com/v1",
            ).supports_web_search()
        )

    async def test_openai_compatible_web_search_uses_local_function_tool(self):
        provider = OpenAIProvider(
            api_key="test",
            model="gpt-4o",
            base_url="https://relay.example/v1",
        )
        fake_completions = _FakeChatCompletions([
            _chat_response(
                SimpleNamespace(
                    content=None,
                    tool_calls=[
                        SimpleNamespace(
                            id="call_1",
                            type="function",
                            function=SimpleNamespace(
                                name="web_search",
                                arguments='{"query": "Mnemox latest", "max_results": 2}',
                            ),
                        )
                    ],
                )
            ),
            _chat_response(SimpleNamespace(content="final answer", tool_calls=None)),
        ])
        provider.client.chat.completions = fake_completions

        with patch(
            "app.ai.openai_provider.search_web",
            AsyncMock(return_value=[
                WebSearchResult(
                    title="Result A",
                    url="https://example.com/a",
                    snippet="summary",
                )
            ]),
        ) as search_mock:
            chunks = [
                chunk
                async for chunk in provider.chat_stream_with_web_search(
                    messages=[{"role": "user", "content": "search"}],
                    system_prompt="be brief",
                    temperature=0.2,
                )
            ]

        self.assertEqual(chunks, ["final answer"])
        search_mock.assert_awaited_once_with("Mnemox latest", limit=2)
        self.assertEqual(fake_completions.calls[0]["tools"][0]["function"]["name"], "web_search")
        self.assertEqual(fake_completions.calls[0]["tool_choice"], "auto")
        self.assertEqual(fake_completions.calls[1]["messages"][-1]["role"], "tool")
        self.assertIn("https://example.com/a", fake_completions.calls[1]["messages"][-1]["content"])

    async def test_openai_compatible_tool_unsupported_raises_fallback_signal(self):
        provider = OpenAIProvider(
            api_key="test",
            model="gpt-4o",
            base_url="https://relay.example/v1",
        )

        class _UnsupportedCompletions:
            async def create(self, **_kwargs):
                raise ValueError("unsupported parameter: tools")

        provider.client.chat.completions = _UnsupportedCompletions()

        with self.assertRaisesRegex(ValueError, "工具调用联网搜索"):
            _ = [
                chunk
                async for chunk in provider.chat_stream_with_web_search(
                    messages=[{"role": "user", "content": "search"}],
                    system_prompt="be brief",
                )
            ]


if __name__ == "__main__":
    unittest.main()
