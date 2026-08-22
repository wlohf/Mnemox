from pathlib import Path

root = Path(__file__).resolve().parents[1]
router_path = root / "backend/app/services/retrieval_router.py"
test_path = root / "backend/tests/test_retrieval_router.py"

router = router_path.read_text(encoding="utf-8")
old_guard = '''        if not str(query or "").strip() or not requested:\n            diagnostics = RetrievalDiagnostics(requested, (), {}, {}, "none")\n            return RetrievalResponse([], diagnostics)\n'''
new_guard = '''        if not requested:\n            diagnostics = RetrievalDiagnostics(requested, (), {}, {}, "none")\n            return RetrievalResponse([], diagnostics)\n'''
if router.count(old_guard) != 1:
    raise RuntimeError(f"guard target count={router.count(old_guard)}")
router = router.replace(old_guard, new_guard, 1)

old_scope = '''        scope = MaterialSearchScope(\n            user_id=user_id,\n            material_ids=material_ids,\n            material_id_min=material_id_min,\n            material_id_max=material_id_max,\n            project_id=project_id,\n        )\n        chunks = await self.material_backend.search(query, scope=scope, top_k=limit)\n'''
new_scope = '''        if not str(query or "").strip():\n            items = await self.context_store.retrieve(\n                self.db,\n                user_id,\n                "",\n                top_k=limit,\n                source_types=("material",),\n            )\n            hits: list[RetrievalHit] = []\n            for item in items:\n                if item.source_type != "material":\n                    continue\n                hit = _context_item_to_hit(item)\n                metadata = dict(hit.metadata)\n                metadata.update(\n                    {\n                        "material_id": int(hit.source_id),\n                        "chunk_index": 0,\n                        "source": f"material:{hit.source_id}",\n                        "backend": "context_store",\n                        "score_normalization": "context_store",\n                    }\n                )\n                hits.append(replace(hit, metadata=metadata))\n            return hits[:limit]\n\n        scope = MaterialSearchScope(\n            user_id=user_id,\n            material_ids=material_ids,\n            material_id_min=material_id_min,\n            material_id_max=material_id_max,\n            project_id=project_id,\n        )\n        chunks = await self.material_backend.search(query, scope=scope, top_k=limit)\n'''
if router.count(old_scope) != 1:
    raise RuntimeError(f"material scope target count={router.count(old_scope)}")
router_path.write_text(router.replace(old_scope, new_scope, 1), encoding="utf-8")

tests = test_path.read_text(encoding="utf-8")
tests = tests.replace(
    "from app.services.context_store import L0, L1\n",
    "from app.services.context_store import L0, L1, ContextItem\n",
    1,
)
old_fake = '''class _FakeContextStore:\n    async def retrieve(self, *args, **kwargs):\n        return []\n\n    async def load_tiered(self, *args, **kwargs):\n        return ""\n'''
new_fake = '''class _FakeContextStore:\n    def __init__(self, items=None):\n        self.items = list(items or [])\n        self.calls = []\n\n    async def retrieve(self, *args, **kwargs):\n        self.calls.append((args, kwargs))\n        return self.items\n\n    async def load_tiered(self, *args, **kwargs):\n        return ""\n'''
if tests.count(old_fake) != 1:
    raise RuntimeError(f"fake store target count={tests.count(old_fake)}")
tests = tests.replace(old_fake, new_fake, 1)
insert_before = '''    async def test_l0_loading_uses_title_without_database_access(self):\n'''
new_test = '''    async def test_empty_material_query_returns_recent_context_store_materials(self):\n        store = _FakeContextStore(\n            [\n                ContextItem(\n                    source_type="material",\n                    source_id=12,\n                    title="Recent material",\n                    excerpt="recent preview",\n                    score=0.1,\n                )\n            ]\n        )\n        backend = _FakeMaterialBackend(error=AssertionError("semantic backend should not run"))\n        router = RetrievalRouter(_FakeDb(), material_backend=backend, context_store=store)\n\n        hits = await router.search(\n            "", user_id=9, source_types=("material",), top_k=3\n        )\n\n        self.assertEqual(len(hits), 1)\n        self.assertEqual(hits[0].source_id, 12)\n        self.assertEqual(hits[0].metadata["backend"], "context_store")\n        self.assertEqual(hits[0].metadata["source"], "material:12")\n        self.assertEqual(backend.calls, [])\n        self.assertEqual(store.calls[0][1]["source_types"], ("material",))\n\n'''
if tests.count(insert_before) != 1:
    raise RuntimeError(f"test insertion target count={tests.count(insert_before)}")
tests = tests.replace(insert_before, new_test + insert_before, 1)
test_path.write_text(tests, encoding="utf-8")
