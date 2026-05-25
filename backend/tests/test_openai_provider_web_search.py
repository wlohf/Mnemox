import unittest
from types import SimpleNamespace

from app.ai.openai_provider import OpenAIProvider


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

    def test_supports_web_search_only_for_official_openai_base_url(self):
        self.assertTrue(OpenAIProvider(api_key="test").supports_web_search())
        self.assertTrue(
            OpenAIProvider(
                api_key="test",
                base_url="https://api.openai.com/v1/",
            ).supports_web_search()
        )
        self.assertFalse(
            OpenAIProvider(
                api_key="test",
                base_url="https://example.com/v1",
            ).supports_web_search()
        )


if __name__ == "__main__":
    unittest.main()
