"""Stage 7 Neo4j per-user rollout and stale-projection read-gate tests."""
from __future__ import annotations

import unittest
from unittest.mock import patch

from app.config import settings
from app.services.graph_store.base import GraphHit
from app.services.graph_store.fallback_store import FallbackGraphStore
from app.services.graph_store.rollout_store import (
    Neo4jRolloutGraphStore,
    neo4j_rollout_bucket,
    neo4j_rollout_decision,
    parse_rollout_user_ids,
)


class RolloutPolicyTests(unittest.TestCase):
    def test_rollout_bucket_is_stable_and_bounded(self):
        first = neo4j_rollout_bucket(123)
        second = neo4j_rollout_bucket(123)
        self.assertEqual(first, second)
        self.assertGreaterEqual(first, 0)
        self.assertLess(first, 100)

    def test_zero_and_full_percent_have_explicit_semantics(self):
        self.assertFalse(
            neo4j_rollout_decision(
                user_id=7,
                percent=0,
                forced_user_ids=frozenset(),
            )["selected"]
        )
        self.assertTrue(
            neo4j_rollout_decision(
                user_id=7,
                percent=100,
                forced_user_ids=frozenset(),
            )["selected"]
        )

    def test_forced_user_bypasses_percentage_without_accepting_invalid_ids(self):
        parsed = parse_rollout_user_ids("7, nope, -3, 11,7")
        self.assertEqual(parsed, frozenset({7, 11}))
        decision = neo4j_rollout_decision(
            user_id=7,
            percent=0,
            forced_user_ids=parsed,
        )
        self.assertTrue(decision["selected"])
        self.assertTrue(decision["forced"])


