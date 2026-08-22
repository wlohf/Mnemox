import unittest
from unittest.mock import AsyncMock

from app.services.context_store import L0, L1, ContextItem
from app.services.material_retrieval_backend import MaterialChunkHit
from app.services.retrieval_router import RetrievalHit, RetrievalRouter


class _FakeMaterialBackend:
    def __init__(self, hits=None, error=None):
        self.hits = list(hits or [])
        self.error = error
        self.calls = []

    async def search(self, query, *, scope, top_k=8):
        self.calls.append((query, scope, top_k))
        if self.error:
            raise self.error
        return self.hits[:top_k]


class _FakeContextStore:
    def __init__(self, items=None):
        self.items = list(items or [])
        self.calls = []

    async def retrieve(self, *args, **kwargs):
        self.calls.append((args, kwargs))
        return self.items

    async def load_tiered(self, *args, **kwargs):
        return ""


class _FakeDb:
    async def execute(self, _stmt):
        raise AssertionError("Unexpected database access")


class RetrievalRouterTests(unittest.IsolatedAsyncioTestCase):
    async def test_material_scope_and_chunk_provenance_are_preserved(self):
        backend = _FakeMaterialBackend([
            MaterialChunkHit(
                text="relevant chunk",
                score=0.8,
                material_id=7,
                material_title="RAG",
                chunk_index=3,
                source="material:7#chunk:3",
                backend="hybrid",
                backend_scores={"chroma": 0.9, "keyword": 2.0},
                backend_ranks={"chroma": 1, "keyword": 2},
            )
        ])
        router = RetrievalRouter(
            _FakeDb(), material_backend=backend, context_store=_FakeContextStore()
        )

        hits = await router.search(
            "RRF",
            user_id=42,
            source_types=("material",),
            material_ids=[7, 8],
            material_id_min=5,
            material_id_max=9,
            project_id=11,
            top_k=4,
        )

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].key, "material:7:chunk:3")
        self.assertEqual(hits[0].metadata["source"], "material:7#chunk:3")
        self.assertEqual(hits[0].score, 1.0)
        self.assertEqual(hits[0].metadata["raw_backend_score"], 0.8)
        self.assertEqual(hits[0].metadata["score_normalization"], "per_query_max")
        self.assertEqual(hits[0].to_material_chunk()["backend"], "hybrid")
        _, scope, requested_k = backend.calls[0]
        self.assertEqual(scope.user_id, 42)
        self.assertEqual(list(scope.material_ids), [7, 8])
        self.assertEqual(scope.material_id_min, 5)
        self.assertEqual(scope.material_id_max, 9)
        self.assertEqual(scope.project_id, 11)
        self.assertEqual(requested_k, 4)

    async def test_cross_source_rrf_treats_material_as_one_source(self):
        router = RetrievalRouter(
            _FakeDb(), material_backend=_FakeMaterialBackend(), context_store=_FakeContextStore()
        )
        material = RetrievalHit(
            source_type="material",
            source_id=1,
            title="doc",
            excerpt="chunk",
            score=0.03,
            metadata={
                "material_id": 1,
                "chunk_index": 0,
                "backend_scores": {"chroma": 0.9, "keyword": 2.1},
            },
        )
        note = RetrievalHit("note", 2, "note", "text", 4.0)
        memory = RetrievalHit("memory", 3, "memory", "text", 3.0)
        router._search_materials = AsyncMock(return_value=[material])
        router._search_context_store = AsyncMock(return_value=[note])
        router._search_memories = AsyncMock(return_value=[memory])

        response = await router.search_with_diagnostics(
            "query",
            user_id=1,
            source_types=("material", "note", "memory"),
            top_k=5,
        )

        self.assertEqual(response.diagnostics.fusion, "rrf")
        self.assertEqual(len(response.hits), 3)
        material_hit = next(hit for hit in response.hits if hit.source_type == "material")
        self.assertEqual(material_hit.metadata["source_ranks"], {"material": 1})
        self.assertEqual(material_hit.metadata["backend_scores"], {"chroma": 0.9, "keyword": 2.1})

    async def test_one_source_failure_degrades_locally(self):
        router = RetrievalRouter(
            _FakeDb(), material_backend=_FakeMaterialBackend(), context_store=_FakeContextStore()
        )
        router._search_materials = AsyncMock(side_effect=RuntimeError("chroma unavailable"))
        router._search_context_store = AsyncMock(
            return_value=[RetrievalHit("note", 1, "title", "body", 1.0)]
        )

        response = await router.search_with_diagnostics(
            "query", user_id=1, source_types=("material", "note"), top_k=3
        )

        self.assertEqual([hit.source_type for hit in response.hits], ["note"])
        self.assertEqual(response.diagnostics.degraded_sources, {"material": "RuntimeError"})
        self.assertEqual(response.diagnostics.fusion, "direct")

    async def test_empty_material_query_returns_recent_context_store_materials(self):
        store = _FakeContextStore(
            [
                ContextItem(
                    source_type="material",
                    source_id=12,
                    title="Recent material",
                    excerpt="recent preview",
                    score=0.1,
                )
            ]
        )
        backend = _FakeMaterialBackend(error=AssertionError("semantic backend should not run"))
        router = RetrievalRouter(_FakeDb(), material_backend=backend, context_store=store)

        hits = await router.search(
            "", user_id=9, source_types=("material",), top_k=3
        )

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].source_id, 12)
        self.assertEqual(hits[0].metadata["backend"], "context_store")
        self.assertEqual(hits[0].metadata["source"], "material:12")
        self.assertEqual(backend.calls, [])
        self.assertEqual(store.calls[0][1]["source_types"], ("material",))

    async def test_l0_loading_uses_title_without_database_access(self):
        router = RetrievalRouter(
            _FakeDb(), material_backend=_FakeMaterialBackend(), context_store=_FakeContextStore()
        )
        router._search_context_store = AsyncMock(
            return_value=[RetrievalHit("note", 1, "Title", "Excerpt", 1.0, level=L1)]
        )

        hits = await router.search(
            "query", user_id=1, source_types=("note",), top_k=1, load_level=L0
        )

        self.assertEqual(hits[0].excerpt, "Title")
        self.assertEqual(hits[0].level, L0)


if __name__ == "__main__":
    unittest.main()
