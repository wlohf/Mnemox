"""AI HTTP clients with no redirects/proxies and connect-time DNS/IP enforcement.

Only TCP addresses are substituted; httpcore retains the original Host header,
TLS SNI and certificate verification. Both httpx-based and httpx2-based OpenAI
SDK releases are supported without adding a new HTTP stack dependency.
"""
from __future__ import annotations

import asyncio
import importlib
import time
from typing import Any

from app.utils.outbound_url import resolve_allowed_ai_addresses, validate_ai_provider_url


class PinnedAIEndpointNetworkBackend:
    def __init__(self, core_module: str, backend: Any = None) -> None:
        self._core_module = core_module
        self._backend = backend

    async def _get_backend(self) -> Any:
        if self._backend is None:
            # httpx has no public network-backend injection point. Keep the
            # version-sensitive integration confined here and regression-tested.
            auto = importlib.import_module(f"{self._core_module}._backends.auto")
            self._backend = auto.AutoBackend()
        return self._backend

    async def connect_tcp(
        self, host: str, port: int, timeout: float | None = None,
        local_address: str | None = None, socket_options: Any = None,
    ) -> Any:
        core = importlib.import_module(self._core_module)
        started = time.monotonic()
        try:
            addresses = await asyncio.wait_for(
                asyncio.get_running_loop().run_in_executor(None, resolve_allowed_ai_addresses, host),
                timeout=timeout,
            )
        except asyncio.TimeoutError as exc:
            raise core.ConnectTimeout("AI endpoint DNS resolution timed out") from exc
        backend = await self._get_backend()
        for index, address in enumerate(addresses):
            remaining = None if timeout is None else max(0.0, timeout - (time.monotonic() - started))
            if remaining == 0:
                raise core.ConnectTimeout("AI endpoint connection timed out")
            try:
                return await backend.connect_tcp(
                    host=address, port=port, timeout=remaining,
                    local_address=local_address, socket_options=socket_options,
                )
            except (core.ConnectError, core.ConnectTimeout):
                if index == len(addresses) - 1:
                    raise
        raise core.ConnectError("AI endpoint has no allowed addresses")

    async def connect_unix_socket(self, *args: Any, **kwargs: Any) -> Any:
        raise ValueError("AI endpoints cannot use Unix sockets")

    async def sleep(self, seconds: float) -> None:
        await (await self._get_backend()).sleep(seconds)


def _pinned_transport(httpx_module: Any, core_module: str) -> Any:
    class PolicyTransport(httpx_module.AsyncHTTPTransport):
        async def handle_async_request(self, request: Any) -> Any:
            # Enforce scheme/userinfo even for env-configured provider URLs that
            # did not travel through the settings API. TCP resolution below is
            # fresh and intentionally does not rely on the validation DNS cache.
            timeout = request.extensions.get("timeout", {}).get("connect", 5.0)
            try:
                await asyncio.wait_for(validate_ai_provider_url(str(request.url)), timeout=timeout)
            except asyncio.TimeoutError as exc:
                raise httpx_module.ConnectTimeout("AI endpoint validation timed out", request=request) from exc
            return await super().handle_async_request(request)

    transport = PolicyTransport(verify=True, trust_env=False)
    core = importlib.import_module(core_module)
    limits = httpx_module.Limits()
    # The original empty pool owns no connections yet. This private hook is the
    # sole httpx/httpcore coupling point; unsupported versions must fail closed.
    transport._pool = core.AsyncConnectionPool(
        network_backend=PinnedAIEndpointNetworkBackend(core_module),
        max_connections=limits.max_connections,
        max_keepalive_connections=limits.max_keepalive_connections,
        keepalive_expiry=limits.keepalive_expiry,
        http1=True, http2=False,
    )
    return transport


def openai_httpx_module() -> Any:
    sdk = importlib.import_module("openai._base_client")
    for name in ("httpx2", "httpx"):
        httpx = getattr(sdk, name, None)
        if httpx is not None and httpx.__name__ == name:
            return httpx
    raise RuntimeError("Unsupported OpenAI HTTP stack; refusing unprotected transport")


def create_openai_http_client() -> Any:
    httpx = openai_httpx_module()
    core = "httpcore2" if httpx.__name__ == "httpx2" else "httpcore"
    return httpx.AsyncClient(
        transport=_pinned_transport(httpx, core),
        # Preserve the SDK's long model-generation read timeout, not httpx's 5s.
        timeout=httpx.Timeout(600.0, connect=5.0),
        follow_redirects=False, trust_env=False,
    )


def create_ai_http_client(*, timeout: Any = 120.0) -> Any:
    """Shared client for direct AI HTTP calls (Claude and model discovery)."""
    httpx = importlib.import_module("httpx")
    return httpx.AsyncClient(
        timeout=timeout, transport=_pinned_transport(httpx, "httpcore"),
        follow_redirects=False, trust_env=False,
    )


create_claude_http_client = create_ai_http_client
