"""Validation for user-configured outbound HTTP endpoints.

This is deliberately applied before the server contacts a custom AI provider.
On public deployments it prevents an authenticated account from turning the
application into a proxy to Docker, cloud metadata, or other private networks.
"""
from __future__ import annotations

import asyncio
import ipaddress
import os
import socket
import time
from urllib.parse import urlsplit

from app.config import settings

_DNS_CACHE_SECONDS = 300.0
_dns_cache: dict[str, tuple[float, tuple[str, ...]]] = {}


def _is_public_deployment() -> bool:
    return settings.ENVIRONMENT.lower() in {"prod", "production"} or bool(os.environ.get("DB_PASSWORD"))


def _resolve_host(hostname: str) -> tuple[str, ...]:
    results = socket.getaddrinfo(hostname, None, type=socket.SOCK_STREAM)
    addresses = tuple(dict.fromkeys(str(item[4][0]) for item in results if item[4]))
    if not addresses:
        raise ValueError("无法解析服务地址")
    return addresses


async def _resolved_addresses(hostname: str) -> tuple[str, ...]:
    now = time.monotonic()
    cached = _dns_cache.get(hostname)
    if cached and now - cached[0] < _DNS_CACHE_SECONDS:
        return cached[1]
    loop = asyncio.get_running_loop()
    try:
        addresses = await loop.run_in_executor(None, _resolve_host, hostname)
    except (OSError, socket.gaierror) as exc:
        raise ValueError("无法解析服务地址") from exc
    _dns_cache[hostname] = (now, addresses)
    return addresses


async def validate_ai_provider_url(value: str | None) -> str:
    """Validate a custom provider URL and return its normalized text.

    Local/desktop development can use local model servers. Public deployments
    only permit HTTPS endpoints resolving exclusively to globally routable IPs.
    Callers should run this for both saved and one-off connection settings.
    """
    raw = str(value or "").strip()
    if not raw:
        return ""

    parsed = urlsplit(raw)
    if not parsed.scheme or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("AI 服务地址必须是完整且不含账号密码的 URL")
    try:
        _ = parsed.port
    except ValueError as exc:
        raise ValueError("AI 服务地址端口无效") from exc

    public_mode = _is_public_deployment() and not settings.ALLOW_PRIVATE_AI_ENDPOINTS
    allowed_schemes = {"https"} if public_mode else {"http", "https"}
    if parsed.scheme.lower() not in allowed_schemes:
        required = "HTTPS" if public_mode else "HTTP 或 HTTPS"
        raise ValueError(f"AI 服务地址必须使用 {required}")

    if not public_mode:
        return raw.rstrip("/")

    addresses = await _resolved_addresses(parsed.hostname)
    for address in addresses:
        try:
            ip = ipaddress.ip_address(address)
        except ValueError as exc:
            raise ValueError("AI 服务地址解析结果无效") from exc
        if not ip.is_global:
            raise ValueError("公网部署不允许访问内网或本机 AI 服务地址")
    return raw.rstrip("/")
