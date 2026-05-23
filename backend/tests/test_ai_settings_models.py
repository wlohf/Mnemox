import unittest
from unittest.mock import patch

import httpx

from app.models.ai_settings import AIProviderSetting
from app.routers.ai_settings import (
    _connection_value,
    _fetch_model_catalog,
    _get_effective_values,
    _merge_available_models,
    _parse_available_models,
)


class _StaticResponseClient:
    def __init__(self, response: httpx.Response):
        self.response = response

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, **kwargs):
        self.response.request = httpx.Request("GET", url)
        return self.response


class AISettingsModelCatalogTests(unittest.IsolatedAsyncioTestCase):
    async def test_model_search_falls_back_to_configured_model_when_catalog_missing(self):
        response = httpx.Response(404)

        with patch("app.routers.ai_settings.httpx.AsyncClient", return_value=_StaticResponseClient(response)):
            models = await _fetch_model_catalog(
                provider_name="openai-compatible",
                api_key="sk-test",
                base_url="https://proxy.example/v1",
                model_hint="gpt-4.1",
            )

        self.assertEqual(models, ["gpt-4.1"])

    async def test_model_search_does_not_hide_auth_failures(self):
        response = httpx.Response(401)

        with patch("app.routers.ai_settings.httpx.AsyncClient", return_value=_StaticResponseClient(response)):
            with self.assertRaises(httpx.HTTPStatusError):
                await _fetch_model_catalog(
                    provider_name="openai-compatible",
                    api_key="bad-key",
                    base_url="https://proxy.example/v1",
                    model_hint="gpt-4.1",
                )

    async def test_effective_values_do_not_fall_back_to_env_api_key(self):
        row = AIProviderSetting(
            user_id=1,
            provider_name="openai",
            display_name="OpenAI",
            api_key="",
            base_url="",
            model="",
            enabled=True,
        )

        with patch("app.routers.ai_settings.settings.OPENAI_API_KEY", "sk-env"):
            api_key, base_url, model = _get_effective_values(row)

        self.assertEqual(api_key, "")
        self.assertEqual(base_url, "https://api.openai.com/v1")
        self.assertEqual(model, "")

    async def test_available_models_can_be_cleared_without_default_model_reappearing(self):
        row = AIProviderSetting(
            user_id=1,
            provider_name="openai",
            display_name="OpenAI",
            api_key="",
            base_url="https://api.openai.com/v1",
            model="",
            available_models="[]",
            enabled=False,
        )

        with patch("app.routers.ai_settings.settings.OPENAI_MODEL", "gpt-4"):
            api_key, base_url, model = _get_effective_values(row)
            models = _parse_available_models(row.available_models, model)

        self.assertEqual(api_key, "")
        self.assertEqual(base_url, "https://api.openai.com/v1")
        self.assertEqual(model, "")
        self.assertEqual(models, [])

    async def test_model_search_merges_without_mutating_provider_settings(self):
        row = AIProviderSetting(
            user_id=1,
            provider_name="openai-proxy",
            display_name="Proxy",
            api_key="",
            base_url="https://old.example/v1",
            model="old-model",
            available_models='["old-model"]',
            enabled=True,
        )

        models = _merge_available_models(row.available_models, ["new-model", "old-model"], "new-model")

        self.assertEqual(row.api_key, "")
        self.assertEqual(row.base_url, "https://old.example/v1")
        self.assertEqual(row.model, "old-model")
        self.assertEqual(
            models,
            ["new-model", "old-model"],
        )

    async def test_connection_value_uses_unsaved_nonempty_input(self):
        self.assertEqual(_connection_value("saved", None), "saved")
        self.assertEqual(_connection_value("saved", ""), "saved")
        self.assertEqual(_connection_value("saved", " unsaved "), "unsaved")

    async def test_connection_value_can_treat_blank_key_as_explicitly_empty(self):
        self.assertEqual(_connection_value("saved", "", use_saved_for_blank=False), "")


if __name__ == "__main__":
    unittest.main()
