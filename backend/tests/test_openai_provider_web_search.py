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
    def __init__(self, *streams):
        self.streams = [list(events) for events in streams]
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        events = self.streams.pop(0)
        if len(events) == 1 and isinstance(events[0], Exception):
            raise events[0]
        return _FakeResponsesStream(events)


class _FailingResponses:
    def __init__(self, exc):
        self.exc = exc
        self.calls = []

    def stream(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        raise self.exc


class _FakeChatCompletions:
    def __init__(self, responses):
        self.responses = list(responses)
        self.calls = []

    async def create(self, **kwargs):
        self.calls.append(deepcopy(kwargs))
        return self.responses.pop(0)


class _FakeChatStream:
    def __init__(self, chunks):
        self.chunks = list(chunks)

    def __aiter__(self):
        self._iter = iter(self.chunks)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


def _stream_chunk(delta):
    return SimpleNamespace(choices=[SimpleNamespace(delta=delta)])


def _chat_response(message):
    return SimpleNamespace(choices=[SimpleNamespace(message=message)])


class OpenAIProviderWebSearchTests(unittest.IsolatedAsyncioTestCase):
    async def test_web_search_stream_uses_hosted_responses_tool_first(self):
        provider = OpenAIProvider(api_key="test", model="gpt-4o-mini")
        fake_responses = _FakeResponses(
            [
                SimpleNamespace(type="response.output_text.delta", delta="hello"),
                SimpleNamespace(type="response.output_text.delta", delta=" world"),
                SimpleNamespace(type="response.completed"),
            ],
        )
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
        self.assertEqual(fake_responses.calls[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(fake_responses.calls[0]["tool_choice"], {"type": "web_search"})
        self.assertEqual(fake_responses.calls[0]["include"], ["web_search_call.action.sources"])
        self.assertEqual(fake_responses.calls[0]["instructions"], "be brief")
        self.assertEqual(fake_responses.calls[0]["input"][0]["content"], "search")

    async def test_web_search_stream_keeps_auto_hosted_tool_choice_for_non_current_query(self):
        provider = OpenAIProvider(api_key="test", model="gpt-4o-mini")
        fake_responses = _FakeResponses(
            [
                SimpleNamespace(type="response.output_text.delta", delta="plain"),
                SimpleNamespace(type="response.completed"),
            ],
        )
        provider.client.responses = fake_responses

        chunks = [
            chunk
            async for chunk in provider.chat_stream_with_web_search(
                messages=[{"role": "user", "content": "解释一下勾股定理"}],
                system_prompt="be brief",
                temperature=0.2,
            )
        ]

        self.assertEqual(chunks, ["plain"])
        self.assertEqual(fake_responses.calls[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(fake_responses.calls[0]["tool_choice"], "auto")

    async def test_web_search_stream_sends_default_instructions_when_system_prompt_missing(self):
        provider = OpenAIProvider(api_key="test", model="gpt-4o-mini")
        fake_responses = _FakeResponses(
            [
                SimpleNamespace(type="response.output_text.delta", delta="searched"),
                SimpleNamespace(type="response.completed"),
            ],
        )
        provider.client.responses = fake_responses

        chunks = [
            chunk
            async for chunk in provider.chat_stream_with_web_search(
                messages=[{"role": "user", "content": "请联网搜索一下告诉我什么是mythos"}],
                system_prompt=None,
                temperature=0.2,
            )
        ]

        self.assertEqual(chunks, ["searched"])
        self.assertIsInstance(fake_responses.calls[0]["instructions"], str)
        self.assertTrue(fake_responses.calls[0]["instructions"].strip())
        self.assertEqual(fake_responses.calls[0]["tool_choice"], {"type": "web_search"})

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

    async def test_openai_compatible_web_search_uses_hosted_responses_first(self):
        provider = OpenAIProvider(
            api_key="test",
            model="gpt-4o",
            base_url="https://relay.example/v1",
        )
        provider.client.responses = _FakeResponses(
            [
                SimpleNamespace(type="response.output_text.delta", delta="hosted answer"),
                SimpleNamespace(type="response.completed"),
            ],
        )
        fake_completions = _FakeChatCompletions([])
        provider.client.chat.completions = fake_completions

        chunks = [
            chunk
            async for chunk in provider.chat_stream_with_web_search(
                messages=[{"role": "user", "content": "search"}],
                system_prompt="be brief",
                temperature=0.2,
            )
        ]

        self.assertEqual(chunks, ["hosted answer"])
        self.assertEqual(provider.client.responses.calls[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(provider.client.responses.calls[0]["tool_choice"], {"type": "web_search"})
        self.assertEqual(fake_completions.calls, [])

    async def test_openai_compatible_web_search_falls_back_to_streaming_local_function_tool(self):
        provider = OpenAIProvider(
            api_key="test",
            model="gpt-4o",
            base_url="https://relay.example/v1",
        )
        provider.client.responses = _FakeResponses(
            [ValueError("unsupported parameter: web_search")],
            [ValueError("unsupported parameter: tools")],
        )
        fake_completions = _FakeChatCompletions([
            _FakeChatStream([
                _stream_chunk(SimpleNamespace(tool_calls=[
                    SimpleNamespace(
                        index=0,
                        id="call_1",
                        type="function",
                        function=SimpleNamespace(name="web_search", arguments=""),
                    )
                ])),
                _stream_chunk(SimpleNamespace(tool_calls=[
                    SimpleNamespace(
                        index=0,
                        function=SimpleNamespace(arguments='{"query": "Mnemox'),
                    )
                ])),
                _stream_chunk(SimpleNamespace(tool_calls=[
                    SimpleNamespace(
                        index=0,
                        function=SimpleNamespace(arguments=' latest", "max_results": 2}'),
                    )
                ])),
            ]),
            _FakeChatStream(
                [
                    _stream_chunk(SimpleNamespace(content="final ")),
                    _stream_chunk(SimpleNamespace(content="answer")),
                ]
            ),
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

        self.assertEqual(chunks, ["final ", "answer"])
        search_mock.assert_awaited_once_with("Mnemox latest", limit=2)
        self.assertEqual(provider.client.responses.calls[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(fake_completions.calls[0]["tools"][0]["function"]["name"], "web_search")
        self.assertEqual(fake_completions.calls[0]["tool_choice"]["function"]["name"], "web_search")
        self.assertTrue(fake_completions.calls[0]["stream"])
        self.assertTrue(fake_completions.calls[1]["stream"])
        self.assertEqual(fake_completions.calls[1]["messages"][-1]["role"], "tool")
        self.assertIn("https://example.com/a", fake_completions.calls[1]["messages"][-1]["content"])

    async def test_openai_compatible_web_search_falls_back_to_responses_function_tool(self):
        provider = OpenAIProvider(
            api_key="test",
            model="gpt-4o",
        )
        fake_responses = _FakeResponses(
            [ValueError("unsupported parameter: web_search")],
            [
                SimpleNamespace(
                    type="response.output_item.added",
                    output_index=0,
                    item=SimpleNamespace(
                        type="function_call",
                        id="fc_1",
                        call_id="call_1",
                        name="web_search",
                        arguments='{"query": "Mnemox latest", "max_results": 2}',
                    ),
                ),
                SimpleNamespace(type="response.completed"),
            ],
            [
                SimpleNamespace(type="response.output_text.delta", delta="relay answer"),
                SimpleNamespace(type="response.completed"),
            ],
        )
        provider.client.responses = fake_responses

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

        self.assertEqual(chunks, ["relay answer"])
        search_mock.assert_awaited_once_with("Mnemox latest", limit=2)
        self.assertEqual(fake_responses.calls[0]["tools"], [{"type": "web_search"}])
        self.assertEqual(fake_responses.calls[1]["tools"][0]["name"], "web_search")
        self.assertEqual(fake_responses.calls[2]["input"][-1]["type"], "function_call_output")

    async def test_openai_compatible_forced_search_raises_when_model_does_not_call_tool(self):
        provider = OpenAIProvider(
            api_key="test",
            model="gpt-4o",
            base_url="https://relay.example/v1",
        )
        provider.client.responses = _FailingResponses(ValueError("unsupported parameter: web_search"))
        fake_completions = _FakeChatCompletions([
            _FakeChatStream([_stream_chunk(SimpleNamespace(content="plain answer"))]),
        ])
        provider.client.chat.completions = fake_completions

        with self.assertRaisesRegex(ValueError, "工具调用联网搜索"):
            _ = [
                chunk
                async for chunk in provider.chat_stream_with_web_search(
                    messages=[{"role": "user", "content": "请联网搜索一下告诉我什么是mythos"}],
                    system_prompt="be brief",
                    temperature=0.2,
                )
            ]

        self.assertEqual(len(provider.client.responses.calls), 2)
        self.assertEqual(fake_completions.calls[0]["tool_choice"]["function"]["name"], "web_search")

    async def test_web_search_treats_instructions_required_as_responses_unsupported(self):
        provider = OpenAIProvider(api_key="test", model="gpt-4o")
        fake_responses = _FakeResponses(
            [
                ValueError(
                    '{"error":{"message":"Instructions are required","type":"invalid_request_error"}}'
                )
            ],
            [
                SimpleNamespace(
                    type="response.output_item.added",
                    output_index=0,
                    item=SimpleNamespace(
                        type="function_call",
                        id="fc_1",
                        call_id="call_1",
                        name="web_search",
                        arguments='{"query": "mythos", "max_results": 1}',
                    ),
                ),
                SimpleNamespace(type="response.completed"),
            ],
            [
                SimpleNamespace(type="response.output_text.delta", delta="fallback answer"),
                SimpleNamespace(type="response.completed"),
            ],
        )
        provider.client.responses = fake_responses

        with patch(
            "app.ai.openai_provider.search_web",
            AsyncMock(return_value=[
                WebSearchResult(
                    title="Mythos",
                    url="https://example.com/mythos",
                    snippet="summary",
                )
            ]),
        ) as search_mock:
            chunks = [
                chunk
                async for chunk in provider.chat_stream_with_web_search(
                    messages=[{"role": "user", "content": "请联网搜索一下告诉我什么是mythos"}],
                    system_prompt=None,
                    temperature=0.2,
                )
            ]

        self.assertEqual(chunks, ["fallback answer"])
        search_mock.assert_awaited_once_with("mythos", limit=1)
        self.assertTrue(fake_responses.calls[0]["instructions"].strip())
        self.assertIn("联网搜索工具", fake_responses.calls[1]["instructions"])

    async def test_openai_compatible_web_search_keeps_auto_tool_choice_for_non_current_query(self):
        provider = OpenAIProvider(
            api_key="test",
            model="gpt-4o",
            base_url="https://relay.example/v1",
        )
        provider.client.responses = _FailingResponses(ValueError("unsupported parameter: web_search"))
        fake_completions = _FakeChatCompletions([
            _FakeChatStream([_stream_chunk(SimpleNamespace(content="plain answer"))]),
        ])
        provider.client.chat.completions = fake_completions

        chunks = [
            chunk
            async for chunk in provider.chat_stream_with_web_search(
                messages=[{"role": "user", "content": "解释一下勾股定理"}],
                system_prompt="be brief",
                temperature=0.2,
            )
        ]

        self.assertEqual(chunks, ["plain answer"])
        self.assertEqual(fake_completions.calls[0]["tool_choice"], "auto")

    async def test_chat_stream_skips_empty_choices_chunks(self):
        provider = OpenAIProvider(api_key="test", model="gpt-4o")
        fake_completions = _FakeChatCompletions([
            _FakeChatStream([
                SimpleNamespace(choices=[]),
                _stream_chunk(SimpleNamespace(content="answer")),
                SimpleNamespace(choices=[]),
            ]),
        ])
        provider.client.chat.completions = fake_completions

        chunks = [
            chunk
            async for chunk in provider.chat_stream(
                messages=[{"role": "user", "content": "hello"}],
                system_prompt="be brief",
                temperature=0.2,
            )
        ]

        self.assertEqual(chunks, ["answer"])

    async def test_openai_compatible_tool_unsupported_raises_fallback_signal(self):
        provider = OpenAIProvider(
            api_key="test",
            model="gpt-4o",
            base_url="https://relay.example/v1",
        )
        provider.client.responses = _FailingResponses(ValueError("unsupported parameter: web_search"))

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

    async def test_openai_compatible_instructions_required_raises_fallback_signal(self):
        provider = OpenAIProvider(
            api_key="test",
            model="gpt-4o",
            base_url="https://relay.example/v1",
        )
        provider.client.responses = _FailingResponses(ValueError("unsupported parameter: web_search"))

        class _InstructionsRequiredCompletions:
            async def create(self, **_kwargs):
                raise ValueError(
                    '{"error":{"message":"Instructions are required","type":"invalid_request_error"}}'
                )

        provider.client.chat.completions = _InstructionsRequiredCompletions()

        with self.assertRaisesRegex(ValueError, "工具调用联网搜索"):
            _ = [
                chunk
                async for chunk in provider.chat_stream_with_web_search(
                    messages=[{"role": "user", "content": "请联网搜索一下告诉我什么是mythos"}],
                    system_prompt="be brief",
                )
            ]


if __name__ == "__main__":
    unittest.main()
