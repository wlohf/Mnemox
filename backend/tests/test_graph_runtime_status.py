from __future__ import annotations

import unittest
from unittest.mock import AsyncMock, Mock, patch


class _Store:
    def __init__(self, health: dict):
        self._health = health

    async def health(self) -> dict:
        return dict(self._health)


class GraphRuntimeStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_sql_backend_is_ready_without_projection_gate(self) -> None:
        from app.services.graph_runtime_status_service import graph_runtime_status

        db = Mock()
        with (
            patch("app.services.graph_runtime_status_service.settings.GRAPH_BACKEND", "sql"),
            patch(
                "app.services.graph_runtime_status_service.create_graph_store",
                return_value=_Store({"ok": True, "backend": "sql", "authoritative": True}),
            ),
            patch(
                "app.services.graph_runtime_status_service.neo4j_projection_lag_summary",
                new=AsyncMock(side_effect=AssertionError("sql must not inspect neo4j lag")),
            ),
        ):
            status = await graph_runtime_status(db, user_id=7)

        self.assertEqual(status["selected_backend"], "sql")
        self.assertFalse(status["projection_required"])
        self.assertTrue(status["primary_ready"])
        self.assertTrue(status["serving_ready"])
        self.assertIsNone(status["projection"])

    async def test_neo4j_requires_health_and_caught_up_projection(self) -> None:
        from app.services.graph_runtime_status_service import graph_runtime_status

        db = Mock()
        with (
            patch("app.services.graph_runtime_status_service.settings.GRAPH_BACKEND", "neo4j"),
            patch(
                "app.services.graph_runtime_status_service.create_graph_store",
                return_value=_Store(
                    {
                        "ok": True,
                        "serving_ok": True,
                        "backend": "neo4j",
                        "fallback_available": True,
                    }
                ),
            ),
            patch(
                "app.services.graph_runtime_status_service.neo4j_projection_lag_summary",
                new=AsyncMock(
                    return_value={
                        "backend": "neo4j",
                        "tasks_total": 10,
                        "status_counts": {"processed": 10},
                        "oldest_pending_age_seconds": 0.0,
                        "latest_processed_lag_seconds": 0.4,
                        "dead_letter_count": 0,
                        "initialized": True,
                    }
                ),
            ),
        ):
            status = await graph_runtime_status(db, user_id=7)

        self.assertTrue(status["projection_required"])
        self.assertTrue(status["projection"]["caught_up"])
        self.assertTrue(status["primary_ready"])
        self.assertTrue(status["serving_ready"])

    async def test_ready_user_outside_rollout_serves_sql_without_marking_primary_unhealthy(self) -> None:
        from app.services.graph_runtime_status_service import graph_runtime_status

        db = Mock()
        with (
            patch("app.services.graph_runtime_status_service.settings.GRAPH_BACKEND", "neo4j"),
            patch("app.services.graph_runtime_status_service.settings.NEO4J_GRAPH_ROLLOUT_PERCENT", 0),
            patch("app.services.graph_runtime_status_service.settings.NEO4J_GRAPH_ROLLOUT_USER_IDS", ""),
            patch(
                "app.services.graph_runtime_status_service.create_graph_store",
                return_value=_Store(
                    {
                        "ok": True,
                        "serving_ok": True,
                        "backend": "neo4j",
                        "fallback_available": True,
                    }
                ),
            ),
            patch(
                "app.services.graph_runtime_status_service.neo4j_projection_lag_summary",
                new=AsyncMock(
                    return_value={
                        "backend": "neo4j",
                        "tasks_total": 1,
                        "status_counts": {"processed": 1},
                        "oldest_pending_age_seconds": 0.0,
                        "latest_processed_lag_seconds": 0.1,
                        "dead_letter_count": 0,
                        "initialized": True,
                    }
                ),
            ),
        ):
            status = await graph_runtime_status(db, user_id=7)

        self.assertTrue(status["primary_ready"])
        self.assertTrue(status["serving_ready"])
        self.assertFalse(status["neo4j_read_enabled"])
        self.assertFalse(status["rollout"]["selected"])
        self.assertEqual(status["effective_backend"], "sql")

    async def test_neo4j_pending_projection_blocks_primary_but_not_safe_serving(self) -> None:
        from app.services.graph_runtime_status_service import graph_runtime_status

        db = Mock()
        with (
            patch("app.services.graph_runtime_status_service.settings.GRAPH_BACKEND", "neo4j"),
            patch(
                "app.services.graph_runtime_status_service.create_graph_store",
                return_value=_Store(
                    {
                        "ok": True,
                        "serving_ok": True,
                        "backend": "neo4j",
                        "fallback_available": True,
                    }
                ),
            ),
            patch(
                "app.services.graph_runtime_status_service.neo4j_projection_lag_summary",
                new=AsyncMock(
                    return_value={
                        "backend": "neo4j",
                        "tasks_total": 11,
                        "status_counts": {"processed": 10, "pending": 1},
                        "oldest_pending_age_seconds": 3.2,
                        "latest_processed_lag_seconds": 0.4,
                        "dead_letter_count": 0,
                        "initialized": True,
                    }
                ),
            ),
        ):
            status = await graph_runtime_status(db, user_id=7)

        self.assertFalse(status["projection"]["caught_up"])
        self.assertEqual(status["projection"]["blocking_counts"]["pending"], 1)
        self.assertFalse(status["primary_ready"])
        self.assertTrue(status["serving_ready"])

    async def test_neo4j_connectivity_failure_can_still_serve_via_fallback(self) -> None:
        from app.services.graph_runtime_status_service import graph_runtime_status

        db = Mock()
        with (
            patch("app.services.graph_runtime_status_service.settings.GRAPH_BACKEND", "neo4j"),
            patch(
                "app.services.graph_runtime_status_service.create_graph_store",
                return_value=_Store(
                    {
                        "ok": False,
                        "serving_ok": True,
                        "backend": "neo4j",
                        "fallback_available": True,
                    }
                ),
            ),
            patch(
                "app.services.graph_runtime_status_service.neo4j_projection_lag_summary",
                new=AsyncMock(
                    return_value={
                        "backend": "neo4j",
                        "tasks_total": 0,
                        "status_counts": {},
                        "oldest_pending_age_seconds": 0.0,
                        "latest_processed_lag_seconds": 0.0,
                        "dead_letter_count": 0,
                    }
                ),
            ),
        ):
            status = await graph_runtime_status(db, user_id=7)

        self.assertFalse(status["primary_ready"])
        self.assertTrue(status["serving_ready"])

    async def test_misconfigured_backend_fails_closed_without_error_body(self) -> None:
        from app.services.graph_runtime_status_service import graph_runtime_status

        db = Mock()
        with (
            patch("app.services.graph_runtime_status_service.settings.GRAPH_BACKEND", "neo4j"),
            patch(
                "app.services.graph_runtime_status_service.create_graph_store",
                side_effect=RuntimeError("secret-password-and-query"),
            ),
        ):
            status = await graph_runtime_status(db, user_id=7)

        self.assertFalse(status["primary_ready"])
        self.assertFalse(status["serving_ready"])
        self.assertEqual(status["health"]["error_type"], "RuntimeError")
        self.assertNotIn("error", status["health"])


if __name__ == "__main__":
    unittest.main()
