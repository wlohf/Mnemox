"""Exercise real HTTP pools against an in-memory TCP/TLS stream (no sockets)."""
import importlib
import ssl
import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import httpx

from app.config import settings
from app.utils.outbound_transport import (
    PinnedAIEndpointNetworkBackend, create_ai_http_client,
    create_openai_http_client, openai_httpx_module,
)


class RecordingStream:
    def __init__(self):
        self.writes = []
        self.tls = None

    async def start_tls(self, ssl_context, server_hostname=None, timeout=None):
        self.tls = (ssl_context, server_hostname)
        return self

    async def write(self, buffer, timeout=None):
        self.writes.append(buffer)

    async def read(self, max_bytes, timeout=None):
        return b'HTTP/1.1 200 OK\r\nContent-Length: 2\r\nConnection: close\r\n\r\n{}'

    async def aclose(self):
        pass

    def get_extra_info(self, info):
        return None


class RecordingNetwork:
    def __init__(self):
        self.stream = RecordingStream()
        self.peers = []

    async def connect_tcp(self, **kwargs):
        self.peers.append(kwargs['host'])
        return self.stream


class AIConnectionPinningTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.public = patch('app.utils.outbound_url._is_public_deployment', return_value=True)
        self.private = patch.object(settings, 'ALLOW_PRIVATE_AI_ENDPOINTS', False)
        self.public.start(); self.private.start()

    async def asyncTearDown(self):
        self.private.stop(); self.public.stop()

    def clients(self):
        sdk_core = 'httpcore2' if openai_httpx_module().__name__ == 'httpx2' else 'httpcore'
        return [(create_ai_http_client(), 'httpcore'), (create_openai_http_client(), sdk_core)]

    async def test_real_http_pools_pin_tcp_but_preserve_host_sni_and_certificate_verification(self):
        for client, core in self.clients():
            with self.subTest(core=core):
                network = RecordingNetwork()
                client._transport._pool._network_backend = PinnedAIEndpointNetworkBackend(core, network)
                try:
                    with patch('app.utils.outbound_url._resolved_addresses', new=AsyncMock(return_value=('8.8.8.8',))), patch('app.utils.outbound_url._resolve_host', return_value=('8.8.8.8',)):
                        result = await client.get('https://provider.example/v1/models')
                    self.assertEqual(result.status_code, 200)
                    self.assertEqual(network.peers, ['8.8.8.8'])
                    context, hostname = network.stream.tls
                    self.assertIn(hostname, ('provider.example', b'provider.example'))
                    self.assertEqual(context.verify_mode, ssl.CERT_REQUIRED)
                    self.assertTrue(context.check_hostname)
                    self.assertIn(b'Host: provider.example', b''.join(network.stream.writes))
                finally:
                    await client.aclose()

    async def test_public_cached_validation_cannot_hide_private_connect_time_dns(self):
        for client, core in self.clients():
            network = RecordingNetwork()
            client._transport._pool._network_backend = PinnedAIEndpointNetworkBackend(core, network)
            try:
                with patch('app.utils.outbound_url._resolved_addresses', new=AsyncMock(return_value=('8.8.8.8',))), patch('app.utils.outbound_url._resolve_host', return_value=('127.0.0.1',)):
                    with self.assertRaisesRegex(ValueError, '内网或本机'):
                        await client.get('https://provider.example/v1/models')
                self.assertEqual(network.peers, [])
            finally:
                await client.aclose()

    async def test_production_plain_http_is_rejected_before_dns_or_tcp(self):
        async with create_ai_http_client() as client:
            with patch('app.utils.outbound_url._resolve_host') as dns:
                with self.assertRaisesRegex(ValueError, 'HTTPS'):
                    await client.get('http://8.8.8.8/v1/models')
                dns.assert_not_called()

    async def test_httpx_based_openai_sdk_remains_supported(self):
        real_import = importlib.import_module
        def modules(name):
            return SimpleNamespace(httpx=httpx) if name == 'openai._base_client' else real_import(name)
        with patch('app.utils.outbound_transport.importlib.import_module', side_effect=modules):
            async with create_openai_http_client() as client:
                self.assertIsInstance(client, httpx.AsyncClient)
                self.assertFalse(client.follow_redirects)
                self.assertEqual(client.timeout.read, 600.0)
