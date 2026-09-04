"""Regression tests for public security boundaries introduced in 2026-08."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path

import httpx
from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine
from starlette.requests import Request

from app.config import settings
from app.database import Base, get_db
from app.main import app, get_uploaded_file
from app.middleware.security import get_request_client_ip
from app.routers.rag import _require_rag_settings_manager
from app.models.user import User


def _request(*, client: str, forwarded_for: str = "") -> Request:
    headers = [] if not forwarded_for else [(b"x-forwarded-for", forwarded_for.encode("ascii"))]
    return Request({"type": "http", "method": "GET", "path": "/", "headers": headers, "client": (client, 12345)})


class TrustedProxyTests(unittest.TestCase):
    def setUp(self):
        self.original_enabled = settings.TRUST_PROXY_HEADERS
        self.original_hops = settings.TRUSTED_PROXY_HOPS

    def tearDown(self):
        settings.TRUST_PROXY_HEADERS = self.original_enabled
        settings.TRUSTED_PROXY_HOPS = self.original_hops

    def test_forwarded_header_is_ignored_by_default(self):
        settings.TRUST_PROXY_HEADERS = False
        settings.TRUSTED_PROXY_HOPS = 0
        self.assertEqual(get_request_client_ip(_request(client="172.20.0.4", forwarded_for="203.0.113.10")), "172.20.0.4")

    def test_public_deployment_uses_client_before_two_trusted_proxies(self):
        settings.TRUST_PROXY_HEADERS = True
        settings.TRUSTED_PROXY_HOPS = 2
        self.assertEqual(
            get_request_client_ip(_request(client="172.20.0.4", forwarded_for="198.51.100.7, 172.20.0.2")),
            "198.51.100.7",
        )

    def test_short_or_invalid_forwarded_header_falls_back_to_direct_peer(self):
        settings.TRUST_PROXY_HEADERS = True
        settings.TRUSTED_PROXY_HOPS = 2
        self.assertEqual(get_request_client_ip(_request(client="172.20.0.4", forwarded_for="not-an-ip")), "172.20.0.4")


class RAGSettingsAccessTests(unittest.TestCase):
    def setUp(self):
        self.original_environment = settings.ENVIRONMENT
        self.original_admins = settings.RAG_SETTINGS_ADMIN_USERNAMES
        settings.ENVIRONMENT = "production"
        settings.RAG_SETTINGS_ADMIN_USERNAMES = "rag-admin, second-admin"

    def tearDown(self):
        settings.ENVIRONMENT = self.original_environment
        settings.RAG_SETTINGS_ADMIN_USERNAMES = self.original_admins

    def test_only_explicit_public_rag_admin_can_change_global_setting(self):
        _require_rag_settings_manager(User(username="RAG-ADMIN"))
        with self.assertRaises(HTTPException) as caught:
            _require_rag_settings_manager(User(username="learner"))
        self.assertEqual(caught.exception.status_code, 403)


class BrowserSessionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "security.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

        sessionmaker = self.sessionmaker

        async def _override_get_db():
            async with sessionmaker() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = _override_get_db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")

    async def asyncTearDown(self):
        await self.client.aclose()
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _register_and_login(self, username: str = "secure_user") -> str:
        registered = await self.client.post(
            "/api/auth/register",
            json={"username": username, "email": f"{username}@example.com", "password": "safe-password-123"},
        )
        self.assertEqual(registered.status_code, 200, registered.text)
        login = await self.client.post("/api/auth/login", data={"username": username, "password": "safe-password-123"})
        self.assertEqual(login.status_code, 200, login.text)
        self.assertIn("httponly", login.headers.get("set-cookie", "").lower())
        self.assertIn("samesite=lax", login.headers.get("set-cookie", "").lower())
        return str(login.json()["access_token"])

    async def test_cookie_authentication_and_logout_revoke_existing_bearer_token(self):
        token = await self._register_and_login()
        self.assertEqual((await self.client.get("/api/auth/me")).status_code, 200)

        logout = await self.client.post("/api/auth/logout")
        self.assertEqual(logout.status_code, 200, logout.text)
        self.assertEqual((await self.client.get("/api/auth/me", headers={"Authorization": f"Bearer {token}"})).status_code, 401)

    async def test_registration_rejects_short_password(self):
        response = await self.client.post(
            "/api/auth/register",
            json={"username": "short_password", "email": "short@example.com", "password": "12345678"},
        )
        self.assertEqual(response.status_code, 400)
        self.assertIn("不能小于", response.text)

    async def test_known_account_is_persistently_throttled_after_repeated_failures(self):
        await self._register_and_login("throttled_user")
        await self.client.post("/api/auth/logout")
        for _ in range(settings.AUTH_ACCOUNT_MAX_FAILURES):
            rejected = await self.client.post(
                "/api/auth/login",
                data={"username": "throttled_user", "password": "wrong-password"},
            )
            self.assertEqual(rejected.status_code, 401)

        locked = await self.client.post(
            "/api/auth/login",
            data={"username": "throttled_user", "password": "safe-password-123"},
        )
        self.assertEqual(locked.status_code, 429)
        self.assertIn("retry-after", locked.headers)

    async def test_upload_endpoint_does_not_accept_jwt_in_query_string(self):
        request = Request({"type": "http", "method": "GET", "path": "/api/uploads/x", "query_string": b"token=legacy-token", "headers": []})
        with self.assertRaises(HTTPException) as caught:
            await get_uploaded_file("missing.png", request)
        self.assertEqual(caught.exception.status_code, 401)
