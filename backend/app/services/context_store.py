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

import json
import re
from dataclasses import dataclass, field
from datetime import datetime
from typing import Any, Protocol

from sqlalchemy import or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.material import Material
from app.models.memory import UserMemory
from app.models.note import Note

SOURCE_TYPES = ("material", "note", "memory")
L0, L1, L2 = 0, 1, 2
_EXCERPT_CHARS = 200
_NOTE_CANDIDATE_LIMIT = 80
_NOTE_WORD_RE = re.compile(r"[A-Za-z0-9_]+|[\u4e00-\u9fff]{2,}")
_CJK_BIGRAM_RE = re.compile(r"^[\u4e00-\u9fff]{2}$")
_NOTE_MARKDOWN_RE = re.compile(
    r"(```.*?```|`[^`]*`|!\[[^\]]*\]\([^)]+\)|\[[^\]]*\]\([^)]+\)|[#>*_\-]+)",
    re.S,
)


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


def _compact_note_text(value: Any, *, limit: int | None = None) -> str:
    text = _NOTE_MARKDOWN_RE.sub(" ", str(value or ""))
    text = re.sub(r"\s+", " ", text).strip()
    if limit is not None and len(text) > limit:
        return text[: max(0, limit - 1)].rstrip() + "…"
    return text


def _note_query_tokens(value: str) -> tuple[str, ...]:
    text = str(value or "").lower()
    tokens = [match.group(0) for match in _NOTE_WORD_RE.finditer(text)]
    for phrase in re.findall(r"[\u4e00-\u9fff]{4,}", text):
        tokens.extend(phrase[index : index + 2] for index in range(len(phrase) - 1))
    return tuple(dict.fromkeys(token for token in tokens if len(token) >= 2))


def _parse_note_tags(value: Any) -> list[str]:
    if isinstance(value, list):
        raw = value
    else:
        try:
            raw = json.loads(str(value or "[]"))
        except (TypeError, ValueError, json.JSONDecodeError):
            raw = [part.strip() for part in str(value or "").split(",")]
    return [str(item).strip() for item in raw if str(item).strip()][:8] if isinstance(raw, list) else []


def _note_excerpt(content: str, tokens: tuple[str, ...], *, limit: int = 220) -> str:
    compact = _compact_note_text(content)
    if not compact:
        return ""
    lowered = compact.lower()
    first_index = min((lowered.find(token) for token in tokens if token in lowered), default=-1)
    if first_index < 0:
        return _compact_note_text(compact, limit=limit)
    start = max(0, first_index - 60)
    end = min(len(compact), first_index + limit)
    prefix = "…" if start else ""
    suffix = "…" if end < len(compact) else ""
    return f"{prefix}{compact[start:end].strip()}{suffix}"


def _score_note_context(note: Note, tokens: tuple[str, ...]) -> tuple[float, str]:
    title = str(note.title or "")
    content = str(note.content or "")
    tags = " ".join(_parse_note_tags(note.tags))
    haystack = f"{title} {tags} {content}".lower()
    matches = [token for token in tokens if token in haystack]
    if not matches:
        return 0.0, ""
    cjk_bigrams = [token for token in tokens if _CJK_BIGRAM_RE.fullmatch(token)]
    matched_cjk_bigrams = [token for token in matches if _CJK_BIGRAM_RE.fullmatch(token)]
    if len(cjk_bigrams) >= 4 and len(matched_cjk_bigrams) < 3:
        return 0.0, ""
    score = float(len(matches))
    if any(token in title.lower() for token in matches):
        score += 3.0
    if any(token in tags.lower() for token in matches):
        score += 1.5
    if content.strip():
        score += 0.2
    return score, "关键词匹配：" + "、".join(matches[:5])


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
        self, db: AsyncSession, user_id: int, query: str, limit: int
    ) -> list[ContextItem]:
        tokens = _note_query_tokens(query)
        if not tokens:
            result = await db.execute(
                select(Note)
                .where(Note.user_id == user_id)
                .order_by(Note.updated_at.desc(), Note.created_at.desc(), Note.id.desc())
                .limit(limit)
            )
            return [
                ContextItem(
                    source_type="note",
                    source_id=int(note.id),
                    title=_compact_note_text(note.title or "未命名笔记", limit=80),
                    excerpt=_note_excerpt(note.content or "", ()),
                    score=0.1,
                    metadata={
                        "tags": _parse_note_tags(note.tags),
                        "reason": "",
                        "updated_at": note.updated_at or note.created_at,
                        "retrieval_mode": "keyword_sql",
                    },
                )
                for note in result.scalars().all()
            ]

        result = await db.execute(
            select(Note)
            .where(Note.user_id == user_id)
            .order_by(Note.updated_at.desc(), Note.created_at.desc(), Note.id.desc())
            .limit(_NOTE_CANDIDATE_LIMIT)
        )
        ranked: list[ContextItem] = []
        for index, note in enumerate(result.scalars().all()):
            score, reason = _score_note_context(note, tokens)
            if score <= 0:
                continue
            excerpt = _note_excerpt(note.content or "", tokens)
            if not excerpt:
                continue
            updated_at = note.updated_at or note.created_at
            ranked.append(
                ContextItem(
                    source_type="note",
                    source_id=int(note.id),
                    title=_compact_note_text(note.title or "未命名笔记", limit=80),
                    excerpt=excerpt,
                    score=score + max(0.0, (_NOTE_CANDIDATE_LIMIT - index) / _NOTE_CANDIDATE_LIMIT) * 0.1,
                    metadata={
                        "tags": _parse_note_tags(note.tags),
                        "reason": reason,
                        "updated_at": updated_at,
                        "retrieval_mode": "keyword_sql",
                    },
                )
            )
        ranked.sort(
            key=lambda item: (item.score, item.metadata.get("updated_at") or datetime.min, item.source_id),
            reverse=True,
        )
        return ranked[:limit]

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
