"""Stage 3 knowledge projection idempotency, recovery, and deletion gates."""
from __future__ import annotations

import hashlib
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.concept import Concept
from app.models.knowledge import (
    Claim,
    KnowledgeEmbeddingProjection,
    KnowledgeProjectionOutbox,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.user import User
from app.services.knowledge_embedding_service import (
    KnowledgeEmbeddingConfiguration,
    KnowledgeEmbeddingUnavailable,
    knowledge_embedding_configuration,
)
from app.services.knowledge_projection_service import (
    KNOWLEDGE_PROJECTION_TARGET,
    SPARSE_KNOWLEDGE_PROJECTION_TARGET,
    claim_next_knowledge_projection,
    enqueue_knowledge_object_projection,
    process_claimed_knowledge_projection,
    schedule_user_knowledge_rebuild,
)
from app.services.knowledge_projection_worker import KnowledgeProjectionWorker
from app.services.knowledge_source_service import delete_source
from app.utils.utc import utc_now_db


class MemoryEmbeddingIndex:
    def __init__(self, collection: str):
        self.collection = collection
        self.vectors: dict[str, dict[str, dict]] = {}
        self.deletes: list[tuple[str, str]] = []

    async def upsert(self, *, vector_key: str, text: str, metadata: dict):
        self.vectors.setdefault(self.collection, {})[str(vector_key)] = {
            "text": str(text),
            "metadata": dict(metadata),
        }

    async def delete(self, *, vector_key: str, collection: str):
        self.deletes.append((str(collection), str(vector_key)))
        self.vectors.setdefault(str(collection), {}).pop(str(vector_key), None)


class UnavailableEmbeddingIndex(MemoryEmbeddingIndex):
    async def upsert(self, *, vector_key: str, text: str, metadata: dict):
        raise KnowledgeEmbeddingUnavailable("test provider unavailable")


class BrokenEmbeddingIndex(MemoryEmbeddingIndex):
    async def upsert(self, *, vector_key: str, text: str, metadata: dict):
        raise RuntimeError("test vector failure")


class KnowledgeProjectionTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'knowledge-projection.db'}"
        )
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _seed(self):
        async with self.sessions() as db:
            user = User(
                username="projection-owner",
                email="projection-owner@example.test",
                hashed_password="hash",
            )
            db.add(user)
            await db.flush()
            source = KnowledgeSource(
                user_id=int(user.id),
                source_type="material",
                source_record_id=41,
                source_key="material:41",
                title_snapshot="Projection source",
                status="active",
                current_revision=1,
            )
            db.add(source)
            await db.flush()
            revision = KnowledgeSourceRevision(
                user_id=int(user.id),
                knowledge_source_id=int(source.id),
                revision=1,
                content_hash=hashlib.sha256(b"projection evidence").hexdigest(),
                title_snapshot=source.title_snapshot,
                status="current",
            )
            db.add(revision)
            await db.flush()
            unit = KnowledgeUnit(
                user_id=int(user.id),
                source_revision_id=int(revision.id),
                unit_type="chunk",
                ordinal=0,
                text="projection evidence",
                text_hash=hashlib.sha256(b"projection evidence").hexdigest(),
                locator={},
            )
            claim = Claim(
                user_id=int(user.id),
                source_revision_id=int(revision.id),
                statement="Projection evidence supports a rebuildable claim.",
                fingerprint=hashlib.sha256(b"projection claim").hexdigest(),
                claim_kind="observation",
                confidence=0.9,
                derivation_type="explicit",
                review_status="pending",
                lifecycle_status="active",
                schema_version=1,
            )
            concept = Concept(
                user_id=int(user.id),
                name="Rebuildable projection",
                name_normalized="rebuildable projection",
                description="A disposable representation of canonical SQL knowledge.",
                source="manual",
                review_status="confirmed",
            )
            db.add_all((unit, claim, concept))
            await db.commit()
            return int(user.id), int(unit.id), int(claim.id), int(concept.id)

    async def _seed_note_unit(self, user_id: int) -> int:
        async with self.sessions() as db:
            source = KnowledgeSource(
                user_id=int(user_id),
                source_type="note",
                source_record_id=42,
                source_key="note:42",
                title_snapshot="Projection note",
                status="active",
                current_revision=1,
            )
            db.add(source)
            await db.flush()
            revision = KnowledgeSourceRevision(
                user_id=int(user_id),
                knowledge_source_id=int(source.id),
                revision=1,
                content_hash=hashlib.sha256(b"note projection evidence").hexdigest(),
                title_snapshot=source.title_snapshot,
                status="current",
            )
            db.add(revision)
            await db.flush()
            unit = KnowledgeUnit(
                user_id=int(user_id),
                source_revision_id=int(revision.id),
                unit_type="note_body",
                ordinal=0,
                text="note projection evidence",
                text_hash=hashlib.sha256(b"note projection evidence").hexdigest(),
                locator={},
            )
            db.add(unit)
            await db.commit()
            return int(unit.id)

    async def _drain(
        self,
        index,
        *,
        max_attempts: int = 5,
        retry_base_seconds: float = 0,
    ) -> list[str]:
        statuses: list[str] = []
        while True:
            async with self.sessions() as db:
                row = await claim_next_knowledge_projection(
                    db,
                    worker_id="projection-test",
                    max_attempts=max_attempts,
                    lease_seconds=120,
                )
                if row is None:
                    await db.rollback()
                    break
                identifier = int(row.id)
                await db.commit()
            async with self.sessions() as db:
                status = await process_claimed_knowledge_projection(
                    db,
                    outbox_id=identifier,
                    worker_id="projection-test",
                    embedding_index=index,
                    max_attempts=max_attempts,
                    retry_base_seconds=retry_base_seconds,
                )
                await db.commit()
                statuses.append(status)
        return statuses

    async def test_claim_concept_and_material_unit_projection_is_idempotent_and_compact(self):
        user_id, unit_id, claim_id, concept_id = await self._seed()
        note_unit_id = await self._seed_note_unit(user_id)
        config = knowledge_embedding_configuration()
        index = MemoryEmbeddingIndex(config.collection)
        with patch.object(settings, "KNOWLEDGE_SPARSE_BACKEND", "reference"):
            async with self.sessions() as db:
                for object_type, object_id in (
                    ("material_unit", unit_id),
                    ("note_unit", note_unit_id),
                    ("claim", claim_id),
                    ("concept", concept_id),
                ):
                    first = await enqueue_knowledge_object_projection(
                        db,
                        user_id=user_id,
                        object_type=object_type,
                        object_id=object_id,
                    )
                    repeated = await enqueue_knowledge_object_projection(
                        db,
                        user_id=user_id,
                        object_type=object_type,
                        object_id=object_id,
                    )
                    self.assertEqual(first.id, repeated.id)
                await db.commit()
                rows = list((await db.scalars(select(KnowledgeProjectionOutbox))).all())

        statuses = await self._drain(index)
        async with self.sessions() as db:
            projections = list(
                (
                    await db.scalars(
                        select(KnowledgeEmbeddingProjection).order_by(
                            KnowledgeEmbeddingProjection.object_type
                        )
                    )
                ).all()
            )

        self.assertEqual(len(rows), 4)
        self.assertTrue(all(set(row.payload) == {"object_type"} for row in rows))
        self.assertTrue(all("text" not in row.payload and "content" not in row.payload for row in rows))
        self.assertEqual(statuses, ["processed", "processed", "processed", "processed"])
        self.assertEqual(
            {row.object_type for row in projections},
            {"claim", "concept", "material_unit", "note_unit"},
        )
        self.assertEqual({row.status for row in projections}, {"ready"})
        concept_vector = index.vectors[config.collection][f"u:{user_id}:knowledge:concept:{concept_id}"]
        self.assertIn("名称：Rebuildable projection", concept_vector["text"])
        self.assertIn("定义：A disposable representation", concept_vector["text"])

    async def test_source_deletion_removes_claim_and_unit_vectors_but_keeps_concept(self):
        user_id, unit_id, claim_id, concept_id = await self._seed()
        config = knowledge_embedding_configuration()
        index = MemoryEmbeddingIndex(config.collection)
        async with self.sessions() as db:
            for object_type, object_id in (
                ("material_unit", unit_id),
                ("claim", claim_id),
                ("concept", concept_id),
            ):
                await enqueue_knowledge_object_projection(
                    db,
                    user_id=user_id,
                    object_type=object_type,
                    object_id=object_id,
                )
            await db.commit()
        await self._drain(index)

        async with self.sessions() as db:
            await delete_source(
                db,
                user_id=user_id,
                source_type="material",
                source_record_id=41,
            )
            await db.commit()
        await self._drain(index)

        remaining = set(index.vectors[config.collection])
        self.assertEqual(remaining, {f"u:{user_id}:knowledge:concept:{concept_id}"})
        async with self.sessions() as db:
            rows = list(
                (
                    await db.scalars(
                        select(KnowledgeEmbeddingProjection).where(
                            KnowledgeEmbeddingProjection.object_type.in_(("claim", "material_unit"))
                        )
                    )
                ).all()
            )
        self.assertEqual({row.status for row in rows}, {"deleted"})

    async def test_rebuild_deletes_orphan_projection_and_leaves_zero_residual_vectors(self):
        user_id, _, _, concept_id = await self._seed()
        config = knowledge_embedding_configuration()
        index = MemoryEmbeddingIndex(config.collection)
        orphan_key = f"u:{user_id}:knowledge:concept:99999"
        index.vectors.setdefault(config.collection, {})[orphan_key] = {"text": "orphan"}
        async with self.sessions() as db:
            db.add(
                KnowledgeEmbeddingProjection(
                    user_id=user_id,
                    object_type="concept",
                    object_id=99999,
                    content_hash="x" * 64,
                    configuration_fingerprint=config.fingerprint,
                    embedding_model=config.embedding_model,
                    collection=config.collection,
                    vector_key=orphan_key,
                    status="ready",
                )
            )
            result = await schedule_user_knowledge_rebuild(db, user_id=user_id)
            await db.commit()
        await self._drain(index)

        self.assertEqual(result["stale_objects"], 1)
        self.assertNotIn(orphan_key, index.vectors[config.collection])
        self.assertIn(
            f"u:{user_id}:knowledge:concept:{concept_id}",
            index.vectors[config.collection],
        )

    async def test_configuration_change_deletes_old_collection_before_reprojection(self):
        user_id, _, _, concept_id = await self._seed()
        first = KnowledgeEmbeddingConfiguration(
            embedding_model="same-model",
            base_url="https://first.example/v1",
            fingerprint="a" * 64,
            collection="knowledge_first",
            enabled=True,
        )
        second = KnowledgeEmbeddingConfiguration(
            embedding_model="same-model",
            base_url="https://second.example/v1",
            fingerprint="b" * 64,
            collection="knowledge_second",
            enabled=True,
        )
        index = MemoryEmbeddingIndex(first.collection)
        with patch(
            "app.services.knowledge_projection_service.knowledge_embedding_configuration",
            return_value=first,
        ):
            async with self.sessions() as db:
                await enqueue_knowledge_object_projection(
                    db,
                    user_id=user_id,
                    object_type="concept",
                    object_id=concept_id,
                )
                await db.commit()
            await self._drain(index)

        key = f"u:{user_id}:knowledge:concept:{concept_id}"
        self.assertIn(key, index.vectors[first.collection])
        index.collection = second.collection
        with patch(
            "app.services.knowledge_projection_service.knowledge_embedding_configuration",
            return_value=second,
        ):
            async with self.sessions() as db:
                await enqueue_knowledge_object_projection(
                    db,
                    user_id=user_id,
                    object_type="concept",
                    object_id=concept_id,
                    force=True,
                )
                await db.commit()
            await self._drain(index)

        self.assertNotIn(key, index.vectors[first.collection])
        self.assertIn(key, index.vectors[second.collection])
        self.assertIn((first.collection, key), index.deletes)
        async with self.sessions() as db:
            rows = list((await db.scalars(select(KnowledgeEmbeddingProjection))).all())
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].configuration_fingerprint, second.fingerprint)
        self.assertEqual(rows[0].status, "ready")

    async def test_missing_embedding_provider_degrades_without_blocking_exact_paths(self):
        user_id, _, _, concept_id = await self._seed()
        config = knowledge_embedding_configuration()
        async with self.sessions() as db:
            await enqueue_knowledge_object_projection(
                db,
                user_id=user_id,
                object_type="concept",
                object_id=concept_id,
            )
            await db.commit()
        statuses = await self._drain(UnavailableEmbeddingIndex(config.collection))
        async with self.sessions() as db:
            projection = await db.scalar(select(KnowledgeEmbeddingProjection))
            outbox = await db.scalar(select(KnowledgeProjectionOutbox))

        self.assertEqual(statuses, ["processed"])
        self.assertEqual(projection.status, "degraded")
        self.assertEqual(outbox.status, "processed")
        self.assertIn("unavailable", projection.last_error)

    async def test_embedding_model_dimension_change_rotates_collection_without_old_vectors(self):
        user_id, _, _, concept_id = await self._seed()
        first = KnowledgeEmbeddingConfiguration(
            embedding_model="dimension-1536",
            base_url="https://embedding.example/v1",
            fingerprint="c" * 64,
            collection="knowledge_dimension_1536",
            enabled=True,
        )
        second = KnowledgeEmbeddingConfiguration(
            embedding_model="dimension-3072",
            base_url="https://embedding.example/v1",
            fingerprint="d" * 64,
            collection="knowledge_dimension_3072",
            enabled=True,
        )
        index = MemoryEmbeddingIndex(first.collection)
        with patch(
            "app.services.knowledge_projection_service.knowledge_embedding_configuration",
            return_value=first,
        ):
            async with self.sessions() as db:
                await enqueue_knowledge_object_projection(
                    db,
                    user_id=user_id,
                    object_type="concept",
                    object_id=concept_id,
                )
                await db.commit()
            await self._drain(index)

        key = f"u:{user_id}:knowledge:concept:{concept_id}"
        index.collection = second.collection
        with patch(
            "app.services.knowledge_projection_service.knowledge_embedding_configuration",
            return_value=second,
        ):
            async with self.sessions() as db:
                await enqueue_knowledge_object_projection(
                    db,
                    user_id=user_id,
                    object_type="concept",
                    object_id=concept_id,
                )
                await db.commit()
            await self._drain(index)

        self.assertNotIn(key, index.vectors[first.collection])
        self.assertIn(key, index.vectors[second.collection])
        async with self.sessions() as db:
            rows = list(
                (
                    await db.scalars(
                        select(KnowledgeEmbeddingProjection).order_by(
                            KnowledgeEmbeddingProjection.id
                        )
                    )
                ).all()
            )
        self.assertEqual([row.status for row in rows], ["deleted", "ready"])
        self.assertEqual(rows[-1].embedding_model, second.embedding_model)

    async def test_projection_failures_retry_then_dead_letter_at_the_bound(self):
        user_id, _, _, concept_id = await self._seed()
        config = knowledge_embedding_configuration()
        index = BrokenEmbeddingIndex(config.collection)
        async with self.sessions() as db:
            await enqueue_knowledge_object_projection(
                db,
                user_id=user_id,
                object_type="concept",
                object_id=concept_id,
            )
            await db.commit()

        first = await self._drain(index, max_attempts=2, retry_base_seconds=60)
        async with self.sessions() as db:
            row = await db.scalar(select(KnowledgeProjectionOutbox))
            self.assertEqual(row.status, "failed")
            self.assertEqual(row.attempts, 1)
            self.assertIsNone(row.dead_lettered_at)
            row.available_at = utc_now_db()
            await db.commit()
        second = await self._drain(index, max_attempts=2, retry_base_seconds=60)
        async with self.sessions() as db:
            row = await db.scalar(select(KnowledgeProjectionOutbox))

        self.assertEqual(first, ["failed"])
        self.assertEqual(second, ["failed"])
        self.assertEqual(row.attempts, 2)
        self.assertIsNotNone(row.dead_lettered_at)

    async def test_sparse_only_worker_does_not_consume_chroma_backlog(self):
        user_id, _, claim_id, _ = await self._seed()
        async with self.sessions() as db:
            claim = await db.scalar(select(Claim).where(Claim.id == claim_id))
            claim.review_status = "confirmed"
            await enqueue_knowledge_object_projection(
                db,
                user_id=user_id,
                object_type="claim",
                object_id=claim_id,
            )
            await db.commit()

        with patch.object(settings, "KNOWLEDGE_EMBEDDING_ENABLED", False), patch.object(
            settings,
            "KNOWLEDGE_SPARSE_BACKEND",
            "sqlite_fts5",
        ):
            async with self.sessions() as db:
                # Re-enqueue while the sparse backend is enabled so both targets exist.
                await enqueue_knowledge_object_projection(
                    db,
                    user_id=user_id,
                    object_type="claim",
                    object_id=claim_id,
                    force=True,
                )
                await db.commit()
                targets = set(
                    (await db.scalars(select(KnowledgeProjectionOutbox.projection_target))).all()
                )
            self.assertIn(KNOWLEDGE_PROJECTION_TARGET, targets)
            self.assertIn(SPARSE_KNOWLEDGE_PROJECTION_TARGET, targets)

            worker = KnowledgeProjectionWorker(
                self.sessions,
                worker_id="sparse-only-worker-test",
                batch_size=10,
                poll_interval_seconds=0.01,
            )
            result = await worker.run_once()

        self.assertGreaterEqual(result["processed"], 1)
        async with self.sessions() as db:
            sparse_rows = list(
                (
                    await db.scalars(
                        select(KnowledgeProjectionOutbox).where(
                            KnowledgeProjectionOutbox.projection_target
                            == SPARSE_KNOWLEDGE_PROJECTION_TARGET
                        )
                    )
                ).all()
            )
            chroma_rows = list(
                (
                    await db.scalars(
                        select(KnowledgeProjectionOutbox).where(
                            KnowledgeProjectionOutbox.projection_target
                            == KNOWLEDGE_PROJECTION_TARGET
                        )
                    )
                ).all()
            )
        self.assertTrue(sparse_rows)
        self.assertTrue(all(row.status == "processed" for row in sparse_rows))
        self.assertTrue(chroma_rows)
        self.assertTrue(all(row.status == "pending" for row in chroma_rows))

    async def test_projection_worker_owns_short_claim_and_processing_transactions(self):
        user_id, _, _, concept_id = await self._seed()
        config = knowledge_embedding_configuration()
        index = MemoryEmbeddingIndex(config.collection)
        async with self.sessions() as db:
            await enqueue_knowledge_object_projection(
                db,
                user_id=user_id,
                object_type="concept",
                object_id=concept_id,
            )
            await db.commit()

        with patch.object(settings, "KNOWLEDGE_EMBEDDING_ENABLED", True), patch.object(
            settings,
            "KNOWLEDGE_SPARSE_BACKEND",
            "reference",
        ):
            worker = KnowledgeProjectionWorker(
                self.sessions,
                worker_id="projection-worker-test",
                embedding_index=index,
                batch_size=10,
                poll_interval_seconds=0.01,
            )
            result = await worker.run_once()

        self.assertEqual(result, {"claimed": 1, "processed": 1, "failed": 0})
        self.assertIn(
            f"u:{user_id}:knowledge:concept:{concept_id}",
            index.vectors[config.collection],
        )
