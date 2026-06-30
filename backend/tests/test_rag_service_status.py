import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

import httpx

from app.ai.rag_service import OpenAICompatibleEmbedding, RAGService, load_rag_settings, save_rag_settings


class RAGServiceStatusTests(unittest.IsolatedAsyncioTestCase):
    async def test_retrieval_status_is_user_scoped(self):
        rag = RAGService()
        await rag.retrieve("hello", user_id=1)

        user_one = await rag.get_status(user_id=1)
        user_two = await rag.get_status(user_id=2)
        global_status = await rag.get_status()

        self.assertEqual(user_one["last_retrieval_status"]["mode"], "fallback")
        self.assertEqual(user_two["last_retrieval_status"]["mode"], "not_run")
        self.assertEqual(global_status["last_retrieval_status"]["mode"], "fallback")
        self.assertTrue(user_one["fallback_active"])

    async def test_uninitialized_status_explains_fallback(self):
        rag = RAGService()
        status = await rag.get_status(user_id=99)

        self.assertFalse(status["initialized"])
        self.assertFalse(status["embedding_enabled"])
        self.assertIn("fallback", status["message"])

    async def test_dimension_mismatch_resets_index_and_reports_reindex_needed(self):
        class FakeEmbedding:
            def get_text_embedding(self, _text):
                return [0.1, 0.2]

        class DimensionMismatchCollection:
            def query(self, **_kwargs):
                raise ValueError("Embedding dimension 2 does not match collection dimensionality 3")

        class EmptyCollection:
            def count(self):
                return 0

        class FakeChromaClient:
            def __init__(self):
                self.deleted = False
                self.collection = EmptyCollection()

            def delete_collection(self, name):
                self.deleted = name == "study_materials"

            def get_or_create_collection(self, **_kwargs):
                return self.collection

        rag = RAGService()
        chroma = FakeChromaClient()
        rag._initialized = True
        rag._embed_model = FakeEmbedding()
        rag._collection = DimensionMismatchCollection()
        rag._chroma_client = chroma

        items = await rag.retrieve("hello", user_id=7)
        status = await rag.get_status(user_id=7)

        self.assertEqual(items, [])
        self.assertTrue(chroma.deleted)
        self.assertTrue(status["fallback_active"])
        self.assertIn("重新索引", status["last_retrieval_status"]["message"])


class RAGSettingsPersistenceTests(unittest.TestCase):
    def test_rag_api_key_is_encrypted_at_rest_and_decrypted_on_load(self):
        with tempfile.TemporaryDirectory() as tmpdir:
            path = Path(tmpdir) / "rag_settings.json"
            with patch("app.ai.rag_service._get_rag_settings_path", return_value=path):
                save_rag_settings({
                    "api_key": "sk-rag-secret",
                    "base_url": "https://example.test/v1",
                    "model": "bge-m3",
                })

                raw = json.loads(path.read_text(encoding="utf-8"))
                self.assertNotEqual(raw["api_key"], "sk-rag-secret")
                self.assertTrue(raw["api_key"].startswith("enc:v1:"))

                loaded = load_rag_settings()
                self.assertEqual(loaded["api_key"], "sk-rag-secret")
                self.assertEqual(loaded["model"], "bge-m3")


class OpenAICompatibleEmbeddingTests(unittest.TestCase):
    def test_extracts_embeddings_from_standard_openai_payload(self):
        client = OpenAICompatibleEmbedding(
            api_key="test-key",
            base_url="https://example.test/v1",
            model="text-embedding-3-small",
        )

        with patch("httpx.Client.post") as post:
            post.return_value = httpx.Response(
                200,
                json={
                    "object": "list",
                    "data": [{"object": "embedding", "embedding": [0.1, 0.2, 0.3], "index": 0}],
                    "model": "text-embedding-3-small",
                },
                request=httpx.Request("POST", "https://example.test/v1/embeddings"),
            )

            embedding = client.get_text_embedding("hello")

        self.assertEqual(embedding, [0.1, 0.2, 0.3])
        self.assertEqual(post.call_args.kwargs["json"]["input"], ["hello"])

    def test_extracts_embeddings_when_relay_stringifies_json_fields(self):
        client = OpenAICompatibleEmbedding(
            api_key="test-key",
            base_url="https://relay.test/v1",
            model="text-embedding-3-small",
        )

        with patch("httpx.Client.post") as post:
            post.return_value = httpx.Response(
                200,
                json={
                    "data": '[{"embedding": "[0.4, 0.5]", "index": 0}, {"embedding": [0.6, 0.7], "index": 1}]',
                },
                request=httpx.Request("POST", "https://relay.test/v1/embeddings"),
            )

            embeddings = client.get_text_embedding_batch(["hello", "world"])

        self.assertEqual(embeddings, [[0.4, 0.5], [0.6, 0.7]])

    def test_reports_invalid_embedding_shape_as_user_readable_error(self):
        client = OpenAICompatibleEmbedding(
            api_key="test-key",
            base_url="https://example.test/v1",
            model="text-embedding-3-small",
        )

        with patch("httpx.Client.post") as post:
            post.return_value = httpx.Response(
                200,
                json={"data": "not-json"},
                request=httpx.Request("POST", "https://example.test/v1/embeddings"),
            )

            with self.assertRaisesRegex(ValueError, "Embedding 服务返回的数据格式不对"):
                client.get_text_embedding("hello")


if __name__ == "__main__":
    unittest.main()
