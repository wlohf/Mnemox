"""Optional real Neo4j Stage 6 integration gate.

Run with MNEMOX_TEST_NEO4J_URI / USER / PASSWORD. The test database is treated as
fully disposable and is cleared for the synthetic user during rebuild.
"""
from __future__ import annotations

import hashlib
import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.concept import Concept
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    ClaimRelation,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.user import User
from app.services.graph_store.fallback_store import FallbackGraphStore
from app.services.graph_store.neo4j_store import Neo4jAsyncExecutor, Neo4jGraphStore
from app.services.graph_store.rollout_store import Neo4jRolloutGraphStore
from app.services.graph_store.sql_store import SqlGraphStore
from app.services.knowledge_projection_service import (
    enqueue_knowledge_object_projection,
    enqueue_neo4j_user_rebuild,
)
from app.utils.utc import utc_now_db


NEO4J_URI = os.environ.get("MNEMOX_TEST_NEO4J_URI", "").strip()
NEO4J_USER = os.environ.get("MNEMOX_TEST_NEO4J_USER", "neo4j").strip()
NEO4J_PASSWORD = os.environ.get("MNEMOX_TEST_NEO4J_PASSWORD", "stage6-graphiti-test").strip()
NEO4J_DATABASE = os.environ.get("MNEMOX_TEST_NEO4J_DATABASE", "neo4j").strip()


