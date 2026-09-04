"""HTTP-boundary tests for the Stage 7 Graphiti Temporal Slice."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException

from app.config import settings
from app.routers.memory import (
    TemporalGraphQueryRequest,
    _require_graphiti_temporal,
    get_temporal_graph_status,
    query_temporal_graph,
    rebuild_temporal_graph,
)
from app.services.graphiti_temporal_service import GraphitiTemporalUnavailable


class GraphitiTemporalApiTests(unittest.IsolatedAsyncioTestCase):
    def test_feature_flag_is_default_off_boundary(self):
        with patch.object(settings, "GRAPHITI_ENABLED", False):
            with self.assertRaises(HTTPException) as ctx:
                _require_graphiti_temporal()
        self.assertEqual(ctx.exception.status_code, 409)

        with patch.object(settings, "GRAPHITI_ENABLED", True):
            _require_graphiti_temporal()

    async def test_query_maps_graphiti_failure_to_fixed_safe_503(self):
        fake = SimpleNamespace(
            query=AsyncMock(
                side_effect=GraphitiTemporalUnavailable(
                    "PRIVATE NEO4J PASSWORD AND CYPHER MUST NOT LEAK"
                )
            ),
            close=AsyncMock(),
        )
        user = SimpleNamespace(id=7)
        body = TemporalGraphQueryRequest(query="learning focus")
        with (
            patch.object(settings, "GRAPHITI_ENABLED", True),
            patch("app.routers.memory.GraphitiTemporalService", return_value=fake),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await query_temporal_graph(body=body, db=object(), current_user=user)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, "Graphiti Temporal Slice 当前不可用")
        self.assertNotIn("PRIVATE", str(ctx.exception.detail))
        fake.close.assert_awaited_once()

    async def test_rebuild_and_status_are_authenticated_user_scoped(self):
        fake = SimpleNamespace(
            rebuild_user=AsyncMock(return_value={"rebuilt": True, "user_id": 9}),
            status=AsyncMock(
                return_value={
                    "ok": True,
                    "backend": "graphiti",
                    "caught_up": True,
                    "reviewed_declarations": 3,
                    "projected_edges": 3,
                }
            ),
            close=AsyncMock(),
        )
        user = SimpleNamespace(id=9)
        with (
            patch.object(settings, "GRAPHITI_ENABLED", True),
            patch("app.routers.memory.GraphitiTemporalService", return_value=fake),
        ):
            rebuilt = await rebuild_temporal_graph(db=object(), current_user=user)
            status = await get_temporal_graph_status(db=object(), current_user=user)
        self.assertTrue(rebuilt["rebuilt"])
        self.assertTrue(status["caught_up"])
        fake.rebuild_user.assert_awaited_once_with(user_id=9)
        fake.status.assert_awaited_once_with(user_id=9)
        self.assertEqual(fake.close.await_count, 2)

    async def test_status_unhealthy_maps_to_fixed_503(self):
        fake = SimpleNamespace(
            status=AsyncMock(
                return_value={
                    "ok": False,
                    "backend": "graphiti",
                    "error_type": "RuntimeError",
                }
            ),
            close=AsyncMock(),
        )
        user = SimpleNamespace(id=11)
        with (
            patch.object(settings, "GRAPHITI_ENABLED", True),
            patch("app.routers.memory.GraphitiTemporalService", return_value=fake),
        ):
            with self.assertRaises(HTTPException) as ctx:
                await get_temporal_graph_status(db=object(), current_user=user)
        self.assertEqual(ctx.exception.status_code, 503)
        self.assertEqual(ctx.exception.detail, "Graphiti Temporal Slice 当前不可用")
        fake.close.assert_awaited_once()


if __name__ == "__main__":
    unittest.main()