class RolloutReadGateTests(unittest.IsolatedAsyncioTestCase):
    async def test_user_outside_rollout_goes_directly_to_sql(self):
        calls: list[str] = []

        class Primary:
            async def expand_claims(self, **_kwargs):
                calls.append("primary")
                return [GraphHit("claim", 1, "direct_claim_relations", 1, 1.0)]

        class Sql:
            async def expand_claims(self, **_kwargs):
                calls.append("sql")
                return [GraphHit("claim", 2, "direct_claim_relations", 1, 1.0)]

        async def projection_summary(_db, *, user_id: int):
            calls.append(f"projection:{user_id}")
            return {"status_counts": {}, "dead_letter_count": 0}

        store = Neo4jRolloutGraphStore(
            db=None,  # type: ignore[arg-type]
            primary=Primary(),  # type: ignore[arg-type]
            fallback=Sql(),  # type: ignore[arg-type]
            projection_summary=projection_summary,
        )
        with (
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_PERCENT", 0),
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_USER_IDS", ""),
        ):
            result = await store.expand_claims(
                user_id=7,
                claim_ids=(1,),
                patterns=("direct_claim_relations",),
            )

        self.assertEqual([hit.object_id for hit in result], [2])
        self.assertEqual(calls, ["sql"])
        self.assertEqual(store.last_diagnostics["route_reason"], "rollout_not_selected")
        self.assertEqual(store.last_diagnostics["effective_backend"], "sql")

    async def test_selected_user_with_stale_projection_goes_directly_to_sql(self):
        calls: list[str] = []

        class Primary:
            async def expand_claims(self, **_kwargs):
                calls.append("primary")
                return []

        class Sql:
            async def expand_claims(self, **_kwargs):
                calls.append("sql")
                return [GraphHit("claim", 2, "direct_claim_relations", 1, 1.0)]

        async def projection_summary(_db, *, user_id: int):
            calls.append(f"projection:{user_id}")
            return {
                "status_counts": {"pending": 1, "processed": 8},
                "dead_letter_count": 0,
                "initialized": True,
            }

        store = Neo4jRolloutGraphStore(
            db=None,  # type: ignore[arg-type]
            primary=Primary(),  # type: ignore[arg-type]
            fallback=Sql(),  # type: ignore[arg-type]
            projection_summary=projection_summary,
        )
        with (
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_PERCENT", 100),
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_USER_IDS", ""),
        ):
            result = await store.expand_claims(
                user_id=7,
                claim_ids=(1,),
                patterns=("direct_claim_relations",),
            )

        self.assertEqual([hit.object_id for hit in result], [2])
        self.assertEqual(calls, ["projection:7", "sql"])
        self.assertEqual(store.last_diagnostics["route_reason"], "projection_not_ready")
        self.assertEqual(
            store.last_diagnostics["projection_blocking_counts"]["pending"],
            1,
        )

    async def test_selected_user_without_initial_rebuild_goes_directly_to_sql(self):
        calls: list[str] = []

        class Primary:
            async def expand_claims(self, **_kwargs):
                calls.append("primary")
                return []

        class Sql:
            async def expand_claims(self, **_kwargs):
                calls.append("sql")
                return [GraphHit("claim", 6, "direct_claim_relations", 1, 1.0)]

        async def projection_summary(_db, *, user_id: int):
            calls.append(f"projection:{user_id}")
            return {
                "status_counts": {},
                "dead_letter_count": 0,
                "initialized": False,
            }

        store = Neo4jRolloutGraphStore(
            db=None,  # type: ignore[arg-type]
            primary=Primary(),  # type: ignore[arg-type]
            fallback=Sql(),  # type: ignore[arg-type]
            projection_summary=projection_summary,
        )
        with (
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_PERCENT", 100),
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_USER_IDS", ""),
        ):
            result = await store.expand_claims(
                user_id=7,
                claim_ids=(1,),
                patterns=("direct_claim_relations",),
            )

        self.assertEqual([hit.object_id for hit in result], [6])
        self.assertEqual(calls, ["projection:7", "sql"])
        self.assertEqual(store.last_diagnostics["route_reason"], "projection_not_ready")
        self.assertEqual(
            store.last_diagnostics["projection_blocking_counts"]["uninitialized"],
            1,
        )

    async def test_projection_status_failure_fails_safe_to_sql_without_message_leak(self):
        calls: list[str] = []

        class Primary:
            async def expand_claims(self, **_kwargs):
                calls.append("primary")
                return []

        class Sql:
            async def expand_claims(self, **_kwargs):
                calls.append("sql")
                return [GraphHit("claim", 3, "direct_claim_relations", 1, 1.0)]

        async def projection_summary(_db, *, user_id: int):
            raise RuntimeError(f"secret projection query for {user_id}")

        store = Neo4jRolloutGraphStore(
            db=None,  # type: ignore[arg-type]
            primary=Primary(),  # type: ignore[arg-type]
            fallback=Sql(),  # type: ignore[arg-type]
            projection_summary=projection_summary,
        )
        with (
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_PERCENT", 100),
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_USER_IDS", ""),
        ):
            result = await store.expand_claims(
                user_id=7,
                claim_ids=(1,),
                patterns=("direct_claim_relations",),
            )

        self.assertEqual([hit.object_id for hit in result], [3])
        self.assertEqual(calls, ["sql"])
        self.assertEqual(store.last_diagnostics["route_reason"], "projection_status_unavailable")
        self.assertEqual(store.last_diagnostics["projection_error_type"], "RuntimeError")
        self.assertNotIn("secret projection query", repr(store.last_diagnostics))

    async def test_caught_up_selected_user_uses_neo4j_primary(self):
        calls: list[str] = []

        class Primary:
            last_diagnostics = {"fallback_used": False}

            async def expand_claims(self, **_kwargs):
                calls.append("primary")
                return [GraphHit("claim", 4, "direct_claim_relations", 1, 1.0)]

        class Sql:
            async def expand_claims(self, **_kwargs):
                calls.append("sql")
                return []

        async def projection_summary(_db, *, user_id: int):
            calls.append(f"projection:{user_id}")
            return {
                "status_counts": {"processed": 9},
                "dead_letter_count": 0,
                "initialized": True,
            }

        store = Neo4jRolloutGraphStore(
            db=None,  # type: ignore[arg-type]
            primary=Primary(),  # type: ignore[arg-type]
            fallback=Sql(),  # type: ignore[arg-type]
            projection_summary=projection_summary,
        )
        with (
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_PERCENT", 100),
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_USER_IDS", ""),
        ):
            result = await store.expand_claims(
                user_id=7,
                claim_ids=(1,),
                patterns=("direct_claim_relations",),
            )

        self.assertEqual([hit.object_id for hit in result], [4])
        self.assertEqual(calls, ["projection:7", "primary"])
        self.assertEqual(store.last_diagnostics["route_reason"], "neo4j_selected")
        self.assertEqual(store.last_diagnostics["effective_backend"], "neo4j")

    async def test_admitted_primary_failure_uses_existing_sql_fallback(self):
        class BrokenNeo4j:
            backend = "neo4j"

            async def expand_claims(self, **_kwargs):
                raise ConnectionError("bolt://user:secret@example.invalid")

        class Sql:
            async def expand_claims(self, **_kwargs):
                return [GraphHit("claim", 5, "direct_claim_relations", 1, 1.0)]

        async def projection_summary(_db, *, user_id: int):
            return {
                "status_counts": {"processed": 1},
                "dead_letter_count": 0,
                "initialized": True,
            }

        sql = Sql()
        resilient = FallbackGraphStore(BrokenNeo4j(), sql)  # type: ignore[arg-type]
        store = Neo4jRolloutGraphStore(
            db=None,  # type: ignore[arg-type]
            primary=resilient,
            fallback=sql,  # type: ignore[arg-type]
            projection_summary=projection_summary,
        )
        with (
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_PERCENT", 100),
            patch.object(settings, "NEO4J_GRAPH_ROLLOUT_USER_IDS", ""),
        ):
            result = await store.expand_claims(
                user_id=7,
                claim_ids=(1,),
                patterns=("direct_claim_relations",),
            )

        self.assertEqual([hit.object_id for hit in result], [5])
        self.assertEqual(store.last_diagnostics["route_reason"], "primary_fallback")
        self.assertEqual(store.last_diagnostics["effective_backend"], "sql")
        self.assertNotIn("secret", repr(store.last_diagnostics))


if __name__ == "__main__":
    unittest.main()
