"""PostgreSQL acceptance for the Stage 5 native sparse projection."""
from __future__ import annotations

import hashlib
import os
import unittest

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.knowledge import Claim, ClaimEvidence, KnowledgeSource, KnowledgeSourceRevision, KnowledgeUnit
from app.models.user import User
from app.services.sparse_knowledge_index import PostgresFtsSparseKnowledgeIndex, ReferenceSparseKnowledgeIndex


POSTGRES_URL = os.environ.get("MNEMOX_TEST_POSTGRES_URL", "").strip()


@unittest.skipUnless(POSTGRES_URL, "MNEMOX_TEST_POSTGRES_URL is required")
class PostgresSparseKnowledgeIndexTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.engine = create_async_engine(POSTGRES_URL)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.drop_all)
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()

    async def _user(self, db, name: str) -> User:
        row = User(username=name, email=f"{name}@example.test", hashed_password="hash")
        db.add(row)
        await db.flush()
        return row

    async def _claim(self, db, *, user_id: int, record_id: int, statement: str):
        source = KnowledgeSource(
            user_id=user_id, source_type="note", source_record_id=record_id,
            source_key=f"note:{record_id}", title_snapshot=f"Source {record_id}",
            status="active", current_revision=1,
        )
        db.add(source)
        await db.flush()
        revision = KnowledgeSourceRevision(
            user_id=user_id, knowledge_source_id=int(source.id), revision=1,
            content_hash=hashlib.sha256(statement.encode()).hexdigest(),
            title_snapshot=source.title_snapshot, status="current",
        )
        db.add(revision)
        await db.flush()
        unit = KnowledgeUnit(
            user_id=user_id, source_revision_id=int(revision.id), unit_type="note_body",
            ordinal=0, text=statement, text_hash=hashlib.sha256(statement.encode()).hexdigest(), locator={},
        )
        claim = Claim(
            user_id=user_id, source_revision_id=int(revision.id), statement=statement,
            fingerprint=hashlib.sha256(statement.casefold().encode()).hexdigest(), confidence=1.0,
            derivation_type="manual", review_status="confirmed", lifecycle_status="active",
        )
        db.add_all((unit, claim))
        await db.flush()
        db.add(ClaimEvidence(
            user_id=user_id, claim_id=int(claim.id), knowledge_unit_id=int(unit.id),
            excerpt=statement, char_start=0, char_end=len(statement), locator={},
            grounding_method="manual", confidence=1.0,
        ))
        await db.flush()
        return source, claim

    async def test_postgres_fts_matches_reference_for_bilingual_queries_and_lifecycle(self):
        async with self.sessions() as db:
            owner = await self._user(db, "postgres-sparse-owner")
            stranger = await self._user(db, "postgres-sparse-stranger")
            source_cn, chinese = await self._claim(db, user_id=int(owner.id), record_id=1, statement="服务账号只应获得完成任务所需的最小权限。")
            _, english = await self._claim(db, user_id=int(owner.id), record_id=2, statement="A feedback loop can amplify the next cycle.")
            _, foreign = await self._claim(db, user_id=int(stranger.id), record_id=3, statement="最小权限 feedback loop private sentinel")
            await db.commit()

            reference = ReferenceSparseKnowledgeIndex(db)
            postgres = PostgresFtsSparseKnowledgeIndex(db)
            health = await postgres.health()
            self.assertTrue(health["ok"])
            self.assertFalse(health["extension_required"])
            await postgres.rebuild_user(user_id=int(owner.id))
            await postgres.rebuild_user(user_id=int(stranger.id))
            await db.commit()

            for query, expected in (("最小权限", int(chinese.id)), ("feedback loop", int(english.id))):
                expected_ids = [row.claim_id for row in await reference.search(user_id=int(owner.id), text=query, top_k=10)]
                actual_ids = [row.claim_id for row in await postgres.search(user_id=int(owner.id), text=query, top_k=10)]
                self.assertEqual(actual_ids, expected_ids)
                self.assertIn(expected, actual_ids)
                self.assertNotIn(int(foreign.id), actual_ids)

            await postgres.delete_source(user_id=int(owner.id), source_key=str(source_cn.source_key))
            self.assertEqual(await postgres.search(user_id=int(owner.id), text="最小权限", top_k=5), [])
            source_cn.status = "deleted"
            await db.commit()
            self.assertEqual(await postgres.search(user_id=int(owner.id), text="最小权限", top_k=5), [])
