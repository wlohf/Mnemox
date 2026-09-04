"""Provider token usage normalization and configured-price tests."""
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.ai.claude_provider import ClaudeProvider
from app.ai.gemini_provider import GeminiProvider
from app.ai.openai_provider import OpenAIProvider


class _ClaudeResponseClient:
    def __init__(self, payload):
        self.payload = payload

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_args):
        return False

    async def post(self, *_args, **_kwargs):
        request = httpx.Request("POST", "https://api.anthropic.com/v1/messages")
        return httpx.Response(200, request=request, json=self.payload)


class AIProviderUsageTests(unittest.IsolatedAsyncioTestCase):
    async def test_openai_usage_is_normalized_and_priced(self):
        provider = OpenAIProvider(
            api_key="test",
            model="gpt-test",
            input_price_per_million=2,
            output_price_per_million=8,
            provider_name="openai-custom",
        )
        provider.client.chat.completions.create = AsyncMock(
            return_value=SimpleNamespace(
                choices=[SimpleNamespace(message=SimpleNamespace(content="done"))],
                usage=SimpleNamespace(
                    prompt_tokens=100,
                    completion_tokens=25,
                    total_tokens=125,
                ),
            )
        )

        self.assertEqual(await provider.chat([{"role": "user", "content": "hello"}]), "done")

        usage = provider.get_last_usage()
        self.assertEqual(usage["provider"], "openai-custom")
        self.assertEqual(usage["total_tokens"], 125)
        self.assertAlmostEqual(usage["configured_cost_usd"], 0.0004)

    async def test_claude_usage_is_normalized_without_guessing_price(self):
        provider = ClaudeProvider(api_key="test", model="claude-test")
        payload = {
            "content": [{"type": "text", "text": "done"}],
            "usage": {"input_tokens": 80, "output_tokens": 20},
        }
        with patch("app.ai.claude_provider.httpx.AsyncClient", return_value=_ClaudeResponseClient(payload)):
            self.assertEqual(await provider.chat([{"role": "user", "content": "hello"}]), "done")

        usage = provider.get_last_usage()
        self.assertEqual(usage["total_tokens"], 100)
        self.assertIsNone(usage["configured_cost_usd"])
        self.assertFalse(usage["pricing_configured"])

    async def test_gemini_usage_metadata_is_normalized(self):
        provider = GeminiProvider(
            api_key="test",
            model="gemini-test",
            input_price_per_million=1,
            output_price_per_million=3,
        )
        provider.client.aio.models.generate_content = AsyncMock(
            return_value=SimpleNamespace(
                text="done",
                usage_metadata=SimpleNamespace(
                    prompt_token_count=60,
                    candidates_token_count=10,
                    total_token_count=70,
                ),
            )
        )

        self.assertEqual(await provider.chat([{"role": "user", "content": "hello"}]), "done")

        usage = provider.get_last_usage()
        self.assertEqual(usage["total_tokens"], 70)
        self.assertAlmostEqual(usage["configured_cost_usd"], 0.00009)


if __name__ == "__main__":
    unittest.main()
