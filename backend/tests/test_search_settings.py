import unittest

from app.models.ai_settings import AIProviderSetting
from app.models.search_settings import AISearchSettings
from app.routers.ai_settings import (
    SearchSettingsUpdate,
    _search_settings_to_out,
    _to_out,
)
from app.ai.factory import AIProviderFactory
from app.services.search_settings_service import search_settings_to_dict
from app.utils.secret_crypto import encrypt_secret


class SearchSettingsTests(unittest.TestCase):
    def test_default_search_settings_use_auto_with_fallback(self):
        data = search_settings_to_dict(None)

        self.assertFalse(data["enabled"])
        self.assertEqual(data["default_mode"], "auto")
        self.assertEqual(data["provider"], "auto")
        self.assertEqual(data["tavily_search_depth"], "advanced")
        self.assertEqual(data["tavily_max_results"], 8)
        self.assertEqual(data["tavily_chunks_per_source"], 3)
        self.assertTrue(data["fallback_enabled"])

    def test_search_settings_output_masks_tavily_key(self):
        row = AISearchSettings(
            user_id=1,
            enabled=True,
            provider="tavily",
            tavily_api_key=encrypt_secret("tvly-secret-key"),
            tavily_max_results=8,
        )

        out = _search_settings_to_out(row)

        self.assertEqual(out.provider, "tavily")
        self.assertEqual(out.tavily_api_key_masked, "tvl****-key")

    def test_search_settings_update_clamps_quality_values(self):
        update = SearchSettingsUpdate(
            tavily_max_results=99,
            tavily_chunks_per_source=99,
            timeout_seconds=99,
        )

        self.assertEqual(update.tavily_max_results, 10)
        self.assertEqual(update.tavily_chunks_per_source, 5)
        self.assertEqual(update.timeout_seconds, 30)

    def test_provider_output_includes_token_budget_settings(self):
        row = AIProviderSetting(
            user_id=1,
            provider_name="openai",
            display_name="OpenAI",
            api_key="",
            base_url="https://api.openai.com/v1",
            model="gpt-4.1",
            max_context_tokens=64000,
            max_output_tokens=8192,
            enabled=True,
        )

        out = _to_out(row)

        self.assertEqual(out.max_context_tokens, 64000)
        self.assertEqual(out.max_output_tokens, 8192)

    def test_factory_passes_token_budgets_to_provider(self):
        provider = AIProviderFactory.create_provider_from_settings(
            provider_name="openai",
            api_key="sk-test",
            model="gpt-4.1",
            base_url="https://api.openai.com/v1",
            max_context_tokens=64000,
            max_output_tokens=8192,
        )

        self.assertEqual(provider.max_context_tokens, 64000)
        self.assertEqual(provider.max_output_tokens, 8192)


if __name__ == "__main__":
    unittest.main()
