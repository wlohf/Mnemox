"""Security checks for account-configured AI provider endpoints."""
from __future__ import annotations

import socket
import unittest
from unittest.mock import patch

from app.config import settings
from app.utils.outbound_url import _dns_cache, validate_ai_provider_url


class OutboundUrlSecurityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_environment = settings.ENVIRONMENT
        self.original_private = settings.ALLOW_PRIVATE_AI_ENDPOINTS
        settings.ENVIRONMENT = "production"
        settings.ALLOW_PRIVATE_AI_ENDPOINTS = False
        _dns_cache.clear()

    def tearDown(self):
        settings.ENVIRONMENT = self.original_environment
        settings.ALLOW_PRIVATE_AI_ENDPOINTS = self.original_private
        _dns_cache.clear()

    async def test_public_deployment_rejects_private_address(self):
        with patch("app.utils.outbound_url.socket.getaddrinfo", return_value=[(None, None, None, None, ("127.0.0.1", 0))]):
            with self.assertRaisesRegex(ValueError, "内网或本机"):
                await validate_ai_provider_url("https://localhost:11434/v1")

    async def test_public_deployment_requires_https(self):
        with self.assertRaisesRegex(ValueError, "HTTPS"):
            await validate_ai_provider_url("http://example.com/v1")

    async def test_public_deployment_accepts_global_https_address(self):
        with patch("app.utils.outbound_url.socket.getaddrinfo", return_value=[(None, None, None, None, ("8.8.8.8", 0))]):
            self.assertEqual(await validate_ai_provider_url("https://provider.example/v1/"), "https://provider.example/v1")

    async def test_local_development_can_use_local_model_server(self):
        settings.ENVIRONMENT = "development"
        self.assertEqual(await validate_ai_provider_url("http://127.0.0.1:11434/v1/"), "http://127.0.0.1:11434/v1")

    async def test_public_deployment_rejects_mixed_dns_answers(self):
        with patch(
            "app.utils.outbound_url.socket.getaddrinfo",
            return_value=[
                (None, None, None, None, ("8.8.8.8", 0)),
                (None, None, None, None, ("127.0.0.1", 0)),
            ],
        ):
            with self.assertRaisesRegex(ValueError, "内网或本机"):
                await validate_ai_provider_url("https://provider.example/v1")