@unittest.skipUnless(NEO4J_URI and NEO4J_PASSWORD, "Neo4j Stage 6 test credentials are required")
class Neo4jShadowIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'neo4j-shadow.db'}")
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        self.executor = Neo4jAsyncExecutor(
            uri=NEO4J_URI,
            user=NEO4J_USER,
            password=NEO4J_PASSWORD,
            database=NEO4J_DATABASE,
        )
        await self.executor.verify_connectivity()

    async def asyncTearDown(self) -> None:
        await self.executor.close()
        await self.engine.dispose()
        self.tmp.cleanup()

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
            fingerprint=hashlib.sha256(statement.casefold().encode()).hexdigest(), confidence=0.9,
            derivation_type="manual", review_status="confirmed", lifecycle_status="active",
        )
        db.add_all((unit, claim))
        await db.flush()
        db.add(ClaimEvidence(
            user_id=user_id, claim_id=int(claim.id), knowledge_unit_id=int(unit.id),
            excerpt=statement, char_start=0, char_end=len(statement), locator={},
            grounding_method="manual", confidence=0.9,
        ))
        await db.flush()
        return source, claim

    async def test_wrong_credentials_report_unavailable_without_touching_sql(self):
        broken = Neo4jAsyncExecutor(
            uri=NEO4J_URI,
            user=NEO4J_USER,
            password=f"{NEO4J_PASSWORD}-wrong",
            database=NEO4J_DATABASE,
        )
        try:
            async with self.sessions() as db:
                store = Neo4jGraphStore(db, executor=broken)
                health = await store.health()
                self.assertFalse(health["ok"])
                self.assertEqual(health["backend"], "neo4j")
                self.assertFalse(health["authoritative"])
                self.assertIn("error", health)
                # The canonical SQL transaction remains usable after Shadow auth failure.
                self.assertEqual(await db.scalar(text("SELECT 1")), 1)
        finally:
            await broken.close()

    async def test_rebuild_query_isolation_delete_and_no_raw_text_properties(self):
        async with self.sessions() as db:
            owner = await self._user(db, "neo4j-int-owner")
            stranger = await self._user(db, "neo4j-int-stranger")
            source_a, anchor = await self._claim(db, user_id=int(owner.id), record_id=101, statement="Anchor private body")
            source_b, related = await self._claim(db, user_id=int(owner.id), record_id=102, statement="Related private body")
            _, foreign = await self._claim(db, user_id=int(stranger.id), record_id=103, statement="Foreign private body")
            concept = Concept(
                user_id=int(owner.id), name="Feedback Loop", name_normalized="feedback loop",
                source="manual", review_status="confirmed",
            )
            db.add(concept)
            await db.flush()
            for claim in (anchor, related):
                db.add(ClaimConceptLink(
                    user_id=int(owner.id), claim_id=int(claim.id), concept_id=int(concept.id),
                    relation_type="about", mention_text="feedback loop", confidence=1.0,
                    derivation_type="manual", review_status="confirmed",
                ))
            db.add(ClaimRelation(
                user_id=int(owner.id), from_claim_id=int(anchor.id), to_claim_id=int(related.id),
                relation_type="supports", confidence=0.95, derivation_type="manual",
                review_status="confirmed", rationale="synthetic",
            ))
            await db.commit()

            store = Neo4jGraphStore(db, executor=self.executor)
            rebuilt = await store.rebuild_user(user_id=int(owner.id))
            self.assertEqual(rebuilt["claims"], 2)
            rebuilt_again = await store.rebuild_user(user_id=int(owner.id))
            self.assertEqual(rebuilt_again["claims"], rebuilt["claims"])
            self.assertEqual(rebuilt_again["concepts"], rebuilt["concepts"])
            self.assertEqual(rebuilt_again["claim_relations"], rebuilt["claim_relations"])

            sql_store = SqlGraphStore(db)
            sql_hits = await sql_store.expand_claims(
                user_id=int(owner.id), claim_ids=(int(anchor.id),),
                patterns=("direct_claim_relations", "shared_concept_claims"), depth=2, limit=10,
            )
            hits = await store.expand_claims(
                user_id=int(owner.id), claim_ids=(int(anchor.id),),
                patterns=("direct_claim_relations", "shared_concept_claims"), depth=2, limit=10,
            )
            signature = lambda row: (
                int(row.object_id),
                str(row.path_type),
                int(row.depth),
                round(float(row.confidence), 6),
            )
            self.assertEqual({signature(row) for row in hits}, {signature(row) for row in sql_hits})
            self.assertIn(int(related.id), {row.object_id for row in hits})
            self.assertNotIn(int(foreign.id), {row.object_id for row in hits})

            sql_source_hits = await sql_store.source_claims(
                user_id=int(owner.id), source_id=int(source_a.id), limit=10,
            )
            source_hits = await store.source_claims(user_id=int(owner.id), source_id=int(source_a.id), limit=10)
            self.assertEqual({signature(row) for row in source_hits}, {signature(row) for row in sql_source_hits})
            self.assertEqual({row.object_id for row in source_hits}, {int(anchor.id)})

            # Real runtime gate: a successful rebuild marker admits the user to
            # Neo4j; a later canonical mutation immediately returns reads to SQL
            # until the projection is rebuilt again.
            with (
                patch.object(settings, "GRAPH_BACKEND", "neo4j"),
                patch.object(settings, "NEO4J_GRAPH_ROLLOUT_PERCENT", 100),
                patch.object(settings, "NEO4J_GRAPH_ROLLOUT_USER_IDS", ""),
            ):
                marker = await enqueue_neo4j_user_rebuild(
                    db,
                    user_id=int(owner.id),
                    force=True,
                )
                assert marker is not None
                marker.status = "processed"
                marker.processed_at = utc_now_db()
                await db.flush()

                resilient = FallbackGraphStore(store, sql_store)
                rollout_store = Neo4jRolloutGraphStore(
                    db=db,
                    primary=resilient,
                    fallback=sql_store,
                )
                runtime_hits = await rollout_store.expand_claims(
                    user_id=int(owner.id),
                    claim_ids=(int(anchor.id),),
                    patterns=("direct_claim_relations", "shared_concept_claims"),
                    depth=2,
                    limit=10,
                )
                self.assertEqual(
                    {signature(row) for row in runtime_hits},
                    {signature(row) for row in sql_hits},
                )
                self.assertEqual(
                    rollout_store.last_diagnostics["effective_backend"],
                    "neo4j",
                )

                concept.description = "Mutation after verified rebuild"
                await db.flush()
                await enqueue_knowledge_object_projection(
                    db,
                    user_id=int(owner.id),
                    object_type="concept",
                    object_id=int(concept.id),
                )
                stale_guard_hits = await rollout_store.expand_claims(
                    user_id=int(owner.id),
                    claim_ids=(int(anchor.id),),
                    patterns=("direct_claim_relations", "shared_concept_claims"),
                    depth=2,
                    limit=10,
                )
                self.assertEqual(
                    {signature(row) for row in stale_guard_hits},
                    {signature(row) for row in sql_hits},
                )
                self.assertEqual(
                    rollout_store.last_diagnostics["route_reason"],
                    "projection_not_ready",
                )
                self.assertEqual(
                    rollout_store.last_diagnostics["effective_backend"],
                    "sql",
                )

            property_rows = await self.executor.execute(
                "MATCH (n {user_id:$user_id}) UNWIND keys(n) AS key RETURN DISTINCT key ORDER BY key",
                {"user_id": int(owner.id)},
            )
            properties = {str(row["key"]) for row in property_rows}
            self.assertTrue({"key", "user_id", "sql_id"}.issubset(properties))
            self.assertTrue(properties.isdisjoint({"statement", "text", "excerpt", "title", "content"}))

            await store.delete_source(user_id=int(owner.id), source_key=str(source_b.source_key))
            after_delete = await store.expand_claims(
                user_id=int(owner.id), claim_ids=(int(anchor.id),),
                patterns=("direct_claim_relations", "shared_concept_claims"), depth=2, limit=10,
            )
            self.assertNotIn(int(related.id), {row.object_id for row in after_delete})

            health = await store.health()
            self.assertTrue(health["ok"])


if __name__ == "__main__":
    unittest.main()
