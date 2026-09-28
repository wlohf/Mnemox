"""Durable material ingestion, update, deletion, recovery, and tenant boundaries."""
from __future__ import annotations

import asyncio
import hashlib
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import event, func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.chat import ChatProject, ChatProjectMaterial
from app.models.material import Material
from app.models.retrieval import RetrievalProjection, RetrievalProjectionChunk
from app.models.user import User
from app.services.material_retrieval_backend import KeywordMaterialRetrievalBackend, MaterialSearchScope
from app.services.retrieval_projection_service import (
    RetrievalProjectionService,
    serialized_retrieval_configuration_change,
)


class _Collection:
    def __init__(self) -> None:
        self.rows: dict[tuple[int, int], list[str]] = {}
        self.deleted_filters: list[dict] = []

    def delete(self, *, where: dict) -> None:
        self.deleted_filters.append(where)
        user_id = int(where["user_id"])
        for key in list(self.rows):
            if key[0] == user_id:
                del self.rows[key]


class _Rag:
    def __init__(self, *, embedding_enabled: bool = True) -> None:
        self.embedding_enabled = embedding_enabled
        self._collection = _Collection()
        self._current_model = "test-embedding-v1"
        self._current_base_url = "https://embedding.invalid/v1"
        self._chunk_size = 128
        self._chunk_overlap = 0
        self.index_calls = 0
        self.fail_index = False
        self.fail_remove = False
        self.last_error = ""

    async def initialize(self) -> None:
        return None

    async def get_status(self, _user_id: int) -> dict:
        return {
            "embedding_enabled": self.embedding_enabled,
            "last_error": self.last_error,
        }

    async def index_material(self, *, material_id: int, user_id: int, content: str, **_kwargs) -> int:
        self.index_calls += 1
        await self.remove_material(material_id, user_id=user_id)
        self._collection.rows[(int(user_id), int(material_id))] = content.split("|")
        if self.fail_index:
            self.last_error = "embedding endpoint unavailable"
            return 0
        return len(content.split("|"))

    async def remove_material(self, material_id: int, user_id: int | None = None) -> None:
        if self.fail_remove:
            raise RuntimeError("vector store unavailable")
        self._collection.rows.pop((int(user_id or 0), int(material_id)), None)


class _CoordinatedRag(_Rag):
    def __init__(self) -> None:
        super().__init__()
        self.old_started = asyncio.Event()
        self.release_old = asyncio.Event()
        self.started_contents: list[str] = []

    async def index_material(self, *, content: str, **kwargs) -> int:
        self.started_contents.append(content)
        if content.startswith("obsolete"):
            self.old_started.set()
            await self.release_old.wait()
        return await super().index_material(content=content, **kwargs)


class RetrievalProjectionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'lifecycle.db'}")
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.rag = _Rag()
        self.splitter = patch(
            "app.services.retrieval_projection_service._chunk_material_text",
            side_effect=lambda content: [part.strip() for part in content.split("|") if part.strip()],
        )
        self.splitter.start()

    async def asyncTearDown(self) -> None:
        self.splitter.stop()
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _user(self, username: str) -> int:
        async with self.sessions() as db:
            user = User(username=username, email=f"{username}@example.test", hashed_password="hash")
            db.add(user)
            await db.commit()
            return int(user.id)

    async def _material(self, user_id: int, title: str, content: str) -> int:
        async with self.sessions() as db:
            material = Material(
                user_id=user_id,
                title=title,
                content=content,
                content_hash=hashlib.sha256(content.encode()).hexdigest(),
                content_status="extracted",
                file_type="md",
            )
            db.add(material)
            await db.commit()
            return int(material.id)

    async def test_ingest_persists_versioned_sql_manifest_and_is_idempotent(self) -> None:
        user_id = await self._user("ingest-owner")
        material_id = await self._material(user_id, "RAG", "RRF ranks results|reranker scores pairs")

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            material = await db.get(Material, material_id)
            first = await service.ingest(material, user_id=user_id)
            second = await service.ingest(material, user_id=user_id)
            chunks = list((await db.scalars(select(RetrievalProjectionChunk))).all())

        self.assertEqual(first["status"], "ready")
        self.assertEqual(first["source_version"], 1)
        self.assertEqual(first["indexed_version"], 1)
        self.assertEqual(first["chunk_count"], 2)
        self.assertEqual(first["vector_chunk_count"], 2)
        self.assertEqual(second["attempt_count"], 1)
        self.assertEqual(self.rag.index_calls, 1)
        self.assertEqual([chunk.chunk_index for chunk in chunks], [0, 1])
        self.assertEqual([chunk.source_version for chunk in chunks], [1, 1])

    async def test_projection_identity_uses_atomic_insert_on_supported_database(self) -> None:
        user_id = await self._user("atomic-projection-owner")
        material_id = await self._material(user_id, "Atomic", "one version")
        statements: list[str] = []

        def capture_statement(_conn, _cursor, statement, _parameters, _context, _executemany):
            statements.append(str(statement))

        event.listen(self.engine.sync_engine, "before_cursor_execute", capture_statement)
        try:
            async with self.sessions() as db:
                service = RetrievalProjectionService(db, rag=self.rag)
                material = await db.get(Material, material_id)
                first = await service.ingest(material, user_id=user_id)
                second = await service.ingest(material, user_id=user_id, force=True)
                projection_count = await db.scalar(
                    select(func.count()).select_from(RetrievalProjection)
                )
        finally:
            event.remove(self.engine.sync_engine, "before_cursor_execute", capture_statement)

        projection_inserts = [
            statement.upper()
            for statement in statements
            if "INSERT INTO RETRIEVAL_PROJECTIONS" in statement.upper()
        ]
        self.assertEqual(first["source_version"], 1)
        self.assertEqual(second["source_version"], 1)
        self.assertEqual(projection_count, 1)
        self.assertEqual(len(projection_inserts), 2)
        self.assertTrue(all("ON CONFLICT" in statement for statement in projection_inserts))
        self.assertTrue(all("DO NOTHING" in statement for statement in projection_inserts))

    async def test_late_old_ingest_cannot_overwrite_new_canonical_version(self) -> None:
        user_id = await self._user("fenced-projection-owner")
        material_id = await self._material(
            user_id,
            "Fenced",
            "obsolete version|old vector",
        )
        rag = _CoordinatedRag()

        async def ingest_current() -> dict:
            async with self.sessions() as db:
                material = await db.get(Material, material_id)
                return await RetrievalProjectionService(db, rag=rag).ingest(
                    material,
                    user_id=user_id,
                    force=True,
                )

        old_task = asyncio.create_task(ingest_current())
        await asyncio.wait_for(rag.old_started.wait(), timeout=2)

        async with self.sessions() as db:
            material = await db.get(Material, material_id)
            material.content = "replacement version|new vector"
            material.content_hash = hashlib.sha256(material.content.encode()).hexdigest()
            await db.commit()

        new_task = asyncio.create_task(ingest_current())
        await asyncio.sleep(0.05)
        self.assertEqual(rag.started_contents, ["obsolete version|old vector"])

        rag.release_old.set()
        old_result, new_result = await asyncio.gather(old_task, new_task)

        async with self.sessions() as db:
            projection = await RetrievalProjectionService(db, rag=rag).get_projection(
                user_id,
                material_id,
            )

        self.assertIsNone(old_result["indexed_version"])
        self.assertEqual(old_result["status"], "pending")
        self.assertEqual(new_result["indexed_version"], 2)
        self.assertEqual(projection.status, "ready")
        self.assertEqual(projection.source_version, 2)
        self.assertEqual(projection.indexed_version, 2)
        self.assertEqual(
            rag._collection.rows[(user_id, material_id)],
            ["replacement version", "new vector"],
        )

    async def test_missing_embeddings_keep_sql_chunks_and_keyword_retrieval(self) -> None:
        user_id = await self._user("fallback-owner")
        material_id = await self._material(user_id, "Hybrid search", "RRF fusion|reranker comparison")
        self.rag.embedding_enabled = False

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            projection = await service.ingest(await db.get(Material, material_id), user_id=user_id)
            hits = await KeywordMaterialRetrievalBackend(db).search(
                "reranker", scope=MaterialSearchScope(user_id=user_id), top_k=5
            )

        self.assertEqual(projection["status"], "degraded")
        self.assertEqual(projection["chunk_count"], 2)
        self.assertEqual(projection["vector_chunk_count"], 0)
        self.assertEqual([(hit.material_id, hit.chunk_index) for hit in hits], [(material_id, 1)])

    async def test_empty_material_records_actionable_projection_failure(self) -> None:
        user_id = await self._user("empty-owner")
        material_id = await self._material(user_id, "Unreadable upload", "")

        async with self.sessions() as db:
            projection = await RetrievalProjectionService(db, rag=self.rag).ingest(
                await db.get(Material, material_id), user_id=user_id
            )

        self.assertEqual(projection["status"], "failed")
        self.assertEqual(projection["chunk_count"], 0)
        self.assertIn("没有可索引", projection["last_error"])
        self.assertEqual(projection["last_error_code"], "retrieval.index_failed")
        self.assertRegex(projection["last_error_fingerprint"], r"^[0-9a-f]{16}$")

    async def test_refresh_replaces_old_chunks_vectors_and_source_version(self) -> None:
        user_id = await self._user("refresh-owner")
        material_id = await self._material(user_id, "RAG", "obsolete phrase|old vector")

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            material = await db.get(Material, material_id)
            await service.ingest(material, user_id=user_id)
            material.content = "replacement knowledge|new vector"
            material.content_hash = hashlib.sha256(material.content.encode()).hexdigest()
            await db.commit()
            projection = await service.refresh(material, user_id=user_id)
            chunks = list((await db.scalars(select(RetrievalProjectionChunk))).all())
            keyword = KeywordMaterialRetrievalBackend(db)
            old_hits = await keyword.search("obsolete", scope=MaterialSearchScope(user_id=user_id))
            new_hits = await keyword.search("replacement", scope=MaterialSearchScope(user_id=user_id))

        self.assertEqual(projection["source_version"], 2)
        self.assertEqual(projection["indexed_version"], 2)
        self.assertTrue(all(chunk.source_version == 2 for chunk in chunks))
        self.assertEqual(old_hits, [])
        self.assertEqual(new_hits[0].material_id, material_id)
        self.assertEqual(self.rag._collection.rows[(user_id, material_id)], ["replacement knowledge", "new vector"])

    async def test_failed_forget_survives_source_deletion_and_can_retry(self) -> None:
        user_id = await self._user("delete-owner")
        material_id = await self._material(user_id, "Private", "must disappear")

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            material = await db.get(Material, material_id)
            await service.ingest(material, user_id=user_id)
            await service.prepare_forget(user_id, material_id)
            await db.delete(material)
            await db.commit()
            self.rag.fail_remove = True
            failed = await service.forget(user_id, material_id)

        self.assertEqual(failed["status"], "failed")
        self.assertEqual(failed["operation"], "forget")
        self.assertIn("vector store unavailable", failed["last_error"])
        self.assertEqual(failed["last_error_code"], "retrieval.forget_failed")
        self.assertRegex(failed["last_error_fingerprint"], r"^[0-9a-f]{16}$")

        self.rag.fail_remove = False
        async with self.sessions() as db:
            recovered = await RetrievalProjectionService(db, rag=self.rag).retry(user_id, material_id)
            chunk_count = await db.scalar(select(func.count()).select_from(RetrievalProjectionChunk))

        self.assertEqual(recovered["status"], "deleted")
        self.assertEqual(chunk_count, 0)
        self.assertNotIn((user_id, material_id), self.rag._collection.rows)

    async def test_partial_vector_failure_is_cleaned_and_retry_recovers(self) -> None:
        user_id = await self._user("retry-owner")
        material_id = await self._material(user_id, "Retries", "first part|second part")
        self.rag.fail_index = True

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            failed = await service.ingest(await db.get(Material, material_id), user_id=user_id)
            self.assertEqual(failed["status"], "failed")
            self.assertNotIn((user_id, material_id), self.rag._collection.rows)
            self.rag.fail_index = False
            self.rag.last_error = ""
            recovered = await service.retry(user_id, material_id)

        self.assertEqual(recovered["status"], "ready")
        self.assertEqual(recovered["attempt_count"], 2)
        self.assertEqual(recovered["vector_chunk_count"], 2)

    async def test_rebuild_recovers_lost_vectors_without_touching_other_users(self) -> None:
        owner = await self._user("rebuild-owner")
        outsider = await self._user("rebuild-outsider")
        own_id = await self._material(owner, "Owner", "own content")
        outsider_id = await self._material(outsider, "Other", "other content")

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            await service.ingest(await db.get(Material, own_id), user_id=owner)
            await service.ingest(await db.get(Material, outsider_id), user_id=outsider)
            self.rag._collection.rows.pop((owner, own_id))
            result = await service.rebuild_user(owner)

        self.assertTrue(result["ok"])
        self.assertEqual(result["materials_indexed"], 1)
        self.assertIn((owner, own_id), self.rag._collection.rows)
        self.assertIn((outsider, outsider_id), self.rag._collection.rows)
        self.assertIn({"user_id": str(owner)}, self.rag._collection.deleted_filters)

    async def test_configuration_change_marks_owned_projection_stale(self) -> None:
        owner = await self._user("configuration-owner")
        outsider = await self._user("configuration-outsider")
        own_id = await self._material(owner, "Owner", "owner content")
        other_id = await self._material(outsider, "Other", "other content")

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            await service.ingest(await db.get(Material, own_id), user_id=owner)
            await service.ingest(await db.get(Material, other_id), user_id=outsider)
            self.rag._current_model = "test-embedding-v2"
            changed = await service.mark_configuration_stale(user_id=owner)
            own = await service.get_projection(owner, own_id)
            other = await service.get_projection(outsider, other_id)
            summary = await service.status_summary(owner)

        self.assertEqual(changed, 1)
        self.assertEqual(own.status, "degraded")
        self.assertEqual(other.status, "ready")
        self.assertEqual(summary["degraded"], 1)

    async def test_configuration_change_waits_for_in_flight_ingest(self) -> None:
        user_id = await self._user("configuration-fence-owner")
        material_id = await self._material(user_id, "Source", "obsolete content")
        coordinated_rag = _CoordinatedRag()
        configuration_entered = asyncio.Event()

        async def ingest() -> None:
            async with self.sessions() as db:
                material = await db.get(Material, material_id)
                await RetrievalProjectionService(db, rag=coordinated_rag).ingest(
                    material,
                    user_id=user_id,
                )

        async def change_configuration() -> None:
            async with self.sessions() as db:
                async with serialized_retrieval_configuration_change(db):
                    configuration_entered.set()

        ingest_task = asyncio.create_task(ingest())
        await asyncio.wait_for(coordinated_rag.old_started.wait(), timeout=1)
        configuration_task = asyncio.create_task(change_configuration())
        with self.assertRaises(asyncio.TimeoutError):
            await asyncio.wait_for(configuration_entered.wait(), timeout=0.05)

        coordinated_rag.release_old.set()
        await ingest_task
        await asyncio.wait_for(configuration_entered.wait(), timeout=1)
        await configuration_task

    async def test_forget_user_removes_only_owned_sql_chunks_and_vectors(self) -> None:
        owner = await self._user("purge-owner")
        outsider = await self._user("purge-outsider")
        own_id = await self._material(owner, "Owner", "owner private content")
        other_id = await self._material(outsider, "Other", "other private content")

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            await service.ingest(await db.get(Material, own_id), user_id=owner)
            await service.ingest(await db.get(Material, other_id), user_id=outsider)
            result = await service.forget_user(owner)
            own = await service.get_projection(owner, own_id)
            other = await service.get_projection(outsider, other_id)
            own_chunks = await db.scalar(
                select(func.count())
                .select_from(RetrievalProjectionChunk)
                .where(RetrievalProjectionChunk.user_id == owner)
            )

        self.assertEqual(result["projections_deleted"], 1)
        self.assertEqual(own.status, "deleted")
        self.assertEqual(other.status, "ready")
        self.assertEqual(own_chunks, 0)
        self.assertNotIn((owner, own_id), self.rag._collection.rows)
        self.assertIn((outsider, other_id), self.rag._collection.rows)

    async def test_stale_manifest_cannot_shadow_directly_updated_sql_content(self) -> None:
        user_id = await self._user("stale-owner")
        material_id = await self._material(user_id, "Source of truth", "obsolete words")

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            material = await db.get(Material, material_id)
            await service.ingest(material, user_id=user_id)
            material.content = "replacement information"
            await db.commit()
            backend = KeywordMaterialRetrievalBackend(db)
            old_hits = await backend.search("obsolete", scope=MaterialSearchScope(user_id=user_id))
            new_hits = await backend.search("replacement", scope=MaterialSearchScope(user_id=user_id))

        self.assertEqual(old_hits, [])
        self.assertEqual(new_hits[0].material_id, material_id)

    async def test_projection_mutation_rejects_cross_user_source(self) -> None:
        owner = await self._user("scope-owner")
        outsider = await self._user("scope-outsider")
        material_id = await self._material(owner, "Secret", "private")

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            with self.assertRaises(PermissionError):
                await service.ingest(await db.get(Material, material_id), user_id=outsider)
            projection_count = await db.scalar(select(func.count()).select_from(RetrievalProjection))

        self.assertEqual(projection_count, 0)

    async def test_canonical_update_commits_pending_index_before_external_failure(self):
        from app.services.material_service import MaterialService
        from unittest.mock import AsyncMock
        user_id = await self._user("pending-owner")
        material_id = await self._material(user_id, "Atomic update", "old text")
        async with self.sessions() as db:
            service = MaterialService(db)
            service.projections = RetrievalProjectionService(db, rag=self.rag)
            await service.projections.ingest(await db.get(Material, material_id), user_id=user_id)
            with (patch.object(service.projections, "refresh", AsyncMock(side_effect=RuntimeError("vector unavailable"))),
                  patch("app.services.material_service.sync_material_concepts", AsyncMock(return_value={}))):
                await service.update_material(material_id, user_id=user_id, content="new text")
        async with self.sessions() as db:
            self.assertEqual((await db.get(Material, material_id)).content, "new text")
            projection = await RetrievalProjectionService(db, rag=self.rag).get_projection(user_id, material_id)
            self.assertEqual((projection.status, projection.source_version, projection.indexed_version), ("pending", 2, None))

    async def test_warm_keyword_search_reads_no_bodies_and_does_not_retokenize(self) -> None:
        import re

        from app.services import material_retrieval_backend as backend_module

        user_id = await self._user("keyword-cache-owner")
        first = await self._material(user_id, "BM25", "ranked retrieval basics|term frequency ranks chunks|unrelated words")
        second = await self._material(user_id, "RRF", "fusion of ranked lists|retrieval fusion recipe")
        statements: list[str] = []

        def record(_conn, _cursor, statement, *_args) -> None:
            statements.append(statement)

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            for material_id in (first, second):
                await service.ingest(await db.get(Material, material_id), user_id=user_id)
            backend = KeywordMaterialRetrievalBackend(db)
            scope = MaterialSearchScope(user_id=user_id)
            cold = await backend.search("ranked retrieval", scope=scope, top_k=3)
            event.listen(self.engine.sync_engine, "before_cursor_execute", record)
            try:
                with patch.object(backend_module, "_chunk_token_stats", side_effect=AssertionError("re-tokenized")):
                    warm = await backend.search("ranked retrieval", scope=scope, top_k=3)
            finally:
                event.remove(self.engine.sync_engine, "before_cursor_execute", record)

        self.assertTrue(cold)
        self.assertEqual(
            [(hit.material_id, hit.chunk_index, hit.text, hit.score) for hit in warm],
            [(hit.material_id, hit.chunk_index, hit.text, hit.score) for hit in cold],
        )
        body_reads = [
            statement for statement in statements
            if re.search(r"materials\.content\b(?!_hash)", re.split(r"\s+FROM\s+", statement, maxsplit=1)[0])
        ]
        self.assertEqual(body_reads, [])

    async def test_keyword_scores_match_reference_bm25(self) -> None:
        import math
        from collections import Counter

        from app.services.material_retrieval_backend import _tokenize

        user_id = await self._user("keyword-reference-owner")
        corpus = {
            await self._material(user_id, "概率", "条件概率与贝叶斯定理|贝叶斯推断更新先验|随机变量期望"): None,
            await self._material(user_id, "检索", "BM25 ranks chunks by term frequency|混合检索融合排序|retrieval fusion"): None,
        }
        query = "贝叶斯 检索 ranks"
        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            for material_id in corpus:
                material = await db.get(Material, material_id)
                corpus[material_id] = [part.strip() for part in material.content.split("|")]
                await service.ingest(material, user_id=user_id)
            hits = await KeywordMaterialRetrievalBackend(db).search(
                query, scope=MaterialSearchScope(user_id=user_id), top_k=10,
            )

        # The pre-cache implementation, kept verbatim as the scoring oracle.
        docs = [
            (material_id, index, _tokenize(chunk))
            for material_id, chunks in corpus.items()
            for index, chunk in enumerate(chunks)
            if _tokenize(chunk)
        ]
        frequency = Counter()
        for *_ignored, tokens in docs:
            frequency.update(set(tokens))
        average = sum(len(tokens) for *_ignored, tokens in docs) / len(docs)
        expected = []
        for material_id, index, tokens in docs:
            tf = Counter(tokens)
            score = 0.0
            for term, weight in Counter(_tokenize(query)).items():
                if not tf.get(term):
                    continue
                idf = math.log(1.0 + (len(docs) - frequency[term] + 0.5) / (frequency[term] + 0.5))
                norm = tf[term] + 1.5 * (1.0 - 0.75 + 0.75 * len(tokens) / max(average, 1.0))
                score += weight * idf * (tf[term] * 2.5 / norm)
            if score > 0:
                expected.append((score, material_id, index))
        expected.sort(key=lambda item: (-item[0], item[1], item[2]))

        self.assertEqual(
            [(hit.material_id, hit.chunk_index) for hit in hits],
            [(material_id, index) for _, material_id, index in expected],
        )
        for hit, (score, *_ignored) in zip(hits, expected):
            self.assertAlmostEqual(hit.score, score)

    async def test_incompatible_vector_reset_runs_once_and_flags_ready_projections(self) -> None:
        from app.services.retrieval_projection_service import (
            VECTOR_INCOMPATIBLE_ERROR,
            reset_incompatible_vector_collection,
        )

        class _ResettableRag(_Rag):
            def __init__(self) -> None:
                super().__init__()
                self.vector_incompatible = False
                self.resets = 0

            async def reset_index(self, message=None, user_id=None) -> None:
                self.resets += 1
                self.vector_incompatible = False
                self._collection.rows.clear()

            def clear_vector_incompatible(self) -> None:
                self.vector_incompatible = False

        rag = _ResettableRag()
        owner = await self._user("reset-owner")
        other = await self._user("reset-other")
        owner_ready = await self._material(owner, "A", "alpha|beta")
        other_ready = await self._material(other, "B", "gamma")
        owner_failed = await self._material(owner, "Empty", "   ")
        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=rag)
            for material_id, user_id in ((owner_ready, owner), (other_ready, other), (owner_failed, owner)):
                await service.ingest(await db.get(Material, material_id), user_id=user_id)

        rag.vector_incompatible = True
        flagged = await reset_incompatible_vector_collection(self.sessions, rag)
        repeated = await reset_incompatible_vector_collection(self.sessions, rag)

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=rag)
            own = await service.get_projection(owner, owner_ready)
            foreign = await service.get_projection(other, other_ready)
            failed = await service.get_projection(owner, owner_failed)
        self.assertEqual((flagged, repeated, rag.resets), (2, 0, 1))
        self.assertEqual((own.status, own.vector_chunk_count, own.last_error), ("degraded", 0, VECTOR_INCOMPATIBLE_ERROR))
        self.assertEqual(foreign.status, "degraded")
        self.assertEqual(failed.status, "failed")
        self.assertEqual(rag._collection.rows, {})

    async def test_project_membership_changes_never_reembed(self) -> None:
        user_id = await self._user("membership-owner")
        material_id = await self._material(user_id, "Shared", "alpha|beta")

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            await service.ingest(await db.get(Material, material_id), user_id=user_id)
            project = ChatProject(user_id=user_id, name="项目")
            db.add(project)
            await db.flush()
            db.add(ChatProjectMaterial(project_id=project.id, material_id=material_id))
            await db.commit()
            again = await service.ingest(await db.get(Material, material_id), user_id=user_id)

        self.assertEqual(again["status"], "ready")
        self.assertEqual(self.rag.index_calls, 1)

    async def test_legacy_membership_signature_is_adopted_without_reembedding(self) -> None:
        user_id = await self._user("legacy-signature-owner")
        material_id = await self._material(user_id, "Legacy", "alpha|beta")

        async with self.sessions() as db:
            service = RetrievalProjectionService(db, rag=self.rag)
            material = await db.get(Material, material_id)
            await service.ingest(material, user_id=user_id)
            project = ChatProject(user_id=user_id, name="旧项目")
            db.add(project)
            await db.flush()
            db.add(ChatProjectMaterial(project_id=project.id, material_id=material_id))
            # The signature format written before vectors became single-copy.
            content_hash = hashlib.sha256(material.content.strip().encode("utf-8")).hexdigest()
            legacy_signature = hashlib.sha256(json.dumps({
                "title": material.title,
                "content_hash": content_hash,
                "file_type": material.file_type,
                "project_ids": [int(project.id)],
            }, ensure_ascii=False, sort_keys=True).encode("utf-8")).hexdigest()
            projection = await service.get_projection(user_id, material_id)
            projection.source_signature = legacy_signature
            await db.commit()

            adopted = await service.ingest(material, user_id=user_id)
            repeated = await service.ingest(material, user_id=user_id)
            projection = await service.get_projection(user_id, material_id)

        self.assertEqual((adopted["status"], repeated["status"]), ("ready", "ready"))
        self.assertEqual(self.rag.index_calls, 1)
        self.assertNotEqual(projection.source_signature, legacy_signature)

    async def test_new_material_is_vectorized_after_create_returns(self) -> None:
        from unittest.mock import AsyncMock

        from app.services.background_runner import material_projection_runner
        from app.services.material_service import MaterialService

        class _GatedRag(_Rag):
            def __init__(self) -> None:
                super().__init__()
                self.release = asyncio.Event()

            async def index_material(self, **kwargs) -> int:
                await self.release.wait()
                return await super().index_material(**kwargs)

        rag = _GatedRag()
        user_id = await self._user("background-owner")
        with (
            patch("app.services.material_service.get_rag_service", return_value=rag),
            patch("app.services.material_service.sync_material_concepts", AsyncMock(return_value={})),
        ):
            async with self.sessions() as db:
                service = MaterialService(db)
                material = await asyncio.wait_for(
                    service.create_material(title="后台索引", content="alpha|beta", user_id=user_id),
                    timeout=5,
                )
                material_id = int(material.id)
                queued = await service.projections.get_projection(user_id, material_id)
                self.assertIn(queued.status, {"pending", "indexing"})
                self.assertEqual(rag.index_calls, 0)
            rag.release.set()
            await material_projection_runner.drain(timeout=5)

        async with self.sessions() as db:
            projection = await RetrievalProjectionService(db, rag=rag).get_projection(user_id, material_id)
        self.assertEqual((projection.status, projection.vector_chunk_count), ("ready", 2))

    async def test_new_material_without_embeddings_is_indexed_in_request(self) -> None:
        from unittest.mock import AsyncMock

        from app.services.background_runner import material_projection_runner
        from app.services.material_service import MaterialService

        rag = _Rag(embedding_enabled=False)
        user_id = await self._user("keyword-only-owner")
        with (
            patch("app.services.material_service.get_rag_service", return_value=rag),
            patch("app.services.material_service.sync_material_concepts", AsyncMock(return_value={})),
        ):
            async with self.sessions() as db:
                service = MaterialService(db)
                material = await service.create_material(title="关键词", content="alpha|beta", user_id=user_id)
                projection = await service.projections.get_projection(user_id, int(material.id))

        self.assertEqual((projection.status, projection.chunk_count), ("degraded", 2))
        self.assertEqual(material_projection_runner.pending_count, 0)


if __name__ == "__main__":
    unittest.main()
