"""ContextStore：统一上下文检索底座接口（决策 D3，接口先行）。

目标：收敛 RAG（Chroma）、笔记（关键词）、记忆（SQL）三套割裂检索。
业务代码只依赖本接口；实现可替换——OpenViking spike 通过则由其实现，
否则由 Chroma+关键词保底实现承接。本文件先交付接口契约 + 保底实现。

分层加载语义（对齐 OpenViking L0/L1/L2）：
- L0：标题/一行摘要（最省 token）
- L1：摘录（约 200 字）
- L2：全文（按需加载）
"""
from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.material import Material
from app.models.memory import UserMemory
from app.models.note import Note

SOURCE_TYPES = ("material", "note", "memory")
L0, L1, L2 = 0, 1, 2
_EXCERPT_CHARS = 200


@dataclass(frozen=True)
class ContextItem:
    """一条检索结果：带来源与分层内容指针。"""

    source_type: str  # material | note | memory
    source_id: int
    title: str
    excerpt: str
    score: float = 0.0
    metadata: dict[str, Any] = field(default_factory=dict)


class ContextStore(Protocol):
    """统一上下文底座接口。实现必须满足用户隔离与降级纪律。"""

    async def ingest(
        self, db: AsyncSession, user_id: int, source_type: str, source_id: int
    ) -> bool:
        """登记/索引一条内容。实现可以延迟建索引；失败不得抛出致命异常。"""
        ...

    async def retrieve(
        self,
        db: AsyncSession,
        user_id: int,
        query: str,
        *,
        top_k: int = 5,
        source_types: tuple[str, ...] = SOURCE_TYPES,
    ) -> list[ContextItem]:
        """混合召回：返回按相关度排序的上下文条目（L1 粒度摘录）。"""
        ...

    async def load_tiered(
        self, db: AsyncSession, user_id: int, source_type: str, source_id: int, level: int
    ) -> str:
        """按层级取内容：L0 标题 / L1 摘录 / L2 全文。找不到返回空串。"""
        ...

    async def forget(
        self, db: AsyncSession, user_id: int, source_type: str, source_id: int
    ) -> bool:
        """移除索引记录（内容本体由领域服务负责删除）。"""
        ...


def _excerpt(text: str, limit: int = _EXCERPT_CHARS) -> str:
    clean = " ".join(str(text or "").split())
    return clean[:limit]


