import unittest
import hashlib
from sqlalchemy.ext.asyncio import create_async_engine, async_sessionmaker
from app.database import Base
from app.models.user import User
from app.models.material import Material
from app.models.retrieval import RetrievalProjection, RetrievalProjectionChunk

from app.services.material_retrieval_backend import (
    ChromaMaterialRetrievalBackend,
    HybridMaterialRetrievalBackend,
    MaterialChunkHit,
    MaterialIndexRebuilder,
    MaterialSearchScope,
    _tokenize,
)


class _RowsResult:
    def __init__(self, rows):
        self._rows = rows

    def all(self):
        return self._rows

    def scalars(self):
        return self


class _SequenceDb:
    def __init__(self, results):
        self.results = list(results)
        self.calls = 0

    async def execute(self, _query):
        result = self.results[self.calls]
        self.calls += 1
        return result


class _FakeEmbedding:
    def get_text_embedding(self, _query):
        return [0.1, 0.2]


class _FakeCollection:
    def __init__(self):
        self.query_kwargs = None
        self.deleted_where = None

    def query(self, **kwargs):
        self.query_kwargs = kwargs
        return {
            "documents": [["RRF combines ranked lists"]],
            "metadatas": [[{
                "material_id": "7",
                "title": "RAG notes",
                "file_type": "md",
                "chunk_index": 3,
                "project_id": "11",
                "user_id": "42",
            }]],
            "distances": [[0.2]],
        }

    def delete(self, *, where):
        self.deleted_where = where


class _FakeRag:
    def __init__(self):
        self._embed_model = _FakeEmbedding()
        self._collection = _FakeCollection()
        self._similarity_threshold = 0.0
        self.vector_incompatible = False
        self.indexed = []
        self.removed = []

    async def initialize(self):
        return None

    async def get_status(self, _user_id):
        return {"embedding_enabled": True}

    async def index_material(self, **kwargs):
        self.indexed.append(kwargs)
        return 2

    async def remove_material(self, material_id, user_id=None):
        self.removed.append((material_id, user_id))

    def _looks_like_dimension_mismatch(self, _exc):
        return False


class _FakeBackend:
    def __init__(self, hits):
        self.hits = hits

    async def search(self, _query, *, scope, top_k=8):
        del scope
        return self.hits[:top_k]


class _FailingBackend:
    async def search(self, _query, *, scope, top_k=8):
        del scope, top_k
        raise RuntimeError("backend unavailable")


class MaterialRetrievalBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_chroma_hit_exposes_chunk_source_and_scope(self):
        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(engine.dispose)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        rag = _FakeRag()
        text = "RRF combines ranked lists"
        digest = hashlib.sha256(text.encode()).hexdigest()
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            db.add(User(id=42, username="owner", email="owner@test.invalid", hashed_password="hash"))
            db.add(Material(id=7, user_id=42, title="RAG notes", content=text, file_type="md"))
            projection = RetrievalProjection(user_id=42, source_id=7, status="ready",
                indexed_version=1, content_hash=digest)
            db.add(projection)
            await db.flush()
            db.add(RetrievalProjectionChunk(projection_id=projection.id, user_id=42, source_id=7,
                chunk_index=3, chunk_hash=digest, text=text))
            await db.commit()
            backend = ChromaMaterialRetrievalBackend(db, rag=rag)
            scope = MaterialSearchScope(user_id=42, material_id_min=5, material_id_max=9)
            hits = await backend.search("RRF", scope=scope, top_k=4)
            # Old vectors must disappear immediately, even before the new index runs.
            material = await db.get(Material, 7)
            material.content = "changed canonical text"
            await db.commit()
            self.assertEqual(await backend.search("RRF", scope=scope, top_k=4), [])
            material.content = text
            projection.status = "pending"
            await db.commit()
            self.assertEqual(await backend.search("RRF", scope=scope, top_k=4), [])

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].material_id, 7)
        self.assertEqual(hits[0].chunk_index, 3)
        self.assertEqual(hits[0].source, "material:7#chunk:3")
        self.assertEqual(hits[0].chunk_key, "material:7:chunk:3")
        self.assertEqual(hits[0].project_id, 11)
        self.assertEqual(hits[0].backend, "chroma")
        self.assertEqual(rag._collection.query_kwargs["n_results"], 16)
        where_filter = rag._collection.query_kwargs["where"]
        self.assertEqual(
            where_filter,
            {"$and": [{"user_id": "42"}, {"material_id": "7"}]},
        )

    async def test_dimension_mismatch_pauses_search_without_wiping_the_collection(self):
        from app.ai.rag_service import RAGService

        class _MismatchCollection(_FakeCollection):
            def query(self, **kwargs):
                raise ValueError("Embedding dimension 2 does not match collection dimensionality 3")

        engine = create_async_engine("sqlite+aiosqlite:///:memory:")
        self.addAsyncCleanup(engine.dispose)
        async with engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        rag = RAGService()
        rag._initialized = True
        rag._embed_model = _FakeEmbedding()
        rag._collection = _MismatchCollection()
        rag._similarity_threshold = 0.0
        handler_calls = []
        rag.set_incompatibility_handler(lambda: handler_calls.append(True))
        async with async_sessionmaker(engine, expire_on_commit=False)() as db:
            db.add(User(id=5, username="u5", email="u5@test.invalid", hashed_password="hash"))
            db.add(Material(id=9, user_id=5, title="T", content="text", file_type="md"))
            await db.commit()
            backend = ChromaMaterialRetrievalBackend(db, rag=rag)
            scope = MaterialSearchScope(user_id=5)
            first = await backend.search("text", scope=scope, top_k=2)
            second = await backend.search("text", scope=scope, top_k=2)

        self.assertEqual((first, second), ([], []))
        self.assertIsNone(rag._collection.deleted_where)
        self.assertTrue(rag.vector_incompatible)
        # One lifecycle reset is requested, not one per query or per user.
        self.assertEqual(handler_calls, [True])

    async def test_hybrid_rrf_merges_same_chunk_and_keeps_provenance(self):
        semantic_hit = MaterialChunkHit(
            text="same chunk",
            score=0.91,
            material_id=3,
            material_title="doc",
            chunk_index=1,
            source="material:3#chunk:1",
            backend="chroma",
            backend_scores={"chroma": 0.91},
        )
        keyword_hit = MaterialChunkHit(
            text="same chunk",
            score=2.3,
            material_id=3,
            material_title="doc",
            chunk_index=1,
            source="material:3#chunk:1",
            backend="keyword",
            backend_scores={"keyword": 2.3},
        )
        hybrid = HybridMaterialRetrievalBackend(
            _FakeBackend([semantic_hit]),
            _FakeBackend([keyword_hit]),
        )

        hits = await hybrid.search(
            "same",
            scope=MaterialSearchScope(user_id=1),
            top_k=5,
        )

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].backend, "hybrid")
        self.assertEqual(hits[0].backend_ranks, {"chroma": 1, "keyword": 1})
        self.assertEqual(hits[0].backend_scores, {"chroma": 0.91, "keyword": 2.3})
        self.assertAlmostEqual(hits[0].score, 2 / 61)

    async def test_hybrid_keeps_keyword_results_when_semantic_backend_fails(self):
        keyword_hit = MaterialChunkHit(
            text="fallback chunk",
            score=1.8,
            material_id=4,
            material_title="doc",
            chunk_index=0,
            source="material:4#chunk:0",
            backend="keyword",
            backend_scores={"keyword": 1.8},
        )
        hybrid = HybridMaterialRetrievalBackend(
            _FailingBackend(),
            _FakeBackend([keyword_hit]),
        )

        hits = await hybrid.search(
            "fallback",
            scope=MaterialSearchScope(user_id=1),
            top_k=3,
        )

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].backend, "hybrid")
        self.assertEqual(hits[0].backend_ranks, {"keyword": 1})
        self.assertAlmostEqual(hits[0].score, 1 / 61)

    def test_tokenizer_keeps_latin_words_and_adds_chinese_bigrams(self):
        tokens = _tokenize("RRF 混合检索效果")
        self.assertIn("rrf", tokens)
        self.assertIn("混合", tokens)
        self.assertIn("检索", tokens)


class MaterialIndexRebuilderTests(unittest.IsolatedAsyncioTestCase):
    async def test_full_user_rebuild_only_deletes_current_user_chunks(self):
        rag = _FakeRag()
        db = _SequenceDb([_RowsResult([])])
        rebuilder = MaterialIndexRebuilder(db, rag=rag)

        result = await rebuilder.rebuild_user(42)

        self.assertTrue(result["ok"])
        self.assertEqual(result["materials_total"], 0)
        self.assertEqual(rag._collection.deleted_where, {"user_id": "42"})

    async def test_empty_explicit_rebuild_is_noop(self):
        rag = _FakeRag()
        db = _SequenceDb([])
        rebuilder = MaterialIndexRebuilder(db, rag=rag)

        result = await rebuilder.rebuild_user(42, material_ids=[])

        self.assertTrue(result["ok"])
        self.assertEqual(result["materials_total"], 0)
        self.assertIsNone(rag._collection.deleted_where)
        self.assertEqual(rag.removed, [])


if __name__ == "__main__":
    unittest.main()
