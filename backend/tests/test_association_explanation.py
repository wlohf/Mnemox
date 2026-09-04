"""Stage 7 Phase 3.2 presentation-safe Association explanation tests."""
from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from sqlalchemy import text
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.concept import Concept, ConceptEdge, ConceptSourceEvidence
from app.models.user import User
from app.services.association_explanation_service import build_association_explanation
from app.services.graph_store.base import GraphEdgeRef, GraphNodeRef, GraphPath


class _FakeGraphStore:
    backend = "neo4j"

    def __init__(self, paths=None, error: Exception | None = None):
        self.paths = list(paths or [])
        self.error = error
        self.calls: list[dict] = []

    async def find_concept_paths(self, **kwargs):
        self.calls.append(dict(kwargs))
        if self.error is not None:
            raise self.error
        return list(self.paths)


class AssociationExplanationTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'association-explanation.db'}"
        )
        async with self.engine.begin() as connection:
            await connection.execute(text("PRAGMA foreign_keys=ON"))
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

    async def _edge(self, db, *, user_id: int, start: Concept, end: Concept, edge_type="prerequisite_of") -> ConceptEdge:
        row = ConceptEdge(
            user_id=int(user_id),
            from_concept_id=int(start.id),
            to_concept_id=int(end.id),
            edge_type=edge_type,
            confidence=0.9,
            source="extract",
            review_status="confirmed",
        )
        db.add(row)
        await db.flush()
        return row

    @staticmethod
    def _path(nodes: list[Concept], edges: list[ConceptEdge]) -> GraphPath:
        return GraphPath(
            nodes=tuple(GraphNodeRef("concept", int(node.id)) for node in nodes),
            edges=tuple(
                GraphEdgeRef(
                    edge_type="concept_edge",
                    edge_id=int(edge.id),
                    relation_type=str(edge.edge_type),
                    from_node=GraphNodeRef("concept", int(edge.from_concept_id)),
                    to_node=GraphNodeRef("concept", int(edge.to_concept_id)),
                    directed=str(edge.edge_type) != "related_to",
                    traversed_forward=True,
                    confidence=float(edge.confidence),
                )
                for edge in edges
            ),
            score=0.9 ** len(edges),
        )

    async def test_shared_concept_explanation_needs_no_graph_and_leaks_no_ids(self):
        async with self.sessions() as db:
            user = await self._user(db, "shared-owner")
            concept = await self._concept(db, user_id=user.id, name="Tool Calling")
            graph = _FakeGraphStore(error=AssertionError("graph should not be called"))
            with patch(
                "app.services.association_explanation_service._related_concepts",
                return_value=(int(concept.id),),
            ):
                result = await build_association_explanation(
                    db,
                    user_id=user.id,
                    anchor_concept_ids=(concept.id,),
                    related_claim_id=999,
                    graph_store=graph,
                )

        self.assertEqual(result["summary"], "共同关联到「Tool Calling」")
        self.assertEqual(graph.calls, [])
        rendered = repr(result)
        self.assertNotIn("concept_id", rendered)
        self.assertNotIn("claim_id", rendered)
        self.assertNotIn("edge_id", rendered)

    async def test_multihop_rehydrates_sql_names_direction_and_evidence_without_internal_ids(self):
        async with self.sessions() as db:
            user = await self._user(db, "multi-owner")
            start = await self._concept(db, user_id=user.id, name="Tool Calling")
            middle = await self._concept(db, user_id=user.id, name="Agent Runtime")
            target = await self._concept(db, user_id=user.id, name="LangGraph")
            first = await self._edge(db, user_id=user.id, start=start, end=middle)
            second = await self._edge(db, user_id=user.id, start=middle, end=target, edge_type="related_to")
            db.add(
                ConceptSourceEvidence(
                    user_id=user.id,
                    concept_id=middle.id,
                    edge_id=first.id,
                    source_type="material",
                    source_id=42,
                    source_version=2,
                    excerpt="Tool Calling is a prerequisite for the Agent Runtime layer.",
                    confidence=0.95,
                    review_status="confirmed",
                )
            )
            await db.flush()
            graph = _FakeGraphStore(paths=[self._path([start, middle, target], [first, second])])
            with patch(
                "app.services.association_explanation_service._related_concepts",
                return_value=(int(target.id),),
            ):
                result = await build_association_explanation(
                    db,
                    user_id=user.id,
                    anchor_concept_ids=(start.id,),
                    related_claim_id=1000,
                    graph_store=graph,
                )

        self.assertIn("prerequisite_of → related_to", result["summary"])
        relations = [step for step in result["steps"] if step["type"] == "relation"]
        self.assertEqual([row["relation_type"] for row in relations], ["prerequisite_of", "related_to"])
        self.assertEqual(relations[0]["provenance_status"], "confirmed_evidence")
        self.assertEqual(relations[1]["provenance_status"], "missing_evidence")
        self.assertEqual(result["evidence"][0]["source_id"], 42)
        rendered = repr(result)
        for forbidden in ("concept_id", "claim_id", "edge_id", "sql_id", "cypher"):
            self.assertNotIn(forbidden, rendered.casefold())

    async def test_foreign_or_mismatched_path_is_discarded(self):
        async with self.sessions() as db:
            owner = await self._user(db, "owner")
            other = await self._user(db, "other")
            start = await self._concept(db, user_id=owner.id, name="Start")
            target = await self._concept(db, user_id=owner.id, name="Target")
            foreign_a = await self._concept(db, user_id=other.id, name="Foreign A")
            foreign_b = await self._concept(db, user_id=other.id, name="Foreign B")
            foreign_edge = await self._edge(db, user_id=other.id, start=foreign_a, end=foreign_b)
            graph = _FakeGraphStore(paths=[self._path([start, target], [foreign_edge])])
            with patch(
                "app.services.association_explanation_service._related_concepts",
                return_value=(int(target.id),),
            ):
                result = await build_association_explanation(
                    db,
                    user_id=owner.id,
                    anchor_concept_ids=(start.id,),
                    related_claim_id=1001,
                    graph_store=graph,
                )
        self.assertIsNone(result)

    async def test_graph_failure_is_optional_enrichment_failure(self):
        async with self.sessions() as db:
            user = await self._user(db, "failure-owner")
            start = await self._concept(db, user_id=user.id, name="Start")
            target = await self._concept(db, user_id=user.id, name="Target")
            graph = _FakeGraphStore(error=RuntimeError("MATCH secret-query"))
            with patch(
                "app.services.association_explanation_service._related_concepts",
                return_value=(int(target.id),),
            ):
                result = await build_association_explanation(
                    db,
                    user_id=user.id,
                    anchor_concept_ids=(start.id,),
                    related_claim_id=1002,
                    graph_store=graph,
                )
        self.assertIsNone(result)


if __name__ == "__main__":
    unittest.main()
