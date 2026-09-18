"""Provider-local extraction safeguards; all SDK calls are mocked."""
from __future__ import annotations

from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from app.ai.base import AIProvider
from app.ai.gemini_provider import GeminiProvider
from app.ai.openai_provider import OpenAIProvider


class _ProviderStub(AIProvider):
    async def chat(self, messages, system_prompt=None, temperature=0.7):
        return ""

    async def chat_stream(self, messages, system_prompt=None, temperature=0.7):
        if False:
            yield ""


@pytest.mark.asyncio
async def test_base_extraction_limit_only_tightens_and_cleanup_is_noop():
    provider = _ProviderStub("key", "model", max_output_tokens=400)

    provider.configure_extraction(120)
    provider.configure_extraction(800)

    assert provider.max_output_tokens == 120
    assert await provider.close_extraction() is None


def test_openai_extraction_disables_retries_without_replacing_pinned_client():
    pinned_http_client = object()
    sdk_client = MagicMock()
    sdk_client.max_retries = 2

    with patch("app.ai.openai_provider.create_openai_http_client", return_value=pinned_http_client), patch(
        "app.ai.openai_provider.AsyncOpenAI", return_value=sdk_client
    ) as async_openai:
        provider = OpenAIProvider("key", max_output_tokens=300)
        provider.configure_extraction(150)

    assert provider.max_output_tokens == 150
    assert provider.client is sdk_client
    assert sdk_client.max_retries == 0
    assert async_openai.call_args.kwargs["http_client"] is pinned_http_client


@pytest.mark.asyncio
async def test_openai_extraction_cleanup_closes_sdk_client():
    sdk_client = MagicMock()
    sdk_client.close = AsyncMock()

    with patch("app.ai.openai_provider.create_openai_http_client", return_value=object()), patch(
        "app.ai.openai_provider.AsyncOpenAI", return_value=sdk_client
    ):
        provider = OpenAIProvider("key")

    await provider.close_extraction()
    sdk_client.close.assert_awaited_once()


@pytest.mark.asyncio
async def test_gemini_extraction_uses_one_attempt_per_call_and_closes_client():
    response = SimpleNamespace(text="ok", usage_metadata=None)
    sdk_client = MagicMock()
    sdk_client.aio.models.generate_content = AsyncMock(return_value=response)
    sdk_client.aio.aclose = AsyncMock()

    with patch("app.ai.gemini_provider.genai.Client", return_value=sdk_client):
        provider = GeminiProvider("key", max_output_tokens=300)
        await provider.chat([{"role": "user", "content": "ordinary"}])
        provider.configure_extraction(120)
        assert await provider.chat([{"role": "user", "content": "extract"}]) == "ok"
        await provider.close_extraction()

    ordinary_config = sdk_client.aio.models.generate_content.await_args_list[0].kwargs["config"]
    extraction_config = sdk_client.aio.models.generate_content.await_args_list[1].kwargs["config"]
    assert ordinary_config.http_options is None
    assert extraction_config.max_output_tokens == 120
    assert extraction_config.http_options.retry_options.attempts == 1
    sdk_client.aio.aclose.assert_awaited_once()


def test_gemini_extraction_rejects_sdk_without_retry_controls_before_chat():
    sdk_client = MagicMock()
    with patch("app.ai.gemini_provider.genai.Client", return_value=sdk_client), patch(
        "app.ai.gemini_provider.types.HttpRetryOptions", None
    ):
        provider = GeminiProvider("key")
        with pytest.raises(RuntimeError, match="retry control"):
            provider.configure_extraction(100)

    sdk_client.aio.models.generate_content.assert_not_called()
