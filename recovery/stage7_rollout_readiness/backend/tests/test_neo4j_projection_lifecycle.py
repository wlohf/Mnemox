"""Stage 7 Neo4j rebuild lifecycle, initialization, and coalescing gates."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import func, select, text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.concept import Concept
from app.models.knowledge import KnowledgeProjectionOutbox, KnowledgeSource
from app.models.user import User
from app.services.graph_shadow_service import neo4j_projection_lag_summary
from app.services.knowledge_projection_service import (
    NEO4J_GRAPH_PROJECTION_TARGET,
    claim_next_knowledge_projection,
    enqueue_knowledge_object_projection,
    enqueue_neo4j_user_rebuild,
)
from app.utils.utc import utc_now_db


class Neo4jProjectionLifecycleTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'neo4j-projection-lifecycle.db'}"
        )
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self) -> None:
        await self.engine.dispose()
        self.tmp.cleanup()

    async def _user(self, db, name: str) -> User:
        row = User(
            username=name,
            email=f"{name}@example.test",
            hashed_password="hash",
        )
        db.add(row)
        await db.flush()
        return row

    async def test_existing_canonical_graph_requires_successful_initial_rebuild(self) -> None:
        async with self.sessions() as db:
            empty = await self._user(db, "neo4j-empty-owner")
            existing = await self._user(db, "neo4j-existing-owner")
            db.add(
                KnowledgeSource(
                    user_id=int(existing.id),
                    source_type="note",
                    source_record_id=1,
                    source_key="note:1",
                    title_snapshot="Existing graph data",
                    status="active",
                    current_revision=1,
                )
            )
            await db.commit()
            empty_id = int(empty.id)
            existing_id = int(existing.id)

        async with self.sessions() as db:
            empty_status = await neo4j_projection_lag_summary(db, user_id=empty_id)
            existing_status = await neo4j_projection_lag_summary(db, user_id=existing_id)

        self.assertTrue(empty_status["initialized"])
        self.assertFalse(empty_status["canonical_graph_objects_present"])
        self.assertFalse(existing_status["initialized"])
        self.assertTrue(existing_status["canonical_graph_objects_present"])
        self.assertFalse(existing_status["successful_rebuild"])

        with patch.object(settings, "GRAPH_BACKEND", "neo4j"):
            async with self.sessions() as db:
                row = await enqueue_neo4j_user_rebuild(
                    db,
                    user_id=existing_id,
                    force=True,
                )
                assert row is not None
                row.status = "processed"
                row.processed_at = utc_now_db()
                await db.commit()

        async with self.sessions() as db:
            initialized = await neo4j_projection_lag_summary(db, user_id=existing_id)
        self.assertTrue(initialized["initialized"])
        self.assertTrue(initialized["successful_rebuild"])

    async def test_graph_object_mutation_requeues_a_processed_rebuild(self) -> None:
        with (
            patch.object(settings, "GRAPH_BACKEND", "neo4j"),
            patch.object(settings, "KNOWLEDGE_V2_ENABLED", True),
        ):
            async with self.sessions() as db:
                owner = await self._user(db, "neo4j-dirty-owner")
                concept = Concept(
                    user_id=int(owner.id),
                    name="Dirty graph concept",
                    name_normalized="dirty graph concept",
                    description="First version",
                    source="manual",
                    review_status="confirmed",
                )
                db.add(concept)
                await db.flush()
                row = await enqueue_neo4j_user_rebuild(
                    db,
                    user_id=int(owner.id),
                    force=True,
                )
                assert row is not None
                row.status = "processed"
                row.processed_at = utc_now_db()
                await db.commit()
                user_id = int(owner.id)
                concept_id = int(concept.id)
                rebuild_id = int(row.id)

            async with self.sessions() as db:
                concept = await db.get(Concept, concept_id)
                assert concept is not None
                concept.description = "Second version"
                await db.flush()
                await enqueue_knowledge_object_projection(
                    db,
                    user_id=user_id,
                    object_type="concept",
                    object_id=concept_id,
                )
                await db.commit()

            async with self.sessions() as db:
                rebuild = await db.get(KnowledgeProjectionOutbox, rebuild_id)
                assert rebuild is not None
                self.assertEqual(rebuild.status, "pending")
                self.assertIsNone(rebuild.processed_at)

    async def test_inflight_rebuild_uses_one_followup_slot_and_blocks_parallel_claim(self) -> None:
        with patch.object(settings, "GRAPH_BACKEND", "neo4j"):
            async with self.sessions() as db:
                owner = await self._user(db, "neo4j-followup-owner")
                main = await enqueue_neo4j_user_rebuild(
                    db,
                    user_id=int(owner.id),
                    force=True,
                )
                assert main is not None
                await db.commit()
                user_id = int(owner.id)
                main_id = int(main.id)

            async with self.sessions() as db:
                claimed = await claim_next_knowledge_projection(
                    db,
                    worker_id="neo4j-worker-a",
                    max_attempts=5,
                    lease_seconds=120,
                    projection_targets=(NEO4J_GRAPH_PROJECTION_TARGET,),
                )
                assert claimed is not None
                self.assertEqual(int(claimed.id), main_id)
                await db.commit()

            async with self.sessions() as db:
                followup_a = await enqueue_neo4j_user_rebuild(
                    db,
                    user_id=user_id,
                    force=True,
                )
                followup_b = await enqueue_neo4j_user_rebuild(
                    db,
                    user_id=user_id,
                    force=True,
                )
                assert followup_a is not None and followup_b is not None
                self.assertEqual(int(followup_a.id), int(followup_b.id))
                self.assertNotEqual(int(followup_a.id), main_id)
                await db.commit()
                followup_id = int(followup_a.id)

            async with self.sessions() as db:
                total = int(
                    await db.scalar(
                        select(func.count(KnowledgeProjectionOutbox.id)).where(
                            KnowledgeProjectionOutbox.user_id == user_id,
                            KnowledgeProjectionOutbox.projection_target
                            == NEO4J_GRAPH_PROJECTION_TARGET,
                        )
                    )
                    or 0
                )
                blocked = await claim_next_knowledge_projection(
                    db,
                    worker_id="neo4j-worker-b",
                    max_attempts=5,
                    lease_seconds=120,
                    projection_targets=(NEO4J_GRAPH_PROJECTION_TARGET,),
                )
                self.assertEqual(total, 2)
                self.assertIsNone(blocked)
                await db.rollback()

            async with self.sessions() as db:
                main = await db.get(KnowledgeProjectionOutbox, main_id)
                assert main is not None
                main.status = "processed"
                main.processed_at = utc_now_db()
                main.locked_at = None
                main.lease_owner = None
                await db.commit()

            async with self.sessions() as db:
                followup = await claim_next_knowledge_projection(
                    db,
                    worker_id="neo4j-worker-b",
                    max_attempts=5,
                    lease_seconds=120,
                    projection_targets=(NEO4J_GRAPH_PROJECTION_TARGET,),
                )
                assert followup is not None
                self.assertEqual(int(followup.id), followup_id)
                await db.commit()

            # A mutation during follow-up processing reuses the now-idle main
            # slot instead of creating a third full rebuild task.
            async with self.sessions() as db:
                queued = await enqueue_neo4j_user_rebuild(
                    db,
                    user_id=user_id,
                    force=True,
                )
                assert queued is not None
                self.assertEqual(int(queued.id), main_id)
                await db.commit()

            async with self.sessions() as db:
                total = int(
                    await db.scalar(
                        select(func.count(KnowledgeProjectionOutbox.id)).where(
                            KnowledgeProjectionOutbox.user_id == user_id,
                            KnowledgeProjectionOutbox.projection_target
                            == NEO4J_GRAPH_PROJECTION_TARGET,
                        )
                    )
                    or 0
                )
                blocked = await claim_next_knowledge_projection(
                    db,
                    worker_id="neo4j-worker-c",
                    max_attempts=5,
                    lease_seconds=120,
                    projection_targets=(NEO4J_GRAPH_PROJECTION_TARGET,),
                )
                self.assertEqual(total, 2)
                self.assertIsNone(blocked)
                await db.rollback()


if __name__ == "__main__":
    unittest.main()
