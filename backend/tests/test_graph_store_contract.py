"""Stage 7 storage-neutral GraphStore contract tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.config import settings
from app.services.graph_store.base import (
    GraphCapabilityUnsupported,
    GraphEdgeRef,
    GraphHit,
    GraphNodeRef,
    GraphPath,
)
from app.services.graph_store.factory import create_graph_store
from app.services.graph_store.fallback_store import FallbackGraphStore
from app.services.graph_store.sql_store import SqlGraphStore


class GraphPathDtoTests(unittest.TestCase):
    def test_path_preserves_canonical_direction_and_traversal_orientation(self):
        prerequisite = GraphNodeRef("concept", 10, {"name": "Tool Calling"})
        dependent = GraphNodeRef("concept", 20, {"name": "Agent Runtime"})
        edge = GraphEdgeRef(
            edge_type="concept_edge",
            edge_id=7,
            relation_type="prerequisite_of",
            from_node=prerequisite,
            to_node=dependent,
            directed=True,
            traversed_forward=False,
            confidence=0.9,
            evidence_ids=(101,),
        )
        path = GraphPath(nodes=(dependent, prerequisite), edges=(edge,), score=0.9)

        self.assertEqual(path.depth, 1)
        self.assertEqual(edge.from_node.object_id, 10)
        self.assertEqual(edge.to_node.object_id, 20)
        self.assertFalse(edge.traversed_forward)
        self.assertEqual(edge.evidence_ids, (101,))


class GraphBackendSelectionTests(unittest.TestCase):
    def test_sql_is_default_even_if_legacy_neo4j_flag_is_enabled(self):
        with (
            patch.object(settings, "GRAPH_BACKEND", "sql"),
            patch.object(settings, "NEO4J_GRAPH_ENABLED", True),
        ):
            store = create_graph_store(None)  # type: ignore[arg-type]
        self.assertIsInstance(store, SqlGraphStore)

    def test_neo4j_selection_requires_explicit_credentials(self):
        with (
            patch.object(settings, "GRAPH_BACKEND", "neo4j"),
            patch.object(settings, "NEO4J_PASSWORD", ""),
        ):
            with self.assertRaisesRegex(RuntimeError, "neo4j_graph_backend_not_configured"):
                create_graph_store(None)  # type: ignore[arg-type]

    def test_unknown_runtime_value_fails_closed(self):
        with patch.object(settings, "GRAPH_BACKEND", "mystery"):
            with self.assertRaisesRegex(ValueError, "unsupported_graph_backend:mystery"):
                create_graph_store(None)  # type: ignore[arg-type]


class FallbackGraphStoreTests(unittest.IsolatedAsyncioTestCase):
    async def test_read_failure_falls_back_without_exposing_exception_message(self):
        class BrokenPrimary:
            backend = "neo4j"

            async def expand_claims(self, **_kwargs):
                raise RuntimeError("MATCH secret-user-query-body")

        class SqlFallback:
            async def expand_claims(self, **_kwargs):
                return [GraphHit("claim", 42, "direct_claim_relations", 1, 0.8)]

        store = FallbackGraphStore(BrokenPrimary(), SqlFallback())  # type: ignore[arg-type]
        result = await store.expand_claims(
            user_id=1,
            claim_ids=(1,),
            patterns=("direct_claim_relations",),
        )

        self.assertEqual([hit.object_id for hit in result], [42])
        self.assertTrue(store.last_diagnostics["fallback_used"])
        self.assertTrue(store.last_diagnostics["fallback_succeeded"])
        self.assertEqual(store.last_diagnostics["primary_error_type"], "RuntimeError")
        self.assertNotIn("secret-user-query-body", repr(store.last_diagnostics))

    async def test_health_distinguishes_primary_failure_from_serving_fallback(self):
        class UnhealthyPrimary:
            backend = "neo4j"

            async def health(self):
                return {"ok": False, "backend": "neo4j", "error": "connection refused"}

        class HealthyFallback:
            async def health(self):
                return {"ok": True, "backend": "sql", "authoritative": True}

        store = FallbackGraphStore(UnhealthyPrimary(), HealthyFallback())  # type: ignore[arg-type]
        health = await store.health()
        self.assertFalse(health["ok"])
        self.assertTrue(health["serving_ok"])
        self.assertTrue(health["fallback_available"])

    async def test_projection_rebuild_failure_does_not_fallback(self):
        calls: list[str] = []

        class BrokenPrimary:
            backend = "neo4j"

            async def rebuild_user(self, **_kwargs):
                raise RuntimeError("projection unavailable")

        class SqlFallback:
            async def rebuild_user(self, **_kwargs):
                calls.append("fallback")
                return {"rebuilt": False}

        store = FallbackGraphStore(BrokenPrimary(), SqlFallback())  # type: ignore[arg-type]
        with self.assertRaisesRegex(RuntimeError, "projection unavailable"):
            await store.rebuild_user(user_id=1)
        self.assertEqual(calls, [])


class SqlGraphCapabilityTests(unittest.IsolatedAsyncioTestCase):
    async def test_generic_concept_path_search_is_explicitly_not_implemented(self):
        store = SqlGraphStore(None)  # type: ignore[arg-type]
        with self.assertRaisesRegex(
            GraphCapabilityUnsupported,
            "concept_path_search_not_supported_by_sql_backend",
        ):
            await store.find_concept_paths(
                user_id=1,
                start_concept_ids=(10,),
                target_concept_ids=(20,),
                relation_types=("prerequisite_of",),
                direction="outgoing",
                max_depth=4,
                limit=3,
            )


if __name__ == "__main__":
    unittest.main()
