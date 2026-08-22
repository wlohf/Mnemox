"""Durable material ingestion, update, deletion, recovery, and tenant boundaries."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.material import Material
from app.models.retrieval import RetrievalProjection, RetrievalProjectionChunk
from app.models.user import User
from app.services.material_retrieval_backend import KeywordMaterialRetrievalBackend, MaterialSearchScope
from app.services.retrieval_projection_service import RetrievalProjectionService


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


if __name__ == "__main__":
    unittest.main()
