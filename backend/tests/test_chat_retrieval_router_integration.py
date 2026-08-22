import unittest
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

from app.routers import chat
from app.services.retrieval_router import RetrievalHit


class ChatMaterialRouterIntegrationTests(unittest.IsolatedAsyncioTestCase):
    async def test_large_material_prompt_uses_retrieval_router(self):
        material = {"id": 9, "title": "Large doc", "content": "x" * 200}
        hit = RetrievalHit(
            source_type="material",
            source_id=9,
            title="Large doc",
            excerpt="retrieved chunk",
            score=0.91,
            metadata={
                "material_id": 9,
                "chunk_index": 2,
                "source": "material:9#chunk:2",
                "backend": "hybrid",
            },
        )
        router = SimpleNamespace(search=AsyncMock(return_value=[hit]))

        with patch.object(chat, "_load_materials", AsyncMock(return_value=[material])), patch.object(
            chat, "RetrievalRouter", return_value=router
        ), patch.object(chat.settings, "SMALL_MATERIAL_THRESHOLD", 50), patch.object(
            chat.settings, "RAG_ENABLED", True
        ):
            prompt = await chat._build_system_prompt_with_rag("question", [9], object(), 7)

        self.assertIn("retrieved chunk", prompt)
        router.search.assert_awaited_once()
        kwargs = router.search.await_args.kwargs
        self.assertEqual(kwargs["user_id"], 7)
        self.assertEqual(kwargs["source_types"], ("material",))
        self.assertEqual(kwargs["material_ids"], [9])


if __name__ == "__main__":
    unittest.main()
