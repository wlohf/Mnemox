"""HTTP-boundary contract tests for Stage 7 Knowledge Path."""
from __future__ import annotations

import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError

from app.config import settings
from app.routers.knowledge import (
    KnowledgePathRequest,
    _require_knowledge_path,
    knowledge_learning_path,
)
from app.services.knowledge_path_service import KnowledgePathUnavailable


class KnowledgePathApiTests(unittest.IsolatedAsyncioTestCase):
    def test_feature_flag_requires_knowledge_v2_and_path_switch(self) -> None:
        with (
            patch.object(settings, "KNOWLEDGE_V2_ENABLED", True),
            patch.object(settings, "KNOWLEDGE_PATH_ENABLED", False),
        ):
            with self.assertRaises(HTTPException) as context:
                _require_knowledge_path()
        self.assertEqual(context.exception.status_code, 409)

        with (
            patch.object(settings, "KNOWLEDGE_V2_ENABLED", True),
            patch.object(settings, "KNOWLEDGE_PATH_ENABLED", True),
        ):
            _require_knowledge_path()

    def test_request_schema_rejects_unknown_relation_type(self) -> None:
        with self.assertRaises(ValidationError):
            KnowledgePathRequest(
                start_concept_ids=[1],
                target_concept_id=2,
                relation_types=["text2cypher"],
            )

    async def test_capability_failure_maps_to_fixed_503_without_internal_reason(self) -> None:
        body = KnowledgePathRequest(
            start_concept_ids=[1],
            target_concept_id=2,
        )
        with (
            patch.object(settings, "KNOWLEDGE_V2_ENABLED", True),
            patch.object(settings, "KNOWLEDGE_PATH_ENABLED", True),
            patch(
                "app.routers.knowledge.build_learning_paths",
                new=AsyncMock(
                    side_effect=KnowledgePathUnavailable(
                        "bolt://neo4j-user:secret@example.invalid MATCH private-query"
                    )
                ),
            ),
        ):
            with self.assertRaises(HTTPException) as context:
                await knowledge_learning_path(
                    body,
                    db=object(),  # type: ignore[arg-type]
                    current_user=SimpleNamespace(id=7),  # type: ignore[arg-type]
                )
        self.assertEqual(context.exception.status_code, 503)
        self.assertNotIn("secret", str(context.exception.detail))
        self.assertNotIn("MATCH", str(context.exception.detail))

    async def test_owned_concept_lookup_failure_maps_to_404(self) -> None:
        body = KnowledgePathRequest(start_concept_ids=[1], target_concept_id=2)
        with (
            patch.object(settings, "KNOWLEDGE_V2_ENABLED", True),
            patch.object(settings, "KNOWLEDGE_PATH_ENABLED", True),
            patch(
                "app.routers.knowledge.build_learning_paths",
                new=AsyncMock(side_effect=LookupError("foreign concept 999")),
            ),
        ):
            with self.assertRaises(HTTPException) as context:
                await knowledge_learning_path(
                    body,
                    db=object(),  # type: ignore[arg-type]
                    current_user=SimpleNamespace(id=7),  # type: ignore[arg-type]
                )
        self.assertEqual(context.exception.status_code, 404)
        self.assertNotIn("999", str(context.exception.detail))


if __name__ == "__main__":
    unittest.main()
