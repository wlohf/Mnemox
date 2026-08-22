from pathlib import Path

root = Path(__file__).resolve().parents[1]
router_path = root / "backend/app/services/retrieval_router.py"
test_path = root / "backend/tests/test_retrieval_router.py"

router = router_path.read_text(encoding="utf-8")
old = '''        chunks = await self.material_backend.search(query, scope=scope, top_k=limit)\n        return [\n            RetrievalHit(\n                source_type="material",\n                source_id=int(chunk.material_id),\n                title=chunk.material_title,\n                excerpt=chunk.text,\n                score=float(chunk.score),\n                metadata={\n                    "material_id": int(chunk.material_id),\n                    "chunk_index": int(chunk.chunk_index),\n                    "source": chunk.source,\n                    "backend": chunk.backend,\n                    "backend_scores": dict(chunk.backend_scores),\n                    "backend_ranks": dict(chunk.backend_ranks),\n                    "file_type": chunk.file_type,\n                    "project_id": chunk.project_id,\n                },\n            )\n            for chunk in chunks\n        ]\n'''
new = '''        chunks = await self.material_backend.search(query, scope=scope, top_k=limit)\n        if not chunks:\n            return []\n\n        raw_scores = [max(0.0, float(chunk.score)) for chunk in chunks]\n        max_raw_score = max(raw_scores) or 1.0\n        hits: list[RetrievalHit] = []\n        for chunk, raw_score in zip(chunks, raw_scores):\n            hits.append(\n                RetrievalHit(\n                    source_type="material",\n                    source_id=int(chunk.material_id),\n                    title=chunk.material_title,\n                    excerpt=chunk.text,\n                    score=raw_score / max_raw_score,\n                    metadata={\n                        "material_id": int(chunk.material_id),\n                        "chunk_index": int(chunk.chunk_index),\n                        "source": chunk.source,\n                        "backend": chunk.backend,\n                        "backend_scores": dict(chunk.backend_scores),\n                        "backend_ranks": dict(chunk.backend_ranks),\n                        "raw_backend_score": raw_score,\n                        "score_normalization": "per_query_max",\n                        "file_type": chunk.file_type,\n                        "project_id": chunk.project_id,\n                    },\n                )\n            )\n        return hits\n'''
if router.count(old) != 1:
    raise RuntimeError(f"router target count={router.count(old)}")
router_path.write_text(router.replace(old, new, 1), encoding="utf-8")

tests = test_path.read_text(encoding="utf-8")
old_test = '''        self.assertEqual(hits[0].metadata["source"], "material:7#chunk:3")\n        self.assertEqual(hits[0].to_material_chunk()["backend"], "hybrid")\n'''
new_test = '''        self.assertEqual(hits[0].metadata["source"], "material:7#chunk:3")\n        self.assertEqual(hits[0].score, 1.0)\n        self.assertEqual(hits[0].metadata["raw_backend_score"], 0.8)\n        self.assertEqual(hits[0].metadata["score_normalization"], "per_query_max")\n        self.assertEqual(hits[0].to_material_chunk()["backend"], "hybrid")\n'''
if tests.count(old_test) != 1:
    raise RuntimeError(f"test target count={tests.count(old_test)}")
test_path.write_text(tests.replace(old_test, new_test, 1), encoding="utf-8")
