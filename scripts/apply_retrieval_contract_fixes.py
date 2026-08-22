from pathlib import Path

root = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = root / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


replace_once(
    "backend/app/services/retrieval_router.py",
    '''        limit = max(1, min(int(top_k or 8), 50))\n        source_limit = max(limit, min(int(per_source_k or limit * 3), 80))\n''',
    '''        limit = max(1, min(int(top_k or 8), 50))\n        if per_source_k is not None:\n            source_limit = max(limit, min(int(per_source_k), 80))\n        elif len(requested) == 1:\n            source_limit = limit\n        else:\n            source_limit = max(limit, min(limit * 3, 80))\n''',
)

replace_once(
    "backend/app/services/note_context_service.py",
    '''    try:\n        items = await RetrievalRouter(db).search(\n            query,\n            user_id=user_id,\n            top_k=max(1, min(int(limit or 3), 12)),\n            source_types=("note",),\n        )\n    except Exception:\n''',
    '''    try:\n        response = await RetrievalRouter(db).search_with_diagnostics(\n            query,\n            user_id=user_id,\n            top_k=max(1, min(int(limit or 3), 12)),\n            source_types=("note",),\n        )\n        if "note" in response.diagnostics.degraded_sources:\n            raise RuntimeError("note retrieval failed")\n        items = response.hits\n    except Exception:\n''',
)

replace_once(
    "backend/app/agents/chat_agent.py",
    '''            item.update(\n                {\n                    "id": hit.source_id,\n                    "title": hit.title,\n                    "content_preview": hit.excerpt[:240],\n                    "route": route,\n                }\n            )\n            items.append(item)\n''',
    '''            item.update(\n                {\n                    "id": hit.source_id,\n                    "title": hit.title,\n                    "content_preview": hit.excerpt[:240],\n                    "route": route,\n                }\n            )\n            if source_type == "memory":\n                item.update(\n                    {\n                        "memory_key": hit.title,\n                        "memory_value": hit.excerpt,\n                        "category": hit.metadata.get("category"),\n                        "confidence": hit.metadata.get("confidence"),\n                        "is_locked": hit.metadata.get("locked"),\n                        "review_status": hit.metadata.get("review_status"),\n                    }\n                )\n            items.append(item)\n''',
)

replace_once(
    "backend/tests/test_retrieval_router.py",
    '''        self.assertGreaterEqual(requested_k, 4)\n''',
    '''        self.assertEqual(requested_k, 4)\n''',
)
