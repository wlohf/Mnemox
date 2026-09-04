"""Real Neo4j integration gate for Stage 7 Knowledge/Learning Path.

Run with MNEMOX_TEST_NEO4J_URI / USER / PASSWORD. The Neo4j database is treated
as disposable test infrastructure and user-scoped projection data is rebuilt
from temporary canonical SQLite rows.
"""
from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.concept import Concept, ConceptEdge, ConceptSourceEvidence
from app.models.learner_model import LearnerEvidence, UserConceptState
from app.models.user import User
from app.services.graph_store.fallback_store import FallbackGraphStore
from app.services.graph_store.neo4j_store import Neo4jAsyncExecutor, Neo4jGraphStore
from app.services.graph_store.rollout_store import Neo4jRolloutGraphStore
from app.services.graph_store.sql_store import SqlGraphStore
from app.services.knowledge_path_service import KnowledgePathUnavailable, build_learning_paths
from app.services.knowledge_projection_service import (
    enqueue_knowledge_object_projection,
    enqueue_neo4j_user_rebuild,
)
from app.utils.utc import utc_now_db


NEO4J_URI = os.environ.get("MNEMOX_TEST_NEO4J_URI", "").strip()
NEO4J_USER = os.environ.get("MNEMOX_TEST_NEO4J_USER", "neo4j").strip()
NEO4J_PASSWORD = os.environ.get("MNEMOX_TEST_NEO4J_PASSWORD", "stage7-path-test").strip()
NEO4J_DATABASE = os.environ.get("MNEMOX_TEST_NEO4J_DATABASE", "neo4j").strip()


