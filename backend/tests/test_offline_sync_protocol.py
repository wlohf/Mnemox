"""Focused regression tests for the offline CRUD synchronization contract."""
from __future__ import annotations

import json
import tempfile
import unittest
import uuid
from pathlib import Path

from fastapi import HTTPException
from fastapi.responses import JSONResponse
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

import app.models  # noqa: F401
from app.database import Base
from app.models.anki import AnkiCard
from app.models.sync import SyncReceipt
from app.models.user import User
from app.routers.anki import AnkiCardCreate, AnkiCardUpdate, create_card, delete_card, update_card


class OfflineSyncProtocolTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'sync.sqlite3'}", future=True
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.owner = await self._user("sync-owner")
        self.other = await self._user("sync-other")

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _user(self, username: str) -> User:
        async with self.sessions() as session:
            user = User(username=username, email=f"{username}@example.test", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
        return User(id=user_id, username=username, email=f"{username}@example.test", hashed_password="hash", is_active=True)

    async def _create(self, user: User, key: str | None = None):
        async with self.sessions() as session:
            result = await create_card(
                AnkiCardCreate(front="front", back="back", tags="tag"),
                idempotency_key=key,
                db=session,
                current_user=user,
            )
            await session.commit()
            return result

    async def test_response_loss_replays_same_receipt_and_user_scope_isolated(self):
        key = str(uuid.uuid4())
        first = await self._create(self.owner, key)
        self.assertEqual(first["sync_version"], 1)
        self.assertTrue(first["created_at"].endswith("Z"))
        self.assertTrue(first["updated_at"].endswith("Z"))

        async with self.sessions() as session:
            replay = await create_card(
                AnkiCardCreate(front="front", back="back", tags="tag"),
                idempotency_key=key,
                db=session,
                current_user=self.owner,
            )
            self.assertIsInstance(replay, JSONResponse)
            self.assertEqual(json.loads(replay.body), first)
            self.assertEqual(replay.status_code, 200)
            self.assertEqual(await session.scalar(select(func.count(AnkiCard.id))), 1)

        # The same UUID is independent for a distinct authenticated user.
        second_user = await self._create(self.other, key)
        self.assertNotEqual(second_user["id"], first["id"])

    async def test_key_reuse_and_delete_replay(self):
        key = str(uuid.uuid4())
        card = await self._create(self.owner, key)
        async with self.sessions() as session:
            with self.assertRaises(HTTPException) as caught:
                await create_card(
                    AnkiCardCreate(front="different", back="body"),
                    idempotency_key=key,
                    db=session,
                    current_user=self.owner,
                )
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(caught.exception.detail["code"], "IDEMPOTENCY_KEY_REUSED")

        delete_key = str(uuid.uuid4())
        async with self.sessions() as session:
            deleted = await delete_card(
                card["id"], if_match='"1"', idempotency_key=delete_key, db=session, current_user=self.owner
            )
            self.assertEqual(deleted, {"ok": True})
            await session.commit()

        async with self.sessions() as session:
            replay = await delete_card(
                card["id"], if_match='"1"', idempotency_key=delete_key, db=session, current_user=self.owner
            )
            self.assertIsInstance(replay, JSONResponse)
            self.assertEqual(json.loads(replay.body), {"ok": True})
            self.assertEqual(await session.scalar(select(func.count(AnkiCard.id))), 0)
            self.assertEqual(await session.scalar(select(func.count(SyncReceipt.id))), 2)

    async def test_stale_if_match_and_legacy_writer_cas_conflict(self):
        card = await self._create(self.owner)
        async with self.sessions() as session:
            with self.assertRaises(HTTPException) as caught:
                await update_card(
                    card["id"], AnkiCardUpdate(note="stale"), if_match='"0"', db=session, current_user=self.owner
                )
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(caught.exception.detail["code"], "SYNC_CONFLICT")

        # A pre-existing writer that does not send If-Match still updates through
        # SQLAlchemy's version_id_col, so the stale sync session cannot overwrite it.
        async with self.sessions() as stale_session, self.sessions() as legacy_session:
            stale = await stale_session.get(AnkiCard, card["id"])
            legacy = await legacy_session.get(AnkiCard, card["id"])
            assert stale is not None and legacy is not None
            legacy.note = "legacy writer"
            await legacy_session.commit()
            with self.assertRaises(HTTPException) as caught:
                await update_card(
                    card["id"], AnkiCardUpdate(note="sync writer"), if_match='"1"',
                    db=stale_session, current_user=self.owner,
                )
            self.assertEqual(caught.exception.status_code, 409)
            self.assertEqual(caught.exception.detail["code"], "SYNC_CONFLICT")
            await stale_session.rollback()

    async def test_schema_registers_receipt_and_all_sync_versions(self):
        self.assertIn("sync_receipts", Base.metadata.tables)
        for table in ("notes", "goals", "tasks", "anki_cards", "wrong_questions"):
            self.assertIn("sync_version", Base.metadata.tables[table].c)


if __name__ == "__main__":
    unittest.main()
