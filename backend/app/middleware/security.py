"""Production-facing safety middleware."""
from __future__ import annotations

import time
import os
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
            if request.url.path in {"/api/materials/upload", "/api/images/upload", "/api/images/upload-batch"}:
                limit_mb = settings.MATERIAL_UPLOAD_MAX_MB + 5
            if limit_mb > 0 and size > limit_mb * 1024 * 1024:
                return JSONResponse(status_code=413, content={"detail": f"请求体超过限制 ({limit_mb}MB)"})
        return await call_next(request)


class RateLimitMiddleware(BaseHTTPMiddleware):
    def __init__(self, app):
        super().__init__(app)
        self._hits: dict[str, Deque[float]] = defaultdict(deque)

    async def dispatch(self, request: Request, call_next) -> Response:
        enabled = settings.RATE_LIMIT_ENABLED or _is_production()
        if not enabled or request.url.path in {"/health", "/"}:
            return await call_next(request)

        now = time.monotonic()
        client = request.client.host if request.client else "unknown"
        path = request.url.path
        bucket = f"{client}:auth" if path.startswith("/api/auth/") else f"{client}:api"
        limit = settings.AUTH_RATE_LIMIT_PER_MINUTE if path.startswith("/api/auth/") else settings.RATE_LIMIT_PER_MINUTE
        window = self._hits[bucket]
        while window and now - window[0] > 60:
            window.popleft()
        if len(window) >= limit:
            return JSONResponse(status_code=429, content={"detail": "请求过于频繁，请稍后再试"})
        window.append(now)
        return await call_next(request)
