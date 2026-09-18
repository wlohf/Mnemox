"""Regression tests for the AI SDK outbound connection boundary."""
from __future__ import annotations

import unittest
from unittest.mock import patch

import httpx

from app.config import settings
from app.utils.outbound_transport import (
    PinnedAIEndpointNetworkBackend,
    create_claude_http_client,
    create_openai_http_client,
    openai_httpx_module,
)

# The SDK determines which native HTTP stack it requires.
httpx2 = openai_httpx_module()


class _RecordingBackend:
    def __init__(self) -> None:
        self.calls = []

    async def connect_tcp(self, **kwargs):
        self.calls.append(kwargs)
        return object()


class AIOutboundTransportSecurityTests(unittest.IsolatedAsyncioTestCase):
    def setUp(self):
        self.original_environment = settings.ENVIRONMENT
        self.original_private = settings.ALLOW_PRIVATE_AI_ENDPOINTS
        settings.ENVIRONMENT = "production"
        settings.ALLOW_PRIVATE_AI_ENDPOINTS = False

    def tearDown(self):
        settings.ENVIRONMENT = self.original_environment
        settings.ALLOW_PRIVATE_AI_ENDPOINTS = self.original_private

    async def test_connection_is_pinned_to_a_verified_public_ipv6_address(self):
        delegate = _RecordingBackend()
        transport = PinnedAIEndpointNetworkBackend("httpcore", backend=delegate)
        answers = [
            (None, None, None, None, ("2001:4860:4860::8888", 0, 0, 0)),
            (None, None, None, None, ("8.8.8.8", 0)),
        ]

        with patch("app.utils.outbound_url.socket.getaddrinfo", return_value=answers):
            await transport.connect_tcp("provider.example", 443)

        self.assertEqual(delegate.calls, [{
            "host": "2001:4860:4860::8888",
            "port": 443,
            "timeout": None,
            "local_address": None,
            "socket_options": None,
        }])

    async def test_mixed_public_and_loopback_answers_never_connect(self):
        delegate = _RecordingBackend()
        transport = PinnedAIEndpointNetworkBackend("httpcore", backend=delegate)
        answers = [
            (None, None, None, None, ("8.8.8.8", 0)),
            (None, None, None, None, ("::1", 0, 0, 0)),
        ]

        with patch("app.utils.outbound_url.socket.getaddrinfo", return_value=answers):
            with self.assertRaisesRegex(ValueError, "内网或本机"):
                await transport.connect_tcp("rebind.example", 443)

        self.assertEqual(delegate.calls, [])

    async def test_development_policy_allows_local_ollama_connection(self):
        settings.ENVIRONMENT = "development"
        delegate = _RecordingBackend()
        transport = PinnedAIEndpointNetworkBackend("httpcore", backend=delegate)

        with patch(
            "app.utils.outbound_url.socket.getaddrinfo",
            return_value=[(None, None, None, None, ("127.0.0.1", 0))],
        ):
            await transport.connect_tcp("localhost", 11434)

        self.assertEqual(delegate.calls[0]["host"], "127.0.0.1")

    async def test_sdk_clients_do_not_follow_redirects(self):
        openai_client = create_openai_http_client()
        claude_client = create_claude_http_client()
        openai_calls = []
        claude_calls = []

        async def openai_redirect(request):
            openai_calls.append(request.url)
            return httpx2.Response(302, headers={"location": "http://127.0.0.1/"})

        async def claude_redirect(request):
            claude_calls.append(request.url)
            return httpx.Response(302, headers={"location": "http://127.0.0.1/"})

        # Mock transports make this a pure client-policy test: no socket or DNS
        # access occurs while confirming the redirect target is not requested.
        openai_client._transport = httpx2.MockTransport(openai_redirect)
        claude_client._transport = httpx.MockTransport(claude_redirect)
        try:
            self.assertEqual((await openai_client.get("https://provider.example/start")).status_code, 302)
            self.assertEqual((await claude_client.get("https://provider.example/start")).status_code, 302)
        finally:
            await openai_client.aclose()
            await claude_client.aclose()

        self.assertEqual(len(openai_calls), 1)
        self.assertEqual(len(claude_calls), 1)


if __name__ == "__main__":
    unittest.main()
