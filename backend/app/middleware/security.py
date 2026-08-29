"""Production-facing safety middleware."""
from __future__ import annotations

import time
import os
import ipaddress
from collections import defaultdict, deque
from typing import Deque

from fastapi import Request
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.responses import JSONResponse, Response

from app.config import settings


def _is_production() -> bool:
    return settings.ENVIRONMENT.lower() in {"prod", "production"} or bool(os.environ.get("DB_PASSWORD"))


class SecurityHeadersMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        response = await call_next(request)
        response.headers.setdefault("X-Content-Type-Options", "nosniff")
        response.headers.setdefault("X-Frame-Options", "DENY")
        response.headers.setdefault("Referrer-Policy", "strict-origin-when-cross-origin")
        response.headers.setdefault("Permissions-Policy", "camera=(), microphone=(), geolocation=()")
        response.headers.setdefault("Cross-Origin-Opener-Policy", "same-origin")
        response.headers.setdefault("Content-Security-Policy", "default-src 'self'; base-uri 'self'; frame-ancestors 'none'; form-action 'self'; object-src 'none'")
        if _is_production():
            response.headers.setdefault("Strict-Transport-Security", "max-age=31536000; includeSubDomains")
        return response


class RequestSizeLimitMiddleware(BaseHTTPMiddleware):
    async def dispatch(self, request: Request, call_next) -> Response:
        content_length = request.headers.get("content-length")
        if content_length:
            try:
                size = int(content_length)
            except ValueError:
                size = 0
            limit_mb = settings.MAX_REQUEST_BODY_MB
            if request.url.path == "/api/materials/upload":
                # Multipart needs a little boundary overhead; the route itself
                # enforces the exact material-file limit while streaming.
                limit_mb = settings.MATERIAL_UPLOAD_MAX_MB + 5
            elif request.url.path in {
                "/api/images/upload",
                "/api/images/upload-background",
                "/api/images/upload-batch",
            }:
                # Do not let an image request reserve the much larger material
                # upload allowance before the image route can reject it.
                limit_mb = settings.IMAGE_UPLOAD_MAX_MB + 5
            if limit_mb > 0 and size > limit_mb * 1024 * 1024:
                return JSONResponse(status_code=413, content={"detail": f"请求体超过限制 ({limit_mb}MB)"})
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, Deque[float]] = defaultdict(deque)
        self._last_cleanup = 0.0

    def _cleanup_expired_buckets(self, now: float) -> None:
        if now - self._last_cleanup < 60 and len(self._hits) < settings.RATE_LIMIT_MAX_BUCKETS:
            return
        self._last_cleanup = now
        for bucket, window in list(self._hits.items()):
            while window and now - window[0] > 60:
                window.popleft()
            if not window:
                self._hits.pop(bucket, None)

    async def dispatch(self, request: Request, call_next) -> Response:
        enabled = settings.RATE_LIMIT_ENABLED or _is_production()
        if not enabled or request.url.path in {"/health", "/"}:
            return await call_next(request)

        now = time.monotonic()
        self._cleanup_expired_buckets(now)
        client = get_request_client_ip(request)
        path = request.url.path
        bucket = f"{client}:auth" if path.startswith("/api/auth/") else f"{client}:api"
        limit = settings.AUTH_RATE_LIMIT_PER_MINUTE if path.startswith("/api/auth/") else settings.RATE_LIMIT_PER_MINUTE
        if bucket not in self._hits and len(self._hits) >= settings.RATE_LIMIT_MAX_BUCKETS:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
        window = self._hits[bucket]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
        window.append(now)
        return await call_next(request)


def _normalized_ip(value: str | None) -> str | None:
    raw = str(value or "").strip()
    if not raw:
        return None
    try:
        return str(ipaddress.ip_address(raw))
    except ValueError:
        return None


def get_request_client_ip(request: Request) -> str:
    """Return the actual client IP only when the deployment opted into proxies.

    `X-Forwarded-For` is user-controlled on a directly reachable backend, so
    it must never be consumed unless the deployment explicitly says that the
    backend is behind a fixed number of trusted reverse proxies.
    """
    direct = _normalized_ip(request.client.host if request.client else None) or "unknown"
    hops = int(settings.TRUSTED_PROXY_HOPS or 0)
    if not settings.TRUST_PROXY_HEADERS or hops < 1:
        return direct

    forwarded = [
        candidate
        for candidate in (_normalized_ip(part) for part in request.headers.get("x-forwarded-for", "").split(","))
        if candidate is not None
    ]
    if len(forwarded) < hops:
        return direct
    return forwarded[-hops]
