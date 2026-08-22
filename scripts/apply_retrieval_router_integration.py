from __future__ import annotations

import re
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]


def replace_once(path: str, old: str, new: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{path}: expected one match, found {count}: {old[:100]!r}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")


def regex_replace_once(path: str, pattern: str, replacement: str) -> None:
    target = ROOT / path
    text = target.read_text(encoding="utf-8")
    updated, count = re.subn(pattern, replacement, text, count=1, flags=re.S)
    if count != 1:
        raise RuntimeError(f"{path}: expected one regex match, found {count}: {pattern[:100]!r}")
    target.write_text(updated, encoding="utf-8")


def patch_chat() -> None:
    path = "backend/app/routers/chat.py"
    replace_once(
        path,
        "from app.ai.rag_service import get_rag_service\n",
        "from app.ai.rag_service import get_rag_service\nfrom app.services.retrieval_router import RetrievalRouter\n",
    )
    replace_once(
        path,
        '''            rag = get_rag_service()\n            large_ids = [m["id"] for m in large_materials]\n            chunks = await rag.retrieve(query=message, material_ids=large_ids, user_id=user_id)\n''',
        '''            retrieval_router = RetrievalRouter(db)\n            large_ids = [m["id"] for m in large_materials]\n            material_hits = await retrieval_router.search(\n                message,\n                user_id=user_id,\n                source_types=("material",),\n                material_ids=large_ids,\n                top_k=max(1, int(getattr(settings, "RAG_TOP_K", 5))),\n                load_level=1,\n            )\n            chunks = [hit.to_material_chunk() for hit in material_hits]\n''',
    )


def patch_note_context() -> None:
    path = "backend/app/services/note_context_service.py"
    replace_once(
        path,
        "from app.services.context_store import ContextItem, get_context_store\n",
        "from app.services.retrieval_router import RetrievalHit, RetrievalRouter\n",
    )
    replace_once(
        path,
        "def _context_item_to_note_hit(item: ContextItem) -> NoteContextHit:\n",
        "def _context_item_to_note_hit(item: RetrievalHit) -> NoteContextHit:\n",
    )
    regex_replace_once(
        path,
        r'''    try:\n        items = await get_context_store\(\)\.retrieve\(\n            db,\n            user_id,\n            query,\n            top_k=max\(1, min\(int\(limit or 3\), 12\)\),\n            source_types=\("note",\),\n        \)\n    except Exception:\n''',
        '''    try:\n        items = await RetrievalRouter(db).search(\n            query,\n            user_id=user_id,\n            top_k=max(1, min(int(limit or 3), 12)),\n            source_types=("note",),\n        )\n    except Exception:\n''',
    )


def patch_chat_agent() -> None:
    path = "backend/app/agents/chat_agent.py"
    replace_once(
        path,
        "from app.services.note_retriever import NoteRetriever\n",
        "from app.services.note_retriever import NoteRetriever\nfrom app.services.retrieval_router import RetrievalRouter\n",
    )
    replace_once(
        path,
        '''        if tool == "search_memories":\n            return await self._search_memories(ctx, query, limit)\n''',
        '''        if tool == "search_memories":\n            return await self._search_memories(ctx, query, limit)\n        if tool == "search_concepts":\n            return await self._search_concepts(ctx, query, limit)\n        if tool == "search_learner_state":\n            return await self._search_learner_state(ctx, query, limit)\n''',
    )
    regex_replace_once(
        path,
        r'''    async def _search_notes\(self, ctx: AgentRunContext, query: str, limit: int\) -> dict:\n.*?\n    async def _search_wrong_questions''',
        '''    async def _router_search(\n        self,\n        ctx: AgentRunContext,\n        query: str,\n        limit: int,\n        *,\n        tool: str,\n        source_type: str,\n        route: str,\n    ) -> dict:\n        hits = await RetrievalRouter(ctx.db).search(\n            query,\n            user_id=ctx.user_id,\n            source_types=(source_type,),\n            top_k=limit,\n        )\n        items = []\n        for hit in hits:\n            item = hit.to_dict()\n            item.update(\n                {\n                    "id": hit.source_id,\n                    "title": hit.title,\n                    "content_preview": hit.excerpt[:240],\n                    "route": route,\n                }\n            )\n            items.append(item)\n        return {"tool": tool, "query": query, "items": items}\n\n    async def _search_notes(self, ctx: AgentRunContext, query: str, limit: int) -> dict:\n        return await self._router_search(\n            ctx, query, limit, tool="search_notes", source_type="note", route="/notes"\n        )\n\n    async def _search_materials(self, ctx: AgentRunContext, query: str, limit: int) -> dict:\n        return await self._router_search(\n            ctx, query, limit, tool="search_materials", source_type="material", route="/materials"\n        )\n\n    async def _search_wrong_questions''',
    )
    regex_replace_once(
        path,
        r'''    async def _search_memories\(self, ctx: AgentRunContext, query: str, limit: int\) -> dict:\n.*?\n    async def _get_profile''',
        '''    async def _search_memories(self, ctx: AgentRunContext, query: str, limit: int) -> dict:\n        return await self._router_search(\n            ctx, query, limit, tool="search_memories", source_type="memory", route="/agent"\n        )\n\n    async def _search_concepts(self, ctx: AgentRunContext, query: str, limit: int) -> dict:\n        return await self._router_search(\n            ctx, query, limit, tool="search_concepts", source_type="concept", route="/knowledge-graph"\n        )\n\n    async def _search_learner_state(self, ctx: AgentRunContext, query: str, limit: int) -> dict:\n        return await self._router_search(\n            ctx,\n            query,\n            limit,\n            tool="search_learner_state",\n            source_type="learner_state",\n            route="/agent",\n        )\n\n    async def _get_profile''',
    )


def patch_agent_kernel() -> None:
    path = "backend/app/agents/agent_kernel.py"
    replace_once(
        path,
        '''    "search_memories": ("检索关于我的长期记忆", '{"query":"关键词","limit":5}'),\n''',
        '''    "search_memories": ("检索关于我的长期记忆", '{"query":"关键词","limit":5}'),\n    "search_concepts": ("检索知识图谱中的概念及关系", '{"query":"概念关键词","limit":5}'),\n    "search_learner_state": ("检索概念掌握度、置信度和遗忘风险", '{"query":"概念关键词","limit":5}'),\n''',
    )
    replace_once(
        path,
        '''        "search_memories",\n        "get_profile",\n''',
        '''        "search_memories",\n        "search_concepts",\n        "search_learner_state",\n        "get_profile",\n''',
    )
    regex_replace_once(
        path,
        r'''    if tool == "context_retrieve":\n        from app\.services\.context_store import get_context_store\n\n        items = await get_context_store\(\)\.retrieve\(db, user_id, query, top_k=limit\)\n        return \{\n            "tool": tool,\n            "items": \[\n                \{\n                    "source_type": item\.source_type,\n                    "source_id": item\.source_id,\n                    "title": item\.title,\n                    "excerpt": item\.excerpt,\n                \}\n                for item in items\n            \],\n        \}\n''',
        '''    if tool == "context_retrieve":\n        from app.services.retrieval_router import RetrievalRouter\n\n        items = await RetrievalRouter(db).search(\n            query, user_id=user_id, top_k=limit\n        )\n        return {"tool": tool, "items": [item.to_dict() for item in items]}\n''',
    )


def patch_agent_api() -> None:
    path = "backend/app/routers/agent.py"
    replace_once(
        path,
        '''    tool: Literal["search_notes", "search_materials", "search_wrong_questions", "search_memories", "get_profile", "get_agent_learning_profile", "get_today_tasks", "get_recent_feedback"]\n''',
        '''    tool: Literal[\n        "search_notes",\n        "search_materials",\n        "search_wrong_questions",\n        "search_memories",\n        "search_concepts",\n        "search_learner_state",\n        "get_profile",\n        "get_agent_learning_profile",\n        "get_today_tasks",\n        "get_recent_feedback",\n    ]\n''',
    )


def main() -> None:
    patch_chat()
    patch_note_context()
    patch_chat_agent()
    patch_agent_kernel()
    patch_agent_api()


if __name__ == "__main__":
    main()
