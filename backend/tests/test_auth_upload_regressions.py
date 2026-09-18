"""Focused regressions for bcrypt limits and upload ownership boundaries."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path, PurePosixPath

import httpx
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
from app.main import _is_upload_owned_by_user, app
from app.models.material import Material
from app.models.user import User
from app.utils.paths import get_uploads_dir


class AuthPasswordRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'auth.sqlite3'}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

        sessionmaker = self.sessionmaker

        async def override_get_db():
            async with sessionmaker() as session:
                try:
                    yield session
                    await session.commit()
                except Exception:
                    await session.rollback()
                    raise

        app.dependency_overrides[get_db] = override_get_db
        self.client = httpx.AsyncClient(transport=httpx.ASGITransport(app=app), base_url="http://testserver")

    async def asyncTearDown(self) -> None:
        await self.client.aclose()
        app.dependency_overrides.pop(get_db, None)
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def test_registration_rejects_passwords_over_bcrypt_utf8_limit(self) -> None:
        for username, password in (("ascii_limit", "a" * 73), ("unicode_limit", "密" * 25)):
            response = await self.client.post(
                "/api/auth/register",
                json={"username": username, "email": f"{username}@example.com", "password": password},
            )
            self.assertEqual(response.status_code, 400, response.text)
            self.assertIn("72", response.text)

    async def test_valid_login_and_malformed_stored_hash_do_not_return_server_error(self) -> None:
        registered = await self.client.post(
            "/api/auth/register",
            json={"username": "valid_login", "email": "valid@example.com", "password": "safe-password-123"},
        )
        self.assertEqual(registered.status_code, 200, registered.text)
        login = await self.client.post("/api/auth/login", data={"username": "valid_login", "password": "safe-password-123"})
        self.assertEqual(login.status_code, 200, login.text)
        for password in ("a" * 73, "密" * 25):
            rejected = await self.client.post("/api/auth/login", data={"username": "valid_login", "password": password})
            self.assertEqual(rejected.status_code, 401, rejected.text)

        async with self.sessionmaker() as session:
            session.add(User(username="broken_hash", email="broken@example.com", hashed_password="not-a-bcrypt-hash"))
            await session.commit()

        malformed = await self.client.post("/api/auth/login", data={"username": "broken_hash", "password": "safe-password-123"})
        self.assertEqual(malformed.status_code, 401, malformed.text)

    async def test_expected_user_header_rejects_shared_cookie_account_switch(self) -> None:
        users = []
        for username in ("cookie_alice", "cookie_bob"):
            response = await self.client.post(
                "/api/auth/register",
                json={"username": username, "email": f"{username}@example.com", "password": "safe-password-123"},
            )
            self.assertEqual(response.status_code, 200, response.text)
            users.append(response.json()["id"])
        response = await self.client.post(
            "/api/auth/login", data={"username": "cookie_bob", "password": "safe-password-123"},
        )
        self.assertEqual(response.status_code, 200, response.text)
        denied = await self.client.post(
            "/api/notes", json={"title": "Alice private note"},
            headers={"X-Mnemox-User-Id": str(users[0])},
        )
        self.assertEqual(denied.status_code, 409, denied.text)
        self.assertEqual(denied.json()["detail"]["code"], "SESSION_USER_MISMATCH")
        accepted = await self.client.get("/api/auth/me", headers={"X-Mnemox-User-Id": str(users[1])})
        self.assertEqual(accepted.status_code, 200, accepted.text)
        self.assertEqual(accepted.json()["id"], users[1])
        compatible = await self.client.get("/api/auth/me")
        self.assertEqual(compatible.status_code, 200, compatible.text)

class UploadOwnershipRegressionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'uploads.sqlite3'}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _user(self, username: str) -> int:
        async with self.sessionmaker() as session:
            user = User(username=username, email=f"{username}@example.com", hashed_password="hash")
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return user_id

    async def test_legacy_images_fail_closed_and_user_image_directory_remains_owned(self) -> None:
        user_id = await self._user("image_owner")
        async with self.sessionmaker() as session:
            self.assertFalse(await _is_upload_owned_by_user(session, user_id, PurePosixPath("images/legacy.png")))
            self.assertTrue(await _is_upload_owned_by_user(session, user_id, PurePosixPath(f"images/{user_id}/owned.png")))
            self.assertFalse(await _is_upload_owned_by_user(session, user_id + 1, PurePosixPath(f"images/{user_id}/owned.png")))

    async def test_material_ownership_requires_exact_normalized_path(self) -> None:
        owner_id = await self._user("path_owner")
        outsider_id = await self._user("path_outsider")
        absolute_path = get_uploads_dir().resolve() / "absolute.pdf"
        async with self.sessionmaker() as session:
            session.add_all(
                [
                    Material(user_id=owner_id, title="owner nested", file_path="data/uploads/owner/report.pdf", content="x"),
                    Material(user_id=owner_id, title="owner absolute", file_path=str(absolute_path), content="x"),
                    Material(user_id=outsider_id, title="outsider collision", file_path="data/uploads/other/report.pdf", content="x"),
                ]
            )
            await session.commit()

        async with self.sessionmaker() as session:
            self.assertTrue(await _is_upload_owned_by_user(session, owner_id, PurePosixPath("owner/report.pdf")))
            self.assertTrue(await _is_upload_owned_by_user(session, owner_id, PurePosixPath("absolute.pdf")))
            self.assertFalse(await _is_upload_owned_by_user(session, owner_id, PurePosixPath("report.pdf")))
            self.assertFalse(await _is_upload_owned_by_user(session, outsider_id, PurePosixPath("owner/report.pdf")))
            self.assertTrue(await _is_upload_owned_by_user(session, outsider_id, PurePosixPath("other/report.pdf")))


if __name__ == "__main__":
    unittest.main()