class KeywordContextStore:
    """保底实现：无向量索引，直接对领域表做关键词检索。

    - 无需 embedding key，任何环境可用（降级纪律的底座）。
    - ingest/forget 为幂等 no-op（关键词检索直查库，无独立索引需要维护）。
    """

    async def ingest(self, db: AsyncSession, user_id: int, source_type: str, source_id: int) -> bool:
        return source_type in SOURCE_TYPES

    async def forget(self, db: AsyncSession, user_id: int, source_type: str, source_id: int) -> bool:
        return source_type in SOURCE_TYPES

    async def retrieve(
        self,
        db: AsyncSession,
        user_id: int,
        query: str,
        *,
        top_k: int = 5,
        source_types: tuple[str, ...] = SOURCE_TYPES,
    ) -> list[ContextItem]:
        top_k = max(1, min(int(top_k or 5), 20))
        keyword = str(query or "").strip()
        items: list[ContextItem] = []
        if "material" in source_types:
            items.extend(await self._retrieve_materials(db, user_id, keyword, top_k))
        if "note" in source_types:
            items.extend(await self._retrieve_notes(db, user_id, keyword, top_k))
        if "memory" in source_types:
            items.extend(await self._retrieve_memories(db, user_id, keyword, top_k))
        items.sort(key=lambda item: item.score, reverse=True)
        return items[:top_k]

    async def load_tiered(
        self, db: AsyncSession, user_id: int, source_type: str, source_id: int, level: int
    ) -> str:
        row = await self._load_row(db, user_id, source_type, source_id)
        if row is None:
            return ""
        title, content = row
        if level <= L0:
            return title
        if level == L1:
            return _excerpt(content)
        return content

    async def _load_row(
        self, db: AsyncSession, user_id: int, source_type: str, source_id: int
    ) -> tuple[str, str] | None:
        if source_type == "material":
            result = await db.execute(
                select(Material).where(Material.id == source_id, Material.user_id == user_id)
            )
            material = result.scalar_one_or_none()
            if material is None:
                return None
            return str(material.title or ""), str(material.content or "")
        if source_type == "note":
            result = await db.execute(
                select(Note).where(Note.id == source_id, Note.user_id == user_id)
            )
            note = result.scalar_one_or_none()
            if note is None:
                return None
            return str(note.title or ""), str(note.content or "")
        if source_type == "memory":
            result = await db.execute(
                select(UserMemory).where(UserMemory.id == source_id, UserMemory.user_id == user_id)
            )
            memory = result.scalar_one_or_none()
            if memory is None:
                return None
            return str(memory.memory_key or ""), str(memory.memory_value or "")
        return None

    async def _retrieve_materials(
        self, db: AsyncSession, user_id: int, keyword: str, limit: int
    ) -> list[ContextItem]:
        stmt = select(Material).where(Material.user_id == user_id)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(or_(Material.title.ilike(like), Material.content.ilike(like)))
        result = await db.execute(stmt.order_by(Material.updated_at.desc()).limit(limit))
        return [
            ContextItem(
                source_type="material",
                source_id=int(material.id),
                title=str(material.title or ""),
                excerpt=_excerpt(material.content or ""),
                score=self._score(keyword, material.title, material.content),
            )
            for material in result.scalars().all()
        ]

    async def _retrieve_notes(
        self, db: AsyncSession, user_id: int, keyword: str, limit: int
    ) -> list[ContextItem]:
        stmt = select(Note).where(Note.user_id == user_id)
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(or_(Note.title.ilike(like), Note.content.ilike(like), Note.tags.ilike(like)))
        result = await db.execute(stmt.order_by(Note.updated_at.desc()).limit(limit))
        return [
            ContextItem(
                source_type="note",
                source_id=int(note.id),
                title=str(note.title or ""),
                excerpt=_excerpt(note.content or ""),
                score=self._score(keyword, note.title, note.content),
            )
            for note in result.scalars().all()
        ]

    async def _retrieve_memories(
        self, db: AsyncSession, user_id: int, keyword: str, limit: int
    ) -> list[ContextItem]:
        stmt = select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
        )
        if keyword:
            like = f"%{keyword}%"
            stmt = stmt.where(or_(UserMemory.memory_key.ilike(like), UserMemory.memory_value.ilike(like)))
        result = await db.execute(stmt.order_by(UserMemory.last_seen_at.desc()).limit(limit))
        return [
            ContextItem(
                source_type="memory",
                source_id=int(memory.id),
                title=str(memory.memory_key or ""),
                excerpt=_excerpt(memory.memory_value or ""),
                score=self._score(keyword, memory.memory_key, memory.memory_value),
            )
            for memory in result.scalars().all()
        ]

    @staticmethod
    def _score(keyword: str, title: Any, content: Any) -> float:
        """朴素相关度：标题命中 > 正文命中 > 无关键词兜底排序。"""
        if not keyword:
            return 0.1
        key = keyword.lower()
        title_text = str(title or "").lower()
        content_text = str(content or "").lower()
        score = 0.0
        if key in title_text:
            score += 0.7
        if key in content_text:
            score += 0.3
        return score


_store_instance: ContextStore | None = None


def get_context_store() -> ContextStore:
    """底座工厂：实现选型的唯一切换点（D3）。

    当前返回关键词保底实现；OpenViking spike 通过后在此处替换实现，
    业务代码不需要任何改动。
    """
    global _store_instance
    if _store_instance is None:
        _store_instance = KeywordContextStore()
    return _store_instance


def set_context_store(store: ContextStore | None) -> None:
    """测试/运行时替换实现。传 None 恢复默认。"""
    global _store_instance
    _store_instance = store