@unittest.skipUnless(NEO4J_URI and NEO4J_PASSWORD, "Neo4j Knowledge Path test credentials are required")
class Neo4jKnowledgePathIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'neo4j-knowledge-path.db'}"
        )
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

    async def _concept(self, db, *, user_id: int, name: str) -> Concept:
        row = Concept(
            user_id=int(user_id),
            name=name,
            name_normalized=name.casefold(),
            source="manual",
            review_status="confirmed",
        )
        db.add(row)
        await db.flush()
        return row

    async def _edge(
        self,
        db,
        *,
        user_id: int,
        start: Concept,
        end: Concept,
        edge_type: str = "prerequisite_of",
        confidence: float = 0.9,
        source: str = "extract",
    ) -> ConceptEdge:
        row = ConceptEdge(
            user_id=int(user_id),
            from_concept_id=int(start.id),
            to_concept_id=int(end.id),
            edge_type=edge_type,
            confidence=float(confidence),
            source=source,
            review_status="confirmed",
        )
        db.add(row)
        await db.flush()
        return row

    async def _learner_state(
        self,
        db,
        *,
        user_id: int,
        concept: Concept,
        mastery: float,
        confidence: float,
    ) -> None:
        db.add(
            UserConceptState(
                user_id=int(user_id),
                concept_id=int(concept.id),
                mastery_estimate=float(mastery),
                confidence=float(confidence),
                forgetting_risk=max(0.0, min(1.0, 1.0 - float(mastery) / 100.0)),
                mastery_dimensions={},
                reliability=float(confidence),
                model_version="path-int-v1",
                explanation_summary={},
            )
        )
        db.add(
            LearnerEvidence(
                user_id=int(user_id),
                concept_id=int(concept.id),
                evidence_type="recall",
                evidence_category="direct",
                score=max(0.0, min(1.0, float(mastery) / 100.0)),
                reliability=float(confidence),
                source_type="integration",
                source_id=f"concept:{int(concept.id)}",
                observed_at=utc_now_db(),
                model_version="path-int-v1",
                payload_version=1,
                payload={},
            )
        )
        await db.flush()

    async def test_bounded_direction_order_cycle_and_evidence_ids(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-neo4j-owner")
            stranger = await self._user(db, "path-neo4j-stranger")
            a = await self._concept(db, user_id=owner.id, name="A")
            b = await self._concept(db, user_id=owner.id, name="B")
            c = await self._concept(db, user_id=owner.id, name="C")
            d = await self._concept(db, user_id=owner.id, name="D")
            e = await self._concept(db, user_id=owner.id, name="E")
            foreign = await self._concept(db, user_id=stranger.id, name="Foreign")

            direct = await self._edge(
                db, user_id=owner.id, start=a, end=d, confidence=0.35, source="manual"
            )
            ab = await self._edge(db, user_id=owner.id, start=a, end=b, confidence=0.9)
            bd = await self._edge(db, user_id=owner.id, start=b, end=d, confidence=0.8)
            ac = await self._edge(db, user_id=owner.id, start=a, end=c, confidence=0.95)
            cd = await self._edge(db, user_id=owner.id, start=c, end=d, confidence=0.7)
            # Cycle edge: a simple path may use it, but no returned path may repeat a node.
            await self._edge(db, user_id=owner.id, start=d, end=a, confidence=0.99)
            # Stored opposite to the requested A -> E traversal; RELATED_TO is symmetric.
            related = await self._edge(
                db,
                user_id=owner.id,
                start=e,
                end=a,
                edge_type="related_to",
                confidence=0.88,
                source="manual",
            )
            db.add(
                ConceptSourceEvidence(
                    user_id=int(owner.id),
                    concept_id=int(b.id),
                    edge_id=int(ab.id),
                    source_type="material",
                    source_id=55,
                    source_version=1,
                    excerpt="A is required before B.",
                    confidence=0.94,
                    review_status="confirmed",
                )
            )
            # This edge points at a foreign Concept and must not be projected for owner.
            await self._edge(
                db,
                user_id=owner.id,
                start=d,
                end=foreign,
                confidence=1.0,
            )
            await db.commit()

            store = Neo4jGraphStore(db, executor=self.executor)
            rebuilt = await store.rebuild_user(user_id=int(owner.id))
            self.assertEqual(rebuilt["concepts"], 5)

            paths = await store.find_concept_paths(
                user_id=int(owner.id),
                start_concept_ids=(int(a.id),),
                target_concept_ids=(int(d.id),),
                relation_types=("prerequisite_of",),
                direction="outgoing",
                max_depth=4,
                limit=5,
            )
            self.assertGreaterEqual(len(paths), 3)
            # Shortest path wins even when its edge confidence is lower.
            self.assertEqual(paths[0].depth, 1)
            self.assertEqual([node.object_id for node in paths[0].nodes], [int(a.id), int(d.id)])
            self.assertEqual(paths[0].edges[0].edge_id, int(direct.id))

            depth_two = [path for path in paths if path.depth == 2]
            self.assertGreaterEqual(len(depth_two), 2)
            # A-B-D score .72 beats A-C-D score .665 at equal depth.
            self.assertEqual(
                [node.object_id for node in depth_two[0].nodes],
                [int(a.id), int(b.id), int(d.id)],
            )
            self.assertAlmostEqual(depth_two[0].score, 0.72, places=6)
            self.assertIn(
                int(
                    await db.scalar(
                        __import__("sqlalchemy").select(ConceptSourceEvidence.id).where(
                            ConceptSourceEvidence.edge_id == int(ab.id)
                        )
                    )
                ),
                depth_two[0].edges[0].evidence_ids,
            )
            for path in paths:
                node_ids = [node.object_id for node in path.nodes]
                self.assertEqual(len(node_ids), len(set(node_ids)))
                self.assertNotIn(int(foreign.id), node_ids)

            incoming = await store.find_concept_paths(
                user_id=int(owner.id),
                start_concept_ids=(int(d.id),),
                target_concept_ids=(int(a.id),),
                relation_types=("prerequisite_of",),
                direction="incoming",
                max_depth=1,
                limit=3,
            )
            self.assertTrue(incoming)
            self.assertFalse(incoming[0].edges[0].traversed_forward)

            symmetric = await store.find_concept_paths(
                user_id=int(owner.id),
                start_concept_ids=(int(a.id),),
                target_concept_ids=(int(e.id),),
                relation_types=("related_to",),
                direction="outgoing",
                max_depth=1,
                limit=3,
            )
            self.assertEqual(len(symmetric), 1)
            self.assertEqual(symmetric[0].edges[0].edge_id, int(related.id))
            self.assertFalse(symmetric[0].edges[0].directed)
            self.assertFalse(symmetric[0].edges[0].traversed_forward)

    async def test_end_to_end_overlay_and_stale_gate(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-runtime-owner")
            start = await self._concept(db, user_id=owner.id, name="Tool Calling")
            middle = await self._concept(db, user_id=owner.id, name="Agent Runtime")
            target = await self._concept(db, user_id=owner.id, name="LangGraph")
            edge_a = await self._edge(db, user_id=owner.id, start=start, end=middle, confidence=0.9)
            edge_b = await self._edge(db, user_id=owner.id, start=middle, end=target, confidence=0.8)
            await self._learner_state(
                db, user_id=owner.id, concept=start, mastery=88, confidence=0.9
            )
            await self._learner_state(
                db, user_id=owner.id, concept=middle, mastery=42, confidence=0.8
            )
            db.add(
                ConceptSourceEvidence(
                    user_id=int(owner.id),
                    concept_id=int(middle.id),
                    edge_id=int(edge_a.id),
                    source_type="material",
                    source_id=81,
                    source_version=1,
                    excerpt="Tool calling is a prerequisite for the runtime layer.",
                    confidence=0.91,
                    review_status="confirmed",
                )
            )
            await db.commit()

            neo4j = Neo4jGraphStore(db, executor=self.executor)
            await neo4j.rebuild_user(user_id=int(owner.id))
            sql = SqlGraphStore(db)
            resilient = FallbackGraphStore(neo4j, sql)
            rollout = Neo4jRolloutGraphStore(db=db, primary=resilient, fallback=sql)

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

                with patch(
                    "app.services.knowledge_path_service.create_graph_store",
                    return_value=rollout,
                ):
                    result = await build_learning_paths(
                        db,
                        user_id=int(owner.id),
                        start_concept_ids=(int(start.id),),
                        target_concept_id=int(target.id),
                        max_depth=4,
                    )
                self.assertEqual(result["status"], "ok")
                self.assertEqual(result["runtime"]["effective_backend"], "neo4j")
                self.assertEqual(
                    [node["name"] for node in result["paths"][0]["nodes"]],
                    ["Tool Calling", "Agent Runtime", "LangGraph"],
                )
                self.assertEqual(result["paths"][0]["nodes"][0]["learning_status"], "mastered")
                self.assertEqual(result["paths"][0]["nodes"][1]["learning_status"], "weak")
                self.assertEqual(
                    result["paths"][0]["edges"][0]["provenance_status"],
                    "confirmed_evidence",
                )
                self.assertEqual(
                    result["paths"][0]["edges"][1]["provenance_status"],
                    "missing_evidence",
                )

                # Canonical mutation requeues projection. Graph-native path must
                # become unavailable rather than returning the now-stale graph.
                middle.description = "Canonical mutation after rebuild"
                await db.flush()
                await enqueue_knowledge_object_projection(
                    db,
                    user_id=int(owner.id),
                    object_type="concept",
                    object_id=int(middle.id),
                )
                with patch(
                    "app.services.knowledge_path_service.create_graph_store",
                    return_value=rollout,
                ):
                    with self.assertRaises(KnowledgePathUnavailable) as context:
                        await build_learning_paths(
                            db,
                            user_id=int(owner.id),
                            start_concept_ids=(int(start.id),),
                            target_concept_id=int(target.id),
                            max_depth=4,
                        )
                self.assertEqual(context.exception.reason, "projection_not_ready")
                self.assertEqual(rollout.last_diagnostics["effective_backend"], "sql")


if __name__ == "__main__":
    unittest.main()
