"""Offline quality corpus integrity and ranking metric correctness."""
from __future__ import annotations

import json
import math
import unittest
from pathlib import Path

from evaluate_retrieval import DeterministicEmbedding, _metrics, _percentile, run_evaluation


class RetrievalQualityMetricTests(unittest.TestCase):
    def test_metrics_reward_graded_relevance_and_first_relevant_rank(self) -> None:
        result = _metrics(
            ["material:9", "material:1", "material:2"],
            {"material:1": 3, "material:2": 1},
        )
        self.assertEqual(result["recall_at_5"], 1.0)
        self.assertEqual(result["recall_at_10"], 1.0)
        self.assertEqual(result["mrr"], 0.5)
        self.assertGreater(result["ndcg_at_10"], 0.0)
        self.assertLess(result["ndcg_at_10"], 1.0)

    def test_duplicate_hits_do_not_inflate_recall(self) -> None:
        result = _metrics(
            ["material:1", "material:1", "material:1"],
            {"material:1": 2, "material:2": 1},
        )
        self.assertEqual(result["recall_at_5"], 0.5)

    def test_percentile_uses_nearest_rank(self) -> None:
        self.assertEqual(_percentile([1, 2, 3, 4, 100], 0.95), 100)

    def test_embedding_is_deterministic_normalized_and_local(self) -> None:
        embedder = DeterministicEmbedding()
        first = embedder.get_text_embedding("RRF reranker 混合检索")
        second = embedder.get_text_embedding("RRF reranker 混合检索")
        self.assertEqual(first, second)
        self.assertAlmostEqual(math.sqrt(sum(value * value for value in first)), 1.0)

    def test_fixture_covers_tenant_isolation_empty_queries_and_cross_source_fusion(self) -> None:
        fixture_path = Path(__file__).parent / "fixtures" / "retrieval_eval_cases.json"
        fixture = json.loads(fixture_path.read_text(encoding="utf-8"))
        self.assertGreaterEqual(len(fixture["cases"]), 15)
        self.assertTrue(any(not case["query"] for case in fixture["cases"]))
        self.assertTrue(any(len(case["source_types"]) > 1 for case in fixture["cases"]))
        self.assertTrue(all("forbidden_user_ids" in case for case in fixture["cases"]))
        self.assertEqual({item["user_id"] for item in fixture["materials"]}, {1, 2})


class RetrievalQualityBaselineTests(unittest.IsolatedAsyncioTestCase):
    async def test_hybrid_baseline_passes_quality_and_lifecycle_gates(self) -> None:
        report = await run_evaluation("hybrid")
        result = report["results"][0]
        self.assertGreaterEqual(result["recall_at_5"], 0.75)
        self.assertGreaterEqual(result["mrr"], 0.75)
        self.assertGreaterEqual(result["material_hit_rate_at_5"], 0.9)
        self.assertEqual(result["forbidden_hits"], 0)
        self.assertTrue(result["empty_query_compatible"])
        self.assertEqual(report["lifecycle_probes"]["deleted_material_residual_hits"], 0)

    async def test_missing_embeddings_preserve_sparse_quality(self) -> None:
        report = await run_evaluation("hybrid_no_embedding")
        result = report["results"][0]
        self.assertGreaterEqual(result["recall_at_5"], 0.75)
        self.assertEqual(result["forbidden_hits"], 0)


if __name__ == "__main__":
    unittest.main()
