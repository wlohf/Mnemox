import unittest

from app.ai.rag_service import RAGService


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


if __name__ == "__main__":
    unittest.main()
