"""Stage 7 Knowledge/Learning Path product-contract tests."""
from __future__ import annotations

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
from app.services.graph_store.base import (
    GraphCapabilityUnsupported,
    GraphEdgeRef,
    GraphNodeRef,
    GraphPath,
)
from app.services.knowledge_path_service import (
    KnowledgePathUnavailable,
    build_learning_paths,
)
from app.utils.utc import utc_now_db


class _FakeGraphStore:
    backend = "neo4j"

    def __init__(self, paths=None, error: Exception | None = None):
        self.paths = list(paths or [])
        self.error = error
        self.calls: list[dict] = []
        self.last_diagnostics = {
            "effective_backend": "neo4j",
            "route_reason": "neo4j_selected",
        }

    async def find_concept_paths(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return list(self.paths)


class KnowledgePathTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'knowledge-path.db'}"
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

    async def _concept(self, db, *, user_id: int, name: str) -> Concept:
        row = Concept(
            user_id=int(user_id),
            name=name,
            name_normalized=name.casefold(),
            description=f"About {name}",
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
            confidence=confidence,
            source=source,
            review_status="confirmed",
        )
        db.add(row)
        await db.flush()
        return row

    async def _state(
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
                reliability=confidence,
                model_version="test-v1",
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
                source_type="test",
                source_id=f"concept:{int(concept.id)}",
                observed_at=utc_now_db(),
                model_version="test-v1",
                payload_version=1,
                payload={},
            )
        )
        await db.flush()

    @staticmethod
    def _path(nodes: list[Concept], edges: list[ConceptEdge], *, traversed=None) -> GraphPath:
        node_refs = tuple(GraphNodeRef("concept", int(node.id)) for node in nodes)
        orientations = list(traversed or [True] * len(edges))
        edge_refs = tuple(
            GraphEdgeRef(
                edge_type="concept_edge",
                edge_id=int(edge.id),
                relation_type=str(edge.edge_type),
                from_node=GraphNodeRef("concept", int(edge.from_concept_id)),
                to_node=GraphNodeRef("concept", int(edge.to_concept_id)),
                directed=str(edge.edge_type) != "related_to",
                traversed_forward=bool(orientations[index]),
                confidence=float(edge.confidence),
            )
            for index, edge in enumerate(edges)
        )
        score = 1.0
        for edge in edges:
            score *= float(edge.confidence)
        return GraphPath(nodes=node_refs, edges=edge_refs, score=score)

    async def test_direct_path_rehydrates_mastery_and_confirmed_edge_evidence(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-direct-owner")
            start = await self._concept(db, user_id=owner.id, name="Tool Calling")
            target = await self._concept(db, user_id=owner.id, name="Agent Runtime")
            edge = await self._edge(db, user_id=owner.id, start=start, end=target)
            await self._state(db, user_id=owner.id, concept=start, mastery=85, confidence=0.9)
            await self._state(db, user_id=owner.id, concept=target, mastery=45, confidence=0.8)
            db.add(
                ConceptSourceEvidence(
                    user_id=int(owner.id),
                    concept_id=int(target.id),
                    edge_id=int(edge.id),
                    source_type="material",
                    source_id=77,
                    source_version=2,
                    excerpt="Agent Runtime depends on tool calling.",
                    confidence=0.92,
                    review_status="confirmed",
                )
            )
            await db.commit()

            fake = _FakeGraphStore([self._path([start, target], [edge])])
            with patch(
                "app.services.knowledge_path_service.create_graph_store",
                return_value=fake,
            ):
                result = await build_learning_paths(
                    db,
                    user_id=int(owner.id),
                    start_concept_ids=(int(start.id),),
                    target_concept_id=int(target.id),
                )

        self.assertEqual(result["status"], "ok")
        self.assertEqual(result["paths"][0]["depth"], 1)
        self.assertEqual(result["paths"][0]["nodes"][0]["learning_status"], "mastered")
        self.assertEqual(result["paths"][0]["nodes"][1]["learning_status"], "weak")
        self.assertEqual(result["paths"][0]["nodes"][0]["learner_evidence"]["direct"], 1)
        edge_payload = result["paths"][0]["edges"][0]
        self.assertEqual(edge_payload["provenance_status"], "confirmed_evidence")
        self.assertEqual(edge_payload["evidence"][0]["source_version"], 2)
        self.assertNotIn("edge_id", edge_payload)
        self.assertEqual(result["runtime"]["effective_backend"], "neo4j")

    async def test_multi_hop_path_preserves_order(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-multi-owner")
            a = await self._concept(db, user_id=owner.id, name="A")
            b = await self._concept(db, user_id=owner.id, name="B")
            c = await self._concept(db, user_id=owner.id, name="C")
            ab = await self._edge(db, user_id=owner.id, start=a, end=b, confidence=0.9)
            bc = await self._edge(db, user_id=owner.id, start=b, end=c, confidence=0.8)
            await db.commit()
            fake = _FakeGraphStore([self._path([a, b, c], [ab, bc])])
            with patch("app.services.knowledge_path_service.create_graph_store", return_value=fake):
                result = await build_learning_paths(
                    db,
                    user_id=int(owner.id),
                    start_concept_ids=(int(a.id),),
                    target_concept_id=int(c.id),
                )
        self.assertEqual([row["name"] for row in result["paths"][0]["nodes"]], ["A", "B", "C"])
        self.assertEqual(result["paths"][0]["depth"], 2)
        self.assertAlmostEqual(result["paths"][0]["score"], 0.72, places=6)

    async def test_missing_edge_evidence_is_explicit(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-missing-evidence")
            a = await self._concept(db, user_id=owner.id, name="A1")
            b = await self._concept(db, user_id=owner.id, name="B1")
            edge = await self._edge(db, user_id=owner.id, start=a, end=b, source="extract")
            await db.commit()
            fake = _FakeGraphStore([self._path([a, b], [edge])])
            with patch("app.services.knowledge_path_service.create_graph_store", return_value=fake):
                result = await build_learning_paths(
                    db,
                    user_id=int(owner.id),
                    start_concept_ids=(int(a.id),),
                    target_concept_id=int(b.id),
                )
        self.assertEqual(result["paths"][0]["edges"][0]["provenance_status"], "missing_evidence")
        self.assertEqual(result["paths"][0]["edges"][0]["evidence"], [])

    async def test_confirmed_manual_edge_without_excerpt_is_explicit(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-manual-evidence")
            a = await self._concept(db, user_id=owner.id, name="A2")
            b = await self._concept(db, user_id=owner.id, name="B2")
            edge = await self._edge(db, user_id=owner.id, start=a, end=b, source="manual")
            await db.commit()
            fake = _FakeGraphStore([self._path([a, b], [edge])])
            with patch("app.services.knowledge_path_service.create_graph_store", return_value=fake):
                result = await build_learning_paths(
                    db,
                    user_id=int(owner.id),
                    start_concept_ids=(int(a.id),),
                    target_concept_id=int(b.id),
                )
        self.assertEqual(result["paths"][0]["edges"][0]["provenance_status"], "confirmed_manual")

    async def test_related_to_reverse_traversal_is_marked_symmetric(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-related-owner")
            a = await self._concept(db, user_id=owner.id, name="A3")
            b = await self._concept(db, user_id=owner.id, name="B3")
            edge = await self._edge(
                db,
                user_id=owner.id,
                start=b,
                end=a,
                edge_type="related_to",
                source="manual",
            )
            await db.commit()
            fake = _FakeGraphStore([self._path([a, b], [edge], traversed=[False])])
            with patch("app.services.knowledge_path_service.create_graph_store", return_value=fake):
                result = await build_learning_paths(
                    db,
                    user_id=int(owner.id),
                    start_concept_ids=(int(a.id),),
                    target_concept_id=int(b.id),
                    relation_types=("related_to",),
                )
        payload = result["paths"][0]["edges"][0]
        self.assertFalse(payload["directed"])
        self.assertFalse(payload["traversed_forward"])
        self.assertEqual(payload["relation_type"], "related_to")

    async def test_no_path_is_not_fabricated(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-none-owner")
            a = await self._concept(db, user_id=owner.id, name="A4")
            b = await self._concept(db, user_id=owner.id, name="B4")
            await db.commit()
            fake = _FakeGraphStore([])
            with patch("app.services.knowledge_path_service.create_graph_store", return_value=fake):
                result = await build_learning_paths(
                    db,
                    user_id=int(owner.id),
                    start_concept_ids=(int(a.id),),
                    target_concept_id=int(b.id),
                )
        self.assertEqual(result["status"], "no_path")
        self.assertEqual(result["paths"], [])

    async def test_target_already_start_returns_depth_zero_without_graph_backend(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-zero-owner")
            concept = await self._concept(db, user_id=owner.id, name="Already Known")
            await self._state(db, user_id=owner.id, concept=concept, mastery=95, confidence=0.95)
            await db.commit()
            with patch(
                "app.services.knowledge_path_service.create_graph_store",
                side_effect=AssertionError("graph backend should not be created"),
            ):
                result = await build_learning_paths(
                    db,
                    user_id=int(owner.id),
                    start_concept_ids=(int(concept.id),),
                    target_concept_id=int(concept.id),
                )
        self.assertEqual(result["paths"][0]["depth"], 0)
        self.assertEqual(result["runtime"]["route_reason"], "target_is_start")

    async def test_foreign_requested_concept_is_not_visible(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-owner")
            stranger = await self._user(db, "path-stranger")
            start = await self._concept(db, user_id=owner.id, name="Owner Start")
            foreign = await self._concept(db, user_id=stranger.id, name="Foreign Target")
            await db.commit()
            with self.assertRaises(LookupError):
                await build_learning_paths(
                    db,
                    user_id=int(owner.id),
                    start_concept_ids=(int(start.id),),
                    target_concept_id=int(foreign.id),
                )

    async def test_foreign_intermediate_from_graph_is_rejected_during_sql_rehydrate(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-rehydrate-owner")
            stranger = await self._user(db, "path-rehydrate-stranger")
            start = await self._concept(db, user_id=owner.id, name="Safe Start")
            target = await self._concept(db, user_id=owner.id, name="Safe Target")
            foreign = await self._concept(db, user_id=stranger.id, name="Foreign Middle")
            edge_a = await self._edge(db, user_id=owner.id, start=start, end=target)
            await db.commit()
            bogus = GraphPath(
                nodes=(
                    GraphNodeRef("concept", int(start.id)),
                    GraphNodeRef("concept", int(foreign.id)),
                    GraphNodeRef("concept", int(target.id)),
                ),
                edges=(
                    GraphEdgeRef(
                        "concept_edge",
                        int(edge_a.id),
                        "prerequisite_of",
                        GraphNodeRef("concept", int(start.id)),
                        GraphNodeRef("concept", int(target.id)),
                    ),
                    GraphEdgeRef(
                        "concept_edge",
                        int(edge_a.id),
                        "prerequisite_of",
                        GraphNodeRef("concept", int(start.id)),
                        GraphNodeRef("concept", int(target.id)),
                    ),
                ),
            )
            fake = _FakeGraphStore([bogus])
            with patch("app.services.knowledge_path_service.create_graph_store", return_value=fake):
                with self.assertRaises(KnowledgePathUnavailable) as context:
                    await build_learning_paths(
                        db,
                        user_id=int(owner.id),
                        start_concept_ids=(int(start.id),),
                        target_concept_id=int(target.id),
                    )
        self.assertEqual(context.exception.reason, "path_rehydration_concept_mismatch")

    async def test_graph_capability_unavailable_is_mapped_to_safe_service_error(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-unavailable-owner")
            start = await self._concept(db, user_id=owner.id, name="Start Unavailable")
            target = await self._concept(db, user_id=owner.id, name="Target Unavailable")
            await db.commit()
            fake = _FakeGraphStore(error=GraphCapabilityUnsupported("secret-internal-detail"))
            fake.last_diagnostics = {
                "effective_backend": "sql",
                "route_reason": "rollout_not_selected",
            }
            with patch("app.services.knowledge_path_service.create_graph_store", return_value=fake):
                with self.assertRaises(KnowledgePathUnavailable) as context:
                    await build_learning_paths(
                        db,
                        user_id=int(owner.id),
                        start_concept_ids=(int(start.id),),
                        target_concept_id=int(target.id),
                    )
        self.assertEqual(context.exception.reason, "rollout_not_selected")
        self.assertNotIn("secret", str(context.exception))

    async def test_relation_allowlist_rejects_unknown_type_before_graph_query(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-relation-owner")
            start = await self._concept(db, user_id=owner.id, name="Relation Start")
            target = await self._concept(db, user_id=owner.id, name="Relation Target")
            await db.commit()
            with self.assertRaises(ValueError):
                await build_learning_paths(
                    db,
                    user_id=int(owner.id),
                    start_concept_ids=(int(start.id),),
                    target_concept_id=int(target.id),
                    relation_types=("totally_unknown",),
                )

    async def test_duplicate_start_ids_are_normalized_before_graph_query(self):
        async with self.sessions() as db:
            owner = await self._user(db, "path-dedupe-owner")
            start = await self._concept(db, user_id=owner.id, name="Dedupe Start")
            target = await self._concept(db, user_id=owner.id, name="Dedupe Target")
            await db.commit()
            fake = _FakeGraphStore([])
            with patch("app.services.knowledge_path_service.create_graph_store", return_value=fake):
                await build_learning_paths(
                    db,
                    user_id=int(owner.id),
                    start_concept_ids=(int(start.id), int(start.id)),
                    target_concept_id=int(target.id),
                )
        self.assertEqual(fake.calls[0]["start_concept_ids"], (int(start.id),))


if __name__ == "__main__":
    unittest.main()
