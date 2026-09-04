"""Stage 5 sparse Knowledge index contracts."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.knowledge import Claim, ClaimEvidence, KnowledgeSource, KnowledgeSourceRevision, KnowledgeUnit
from app.models.user import User
from app.services.sparse_knowledge_index import (
    AutoSparseKnowledgeIndex,
    ReferenceSparseKnowledgeIndex,
    SqliteFts5SparseKnowledgeIndex,
    create_sparse_knowledge_index,
    mark_sparse_knowledge_dirty,
)


class SparseKnowledgeIndexTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'sparse.db'}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _user(self, db, name: str) -> User:
        row = User(username=name, email=f"{name}@example.test", hashed_password="hash")
        db.add(row)
        await db.flush()
        return row

    async def _claim(self, db, *, user_id: int, record_id: int, statement: str, source_status: str = "active") -> tuple[KnowledgeSource, Claim]:
        source = KnowledgeSource(
            user_id=user_id,
            source_type="note",
            source_record_id=record_id,
            source_key=f"note:{record_id}",
            title_snapshot=f"Source {record_id}",
            status=source_status,
            current_revision=1,
        )
        db.add(source)
        await db.flush()
        revision = KnowledgeSourceRevision(
            user_id=user_id,
            knowledge_source_id=int(source.id),
            revision=1,
            content_hash=hashlib.sha256(statement.encode()).hexdigest(),
            title_snapshot=source.title_snapshot,
            status="current",
        )
        db.add(revision)
        await db.flush()
        unit = KnowledgeUnit(
            user_id=user_id,
            source_revision_id=int(revision.id),
            unit_type="note_body",
            ordinal=0,
            text=statement,
            text_hash=hashlib.sha256(statement.encode()).hexdigest(),
            locator={},
        )
        claim = Claim(
            user_id=user_id,
            source_revision_id=int(revision.id),
            statement=statement,
            fingerprint=hashlib.sha256(statement.casefold().encode()).hexdigest(),
            confidence=1.0,
            derivation_type="manual",
            review_status="confirmed",
            lifecycle_status="active",
        )
        db.add_all((unit, claim))
        await db.flush()
        db.add(ClaimEvidence(
            user_id=user_id,
            claim_id=int(claim.id),
            knowledge_unit_id=int(unit.id),
            excerpt=statement,
            char_start=0,
            char_end=len(statement),
            locator={},
            grounding_method="manual",
            confidence=1.0,
        ))
        await db.flush()
        return source, claim

    async def test_fts5_preserves_reference_hits_for_chinese_and_english(self):
        async with self.sessions() as db:
            owner = await self._user(db, "sparse-owner")
            stranger = await self._user(db, "sparse-stranger")
            _, chinese = await self._claim(db, user_id=int(owner.id), record_id=1, statement="服务账号只应获得完成任务所需的最小权限。")
            _, english = await self._claim(db, user_id=int(owner.id), record_id=2, statement="A feedback loop can amplify the next cycle.")
            _, foreign = await self._claim(db, user_id=int(stranger.id), record_id=3, statement="最小权限 feedback loop private sentinel")
            await db.commit()

            reference = ReferenceSparseKnowledgeIndex(db)
            fts = SqliteFts5SparseKnowledgeIndex(db)
            await fts.rebuild_user(user_id=int(owner.id))
            await fts.rebuild_user(user_id=int(stranger.id))

            for query, expected in (("最小权限", int(chinese.id)), ("feedback loop", int(english.id))):
                reference_hits = await reference.search(user_id=int(owner.id), text=query, top_k=10)
                fts_hits = await fts.search(user_id=int(owner.id), text=query, top_k=10)
                self.assertEqual([row.claim_id for row in fts_hits], [row.claim_id for row in reference_hits])
                self.assertIn(expected, [row.claim_id for row in fts_hits])
                self.assertNotIn(int(foreign.id), [row.claim_id for row in fts_hits])

    async def test_fts5_delete_and_rebuild_follow_canonical_visibility(self):
        async with self.sessions() as db:
            owner = await self._user(db, "sparse-lifecycle")
            source, claim = await self._claim(db, user_id=int(owner.id), record_id=11, statement="遗忘曲线最初下降较快，之后变慢。")
            await db.commit()
            fts = SqliteFts5SparseKnowledgeIndex(db)
            await fts.rebuild_user(user_id=int(owner.id))
            self.assertEqual([row.claim_id for row in await fts.search(user_id=int(owner.id), text="遗忘曲线", top_k=5)], [int(claim.id)])

            await fts.delete_source(user_id=int(owner.id), source_key=str(source.source_key))
            self.assertEqual(await fts.search(user_id=int(owner.id), text="遗忘曲线", top_k=5), [])

            source.status = "deleted"
            await db.commit()
            await fts.rebuild_user(user_id=int(owner.id))
            self.assertEqual(await fts.search(user_id=int(owner.id), text="遗忘曲线", top_k=5), [])

    async def test_fts5_search_incrementally_syncs_dirty_claim_without_user_rebuild(self):
        async with self.sessions() as db:
            owner = await self._user(db, "sparse-auto-sync")
            _, first = await self._claim(db, user_id=int(owner.id), record_id=21, statement="机会成本用于比较被放弃的替代方案。")
            await db.commit()
            fts = SqliteFts5SparseKnowledgeIndex(db)

            await fts.rebuild_user(user_id=int(owner.id))
            self.assertEqual(
                [row.claim_id for row in await fts.search(user_id=int(owner.id), text="机会成本", top_k=5)],
                [int(first.id)],
            )

            _, second = await self._claim(db, user_id=int(owner.id), record_id=22, statement="反馈回路会让系统输出影响下一轮输入。")
            await db.commit()
            await fts.mark_claim_dirty(user_id=int(owner.id), claim_id=int(second.id))

            original_rebuild = fts.rebuild_user
            fts.rebuild_user = AsyncMock(side_effect=original_rebuild)
            self.assertEqual(
                [row.claim_id for row in await fts.search(user_id=int(owner.id), text="反馈回路", top_k=5)],
                [int(second.id)],
            )
            fts.rebuild_user.assert_not_awaited()

    async def test_best_effort_dirty_failure_does_not_abort_canonical_transaction(self):
        async with self.sessions() as db:
            owner = await self._user(db, "sparse-savepoint")
            _, claim = await self._claim(db, user_id=int(owner.id), record_id=31, statement="事务中的规范 Claim 必须继续可提交。")
            with patch.object(settings, "KNOWLEDGE_SPARSE_BACKEND", "postgres_fts"):
                marked = await mark_sparse_knowledge_dirty(
                    db,
                    user_id=int(owner.id),
                    claim_id=int(claim.id),
                )
            self.assertFalse(marked)
            claim.statement = "即使可选 Sparse 投影失败，规范 Claim 事务也不能被中止。"
            await db.commit()

        async with self.sessions() as db:
            stored = await db.scalar(select(Claim).where(Claim.id == int(claim.id)))
            self.assertEqual(stored.statement, "即使可选 Sparse 投影失败，规范 Claim 事务也不能被中止。")

    async def test_factory_auto_selects_sqlite_with_reference_rollback(self):
        async with self.sessions() as db:
            with patch.object(settings, "KNOWLEDGE_SPARSE_BACKEND", "auto"):
                automatic = create_sparse_knowledge_index(db)
                self.assertIsInstance(automatic, AutoSparseKnowledgeIndex)
                self.assertIsInstance(automatic.primary, SqliteFts5SparseKnowledgeIndex)
            with patch.object(settings, "KNOWLEDGE_SPARSE_BACKEND", "reference"):
                self.assertIsInstance(create_sparse_knowledge_index(db), ReferenceSparseKnowledgeIndex)
            with patch.object(settings, "KNOWLEDGE_SPARSE_BACKEND", "sqlite_fts5"):
                self.assertIsInstance(create_sparse_knowledge_index(db), SqliteFts5SparseKnowledgeIndex)

    async def test_auto_backend_falls_back_to_reference_search_after_primary_failure(self):
        async with self.sessions() as db:
            owner = await self._user(db, "auto-fallback-owner")
            _, claim = await self._claim(
                db,
                user_id=int(owner.id),
                record_id=41,
                statement="检索练习要求主动从记忆中提取答案。",
            )
            await db.commit()
            automatic = AutoSparseKnowledgeIndex(db, SqliteFts5SparseKnowledgeIndex(db))
            automatic.primary.search = AsyncMock(side_effect=RuntimeError("fts unavailable"))
            hits = await automatic.search(
                user_id=int(owner.id),
                text="检索练习",
                top_k=5,
            )
            self.assertEqual([row.claim_id for row in hits], [int(claim.id)])
