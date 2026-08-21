import unittest

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


class _FakeBackend:
    def __init__(self, hits):
        self.hits = hits

    async def search(self, _query, *, scope, top_k=8):
        del scope
        return self.hits[:top_k]


class MaterialRetrievalBackendTests(unittest.IsolatedAsyncioTestCase):
    async def test_chroma_hit_exposes_chunk_source_and_scope(self):
        db = _SequenceDb([_RowsResult([(7,)])])
        rag = _FakeRag()
        backend = ChromaMaterialRetrievalBackend(db, rag=rag)

        hits = await backend.search(
            "RRF",
            scope=MaterialSearchScope(user_id=42, material_id_min=5, material_id_max=9),
            top_k=4,
        )

        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0].material_id, 7)
        self.assertEqual(hits[0].chunk_index, 3)
        self.assertEqual(hits[0].source, "material:7#chunk:3")
        self.assertEqual(hits[0].project_id, 11)
        self.assertEqual(hits[0].backend, "chroma")
        where_filter = rag._collection.query_kwargs["where"]
        self.assertEqual(
            where_filter,
            {"$and": [{"user_id": "42"}, {"material_id": "7"}]},
        )

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
