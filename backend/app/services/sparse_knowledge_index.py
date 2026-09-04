"""Replaceable sparse retrieval for canonical Knowledge V2 Claims.

Stage 5 keeps a dependency-free SQL reference implementation as the rollback
path and provides an opt-in SQLite FTS5 spike. Product-visible callers must
still revalidate returned Claim ids against canonical SQL lifecycle/evidence
rules before displaying anything.
"""
from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any, Protocol, Sequence

from sqlalchemy import exists, func, select, text as sql_text
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.knowledge import (
    Claim,
    ClaimEvidence,
    KnowledgeSource,
    KnowledgeSourceRevision,
)


_WORD_RE = re.compile(r"[a-z0-9_]+|[\u4e00-\u9fff]+", re.IGNORECASE)


@dataclass(frozen=True)
class SparseKnowledgeHit:
    claim_id: int
    score: float
    backend: str


class SparseKnowledgeIndex(Protocol):
    async def search(self, *, user_id: int, text: str, top_k: int = 30) -> list[SparseKnowledgeHit]: ...
    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]: ...
    async def upsert_claim(self, *, user_id: int, claim_id: int, clear_dirty: bool = True) -> dict[str, Any]: ...
    async def delete_claim(self, *, user_id: int, claim_id: int, clear_dirty: bool = True) -> dict[str, Any]: ...
    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]: ...
    async def mark_claim_dirty(self, *, user_id: int, claim_id: int) -> None: ...
    async def mark_user_dirty(self, *, user_id: int) -> None: ...
    async def health(self) -> dict[str, Any]: ...


def tokenize_sparse_text(value: str) -> tuple[str, ...]:
    output: list[str] = []
    for token in _WORD_RE.findall(str(value or "").casefold()):
        output.append(token)
        if re.fullmatch(r"[\u4e00-\u9fff]+", token) and len(token) > 2:
            output.extend(token[index : index + 2] for index in range(len(token) - 1))
    return tuple(dict.fromkeys(item for item in output if len(item) >= 2))


def lexical_sparse_score(query: str, document: str) -> float:
    query_tokens = set(tokenize_sparse_text(query))
    document_tokens = set(tokenize_sparse_text(document))
    if not query_tokens or not document_tokens:
        return 0.0
    overlap = query_tokens & document_tokens
    if not overlap:
        return 0.0
    score = len(overlap) / max(1, min(len(query_tokens), len(document_tokens)))
    if len(overlap) == 1 and len(next(iter(overlap))) <= 3:
        return 0.0
    return max(0.0, min(1.0, score))


def _visible_claim_statement(user_id: int):
    return (
        select(Claim.id, Claim.statement, KnowledgeSource.source_key)
        .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == Claim.source_revision_id)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
        .where(
            Claim.user_id == int(user_id),
            Claim.review_status == "confirmed",
            Claim.lifecycle_status == "active",
            KnowledgeSourceRevision.user_id == int(user_id),
            KnowledgeSourceRevision.status == "current",
            KnowledgeSource.user_id == int(user_id),
            KnowledgeSource.status == "active",
            exists().where(
                ClaimEvidence.user_id == int(user_id),
                ClaimEvidence.claim_id == Claim.id,
            ),
        )
    )


_INCREMENTAL_DIRTY_LIMIT = 128
_SPARSE_SCHEMA_READY: set[tuple[str, int]] = set()


class ReferenceSparseKnowledgeIndex:
    """Stage 4-compatible full-scan reference and universal fallback."""

    name = "reference"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def search(self, *, user_id: int, text: str, top_k: int = 30) -> list[SparseKnowledgeHit]:
        query = str(text or "").strip()
        if not query or top_k <= 0:
            return []
        rows = (await self.db.execute(_visible_claim_statement(int(user_id)))).all()
        scored = [
            SparseKnowledgeHit(int(claim_id), score, self.name)
            for claim_id, statement, _ in rows
            if (score := lexical_sparse_score(query, str(statement))) >= 0.18
        ]
        scored.sort(key=lambda row: (-row.score, row.claim_id))
        return scored[: max(1, min(100, int(top_k)))]

    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]:
        count = len((await self.db.execute(_visible_claim_statement(int(user_id)))).all())
        return {"backend": self.name, "user_id": int(user_id), "rebuilt": False, "visible_claims": count}

    async def upsert_claim(self, *, user_id: int, claim_id: int, clear_dirty: bool = True) -> dict[str, Any]:
        return {"backend": self.name, "user_id": int(user_id), "claim_id": int(claim_id), "upserted": False, "authoritative": True}

    async def delete_claim(self, *, user_id: int, claim_id: int, clear_dirty: bool = True) -> dict[str, Any]:
        return {"backend": self.name, "user_id": int(user_id), "claim_id": int(claim_id), "deleted": False, "authoritative": True}

    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]:
        return {"backend": self.name, "user_id": int(user_id), "source_key": str(source_key), "deleted": False, "authoritative": True}

    async def mark_claim_dirty(self, *, user_id: int, claim_id: int) -> None:
        return None

    async def mark_user_dirty(self, *, user_id: int) -> None:
        return None

    async def health(self) -> dict[str, Any]:
        return {"ok": True, "backend": self.name, "persistent": False}


class SqliteFts5SparseKnowledgeIndex:
    """Opt-in persistent FTS5 spike over normalized Claim tokens.

    The index is disposable. `rebuild_user` is the authoritative sync operation;
    `search` never makes an unindexed Claim visible by itself. Stage 5 keeps this
    backend opt-in until lifecycle hooks and scale gates are complete.
    """

    name = "sqlite_fts5"
    _table = "knowledge_claim_fts"
    _state_table = "knowledge_claim_fts_state"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _ensure_supported(self) -> None:
        bind = self.db.get_bind()
        if bind.dialect.name != "sqlite":
            raise RuntimeError("sqlite_fts5_backend_requires_sqlite")
        ready_key = (self.name, id(bind))
        if ready_key in _SPARSE_SCHEMA_READY:
            return
        try:
            await self.db.execute(sql_text(
                "CREATE VIRTUAL TABLE IF NOT EXISTS knowledge_claim_fts "
                "USING fts5(search_text, statement UNINDEXED, claim_id UNINDEXED, "
                "user_id UNINDEXED, source_key UNINDEXED)"
            ))
            await self.db.execute(sql_text(
                "CREATE TABLE IF NOT EXISTS knowledge_claim_fts_state ("
                "user_id INTEGER PRIMARY KEY, visible_count INTEGER NOT NULL, "
                "max_claim_updated TEXT NOT NULL, max_source_updated TEXT NOT NULL, "
                "max_revision_id INTEGER NOT NULL)"
            ))
            await self.db.execute(sql_text(
                "CREATE TABLE IF NOT EXISTS knowledge_sparse_dirty (user_id INTEGER PRIMARY KEY)"
            ))
            await self.db.execute(sql_text(
                "CREATE TABLE IF NOT EXISTS knowledge_sparse_dirty_claim ("
                "user_id INTEGER NOT NULL, claim_id INTEGER NOT NULL, "
                "PRIMARY KEY(user_id, claim_id))"
            ))
        except Exception as exc:
            raise RuntimeError("sqlite_fts5_unavailable") from exc
        _SPARSE_SCHEMA_READY.add(ready_key)

    @staticmethod
    def _match_query(value: str) -> str:
        tokens = tokenize_sparse_text(value)
        return " OR ".join(f'"{token.replace(chr(34), "")}"' for token in tokens)

    async def _canonical_signature(self, *, user_id: int) -> tuple[int, str, str, int]:
        row = (await self.db.execute(
            select(
                func.count(Claim.id),
                func.max(Claim.updated_at),
                func.max(KnowledgeSource.updated_at),
                func.max(KnowledgeSourceRevision.id),
            )
            .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == Claim.source_revision_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
            .where(
                Claim.user_id == int(user_id),
                Claim.review_status == "confirmed",
                Claim.lifecycle_status == "active",
                KnowledgeSourceRevision.user_id == int(user_id),
                KnowledgeSourceRevision.status == "current",
                KnowledgeSource.user_id == int(user_id),
                KnowledgeSource.status == "active",
                exists().where(
                    ClaimEvidence.user_id == int(user_id),
                    ClaimEvidence.claim_id == Claim.id,
                ),
            )
        )).one()
        return (
            int(row[0] or 0),
            str(row[1] or ""),
            str(row[2] or ""),
            int(row[3] or 0),
        )

    async def _write_state(self, *, user_id: int, signature: tuple[int, str, str, int]) -> None:
        await self.db.execute(
            sql_text(
                "INSERT INTO knowledge_claim_fts_state(user_id, visible_count, max_claim_updated, max_source_updated, max_revision_id) "
                "VALUES (:user_id, :visible_count, :max_claim_updated, :max_source_updated, :max_revision_id) "
                "ON CONFLICT(user_id) DO UPDATE SET visible_count = excluded.visible_count, "
                "max_claim_updated = excluded.max_claim_updated, max_source_updated = excluded.max_source_updated, "
                "max_revision_id = excluded.max_revision_id"
            ),
            {
                "user_id": int(user_id),
                "visible_count": signature[0],
                "max_claim_updated": signature[1],
                "max_source_updated": signature[2],
                "max_revision_id": signature[3],
            },
        )

    async def _is_stale(self, *, user_id: int) -> bool:
        dirty = await self.db.scalar(
            sql_text("SELECT 1 FROM knowledge_sparse_dirty WHERE user_id = :user_id"),
            {"user_id": int(user_id)},
        )
        if dirty:
            return True
        state = (await self.db.execute(
            sql_text(
                "SELECT visible_count, max_claim_updated, max_source_updated, max_revision_id "
                "FROM knowledge_claim_fts_state WHERE user_id = :user_id"
            ),
            {"user_id": int(user_id)},
        )).first()
        if state is None:
            return True
        if not settings.KNOWLEDGE_SPARSE_VERIFY_SIGNATURE:
            return False
        signature = await self._canonical_signature(user_id=int(user_id))
        return tuple(state) != signature

    async def _clear_claim_dirty(self, *, user_id: int, claim_id: int) -> None:
        await self.db.execute(
            sql_text(
                "DELETE FROM knowledge_sparse_dirty_claim "
                "WHERE user_id = :user_id AND claim_id = :claim_id"
            ),
            {"user_id": int(user_id), "claim_id": int(claim_id)},
        )

    async def _dirty_claim_ids(self, *, user_id: int) -> list[int]:
        rows = (await self.db.execute(
            sql_text(
                "SELECT claim_id FROM knowledge_sparse_dirty_claim "
                "WHERE user_id = :user_id ORDER BY claim_id LIMIT :limit"
            ),
            {"user_id": int(user_id), "limit": _INCREMENTAL_DIRTY_LIMIT + 1},
        )).all()
        return [int(row[0]) for row in rows]

    async def _sync_dirty_claims(self, *, user_id: int) -> None:
        claim_ids = await self._dirty_claim_ids(user_id=int(user_id))
        if len(claim_ids) > _INCREMENTAL_DIRTY_LIMIT:
            await self.rebuild_user(user_id=int(user_id))
            return
        for claim_id in claim_ids:
            await self.upsert_claim(
                user_id=int(user_id),
                claim_id=int(claim_id),
                clear_dirty=True,
            )

    async def search(self, *, user_id: int, text: str, top_k: int = 30) -> list[SparseKnowledgeHit]:
        query = str(text or "").strip()
        match_query = self._match_query(query)
        if not match_query or top_k <= 0:
            return []
        await self._ensure_supported()
        if await self._is_stale(user_id=int(user_id)):
            await self.rebuild_user(user_id=int(user_id))
        else:
            await self._sync_dirty_claims(user_id=int(user_id))
        rows = (await self.db.execute(
            sql_text(
                "SELECT claim_id, statement, bm25(knowledge_claim_fts) AS rank "
                "FROM knowledge_claim_fts "
                "WHERE knowledge_claim_fts MATCH :query AND user_id = :user_id "
                "ORDER BY rank ASC LIMIT :limit"
            ),
            {"query": match_query, "user_id": str(int(user_id)), "limit": max(1, min(200, int(top_k) * 4))},
        )).all()
        scored: list[SparseKnowledgeHit] = []
        for claim_id, statement, _ in rows:
            score = lexical_sparse_score(query, str(statement))
            if score >= 0.18:
                scored.append(SparseKnowledgeHit(int(claim_id), score, self.name))
        scored.sort(key=lambda row: (-row.score, row.claim_id))
        return scored[: max(1, min(100, int(top_k)))]

    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]:
        await self._ensure_supported()
        rows = (await self.db.execute(_visible_claim_statement(int(user_id)).order_by(Claim.id.asc()))).all()
        await self.db.execute(
            sql_text("DELETE FROM knowledge_claim_fts WHERE user_id = :user_id"),
            {"user_id": str(int(user_id))},
        )
        for claim_id, statement, source_key in rows:
            search_text = " ".join(tokenize_sparse_text(str(statement)))
            if not search_text:
                continue
            await self.db.execute(
                sql_text(
                    "INSERT INTO knowledge_claim_fts(search_text, statement, claim_id, user_id, source_key) "
                    "VALUES (:search_text, :statement, :claim_id, :user_id, :source_key)"
                ),
                {
                    "search_text": search_text,
                    "statement": str(statement),
                    "claim_id": str(int(claim_id)),
                    "user_id": str(int(user_id)),
                    "source_key": str(source_key),
                },
            )
        signature = await self._canonical_signature(user_id=int(user_id))
        await self._write_state(user_id=int(user_id), signature=signature)
        await self.db.execute(
            sql_text("DELETE FROM knowledge_sparse_dirty WHERE user_id = :user_id"),
            {"user_id": int(user_id)},
        )
        await self.db.execute(
            sql_text("DELETE FROM knowledge_sparse_dirty_claim WHERE user_id = :user_id"),
            {"user_id": int(user_id)},
        )
        await self.db.flush()
        return {"backend": self.name, "user_id": int(user_id), "rebuilt": True, "indexed_claims": len(rows)}

    async def upsert_claim(self, *, user_id: int, claim_id: int, clear_dirty: bool = True) -> dict[str, Any]:
        await self._ensure_supported()
        row = (await self.db.execute(
            _visible_claim_statement(int(user_id)).where(Claim.id == int(claim_id))
        )).first()
        if row is None:
            return await self.delete_claim(
                user_id=int(user_id),
                claim_id=int(claim_id),
                clear_dirty=bool(clear_dirty),
            )
        visible_claim_id, statement, source_key = row
        await self.db.execute(
            sql_text(
                "DELETE FROM knowledge_claim_fts WHERE user_id = :user_id AND claim_id = :claim_id"
            ),
            {"user_id": str(int(user_id)), "claim_id": str(int(visible_claim_id))},
        )
        search_text = " ".join(tokenize_sparse_text(str(statement)))
        if search_text:
            await self.db.execute(
                sql_text(
                    "INSERT INTO knowledge_claim_fts(search_text, statement, claim_id, user_id, source_key) "
                    "VALUES (:search_text, :statement, :claim_id, :user_id, :source_key)"
                ),
                {
                    "search_text": search_text,
                    "statement": str(statement),
                    "claim_id": str(int(visible_claim_id)),
                    "user_id": str(int(user_id)),
                    "source_key": str(source_key),
                },
            )
        if clear_dirty:
            await self._clear_claim_dirty(user_id=int(user_id), claim_id=int(claim_id))
        await self.db.flush()
        return {
            "backend": self.name,
            "user_id": int(user_id),
            "claim_id": int(claim_id),
            "upserted": bool(search_text),
        }

    async def delete_claim(self, *, user_id: int, claim_id: int, clear_dirty: bool = True) -> dict[str, Any]:
        await self._ensure_supported()
        result = await self.db.execute(
            sql_text(
                "DELETE FROM knowledge_claim_fts WHERE user_id = :user_id AND claim_id = :claim_id"
            ),
            {"user_id": str(int(user_id)), "claim_id": str(int(claim_id))},
        )
        if clear_dirty:
            await self._clear_claim_dirty(user_id=int(user_id), claim_id=int(claim_id))
        await self.db.flush()
        return {
            "backend": self.name,
            "user_id": int(user_id),
            "claim_id": int(claim_id),
            "deleted_rows": int(result.rowcount or 0),
        }

    async def mark_claim_dirty(self, *, user_id: int, claim_id: int) -> None:
        await self._ensure_supported()
        await self.db.execute(
            sql_text(
                "INSERT OR IGNORE INTO knowledge_sparse_dirty_claim(user_id, claim_id) "
                "VALUES (:user_id, :claim_id)"
            ),
            {"user_id": int(user_id), "claim_id": int(claim_id)},
        )
        await self.db.flush()

    async def mark_user_dirty(self, *, user_id: int) -> None:
        await self._ensure_supported()
        await self.db.execute(
            sql_text("INSERT OR IGNORE INTO knowledge_sparse_dirty(user_id) VALUES (:user_id)"),
            {"user_id": int(user_id)},
        )
        await self.db.flush()

    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]:
        await self._ensure_supported()
        result = await self.db.execute(
            sql_text("DELETE FROM knowledge_claim_fts WHERE user_id = :user_id AND source_key = :source_key"),
            {"user_id": str(int(user_id)), "source_key": str(source_key)},
        )
        # Keep the current canonical signature after an explicit projection
        # delete. This prevents lazy staleness repair from immediately
        # resurrecting the just-deleted FTS rows while the caller is still in
        # the same canonical tombstone transaction. Once SQL lifecycle state
        # changes, its timestamps/signature diverge and the next search safely
        # rebuilds from canonical visibility.
        signature = await self._canonical_signature(user_id=int(user_id))
        await self.db.execute(
            sql_text(
                "INSERT INTO knowledge_claim_fts_state(user_id, visible_count, max_claim_updated, max_source_updated, max_revision_id) "
                "VALUES (:user_id, :visible_count, :max_claim_updated, :max_source_updated, :max_revision_id) "
                "ON CONFLICT(user_id) DO UPDATE SET visible_count = excluded.visible_count, "
                "max_claim_updated = excluded.max_claim_updated, max_source_updated = excluded.max_source_updated, "
                "max_revision_id = excluded.max_revision_id"
            ),
            {
                "user_id": int(user_id),
                "visible_count": signature[0],
                "max_claim_updated": signature[1],
                "max_source_updated": signature[2],
                "max_revision_id": signature[3],
            },
        )
        await self.db.flush()
        return {"backend": self.name, "user_id": int(user_id), "source_key": str(source_key), "deleted_rows": int(result.rowcount or 0)}

    async def health(self) -> dict[str, Any]:
        try:
            await self._ensure_supported()
        except Exception as exc:
            return {"ok": False, "backend": self.name, "persistent": True, "error": str(exc)}
        return {"ok": True, "backend": self.name, "persistent": True}


class PostgresFtsSparseKnowledgeIndex:
    """Opt-in PostgreSQL native FTS over application-tokenized Claim text.

    Chinese bigrams and Latin tokens are produced by the same tokenizer as the
    reference backend, so this path does not depend on pg_trgm or a custom text
    search extension. The table is a disposable projection and can be rebuilt
    entirely from canonical SQL.
    """

    name = "postgres_fts"
    _table = "knowledge_claim_sparse"
    _state_table = "knowledge_claim_sparse_state"

    def __init__(self, db: AsyncSession) -> None:
        self.db = db

    async def _ensure_supported(self) -> None:
        bind = self.db.get_bind()
        if bind.dialect.name != "postgresql":
            raise RuntimeError("postgres_fts_backend_requires_postgresql")
        ready_key = (self.name, id(bind))
        if ready_key in _SPARSE_SCHEMA_READY:
            return
        await self.db.execute(sql_text(
            "CREATE TABLE IF NOT EXISTS knowledge_claim_sparse ("
            "user_id BIGINT NOT NULL, claim_id BIGINT PRIMARY KEY, source_key TEXT NOT NULL, "
            "search_text TEXT NOT NULL, statement TEXT NOT NULL)"
        ))
        await self.db.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_claim_sparse_user ON knowledge_claim_sparse(user_id)"
        ))
        await self.db.execute(sql_text(
            "CREATE INDEX IF NOT EXISTS ix_knowledge_claim_sparse_fts ON knowledge_claim_sparse "
            "USING GIN (to_tsvector('simple', search_text))"
        ))
        await self.db.execute(sql_text(
            "CREATE TABLE IF NOT EXISTS knowledge_claim_sparse_state ("
            "user_id BIGINT PRIMARY KEY, visible_count BIGINT NOT NULL, "
            "max_claim_updated TEXT NOT NULL, max_source_updated TEXT NOT NULL, "
            "max_revision_id BIGINT NOT NULL)"
        ))
        await self.db.execute(sql_text(
            "CREATE TABLE IF NOT EXISTS knowledge_sparse_dirty (user_id BIGINT PRIMARY KEY)"
        ))
        await self.db.execute(sql_text(
            "CREATE TABLE IF NOT EXISTS knowledge_sparse_dirty_claim ("
            "user_id BIGINT NOT NULL, claim_id BIGINT NOT NULL, "
            "PRIMARY KEY(user_id, claim_id))"
        ))
        _SPARSE_SCHEMA_READY.add(ready_key)

    async def _canonical_signature(self, *, user_id: int) -> tuple[int, str, str, int]:
        row = (await self.db.execute(
            select(
                func.count(Claim.id),
                func.max(Claim.updated_at),
                func.max(KnowledgeSource.updated_at),
                func.max(KnowledgeSourceRevision.id),
            )
            .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == Claim.source_revision_id)
            .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
            .where(
                Claim.user_id == int(user_id),
                Claim.review_status == "confirmed",
                Claim.lifecycle_status == "active",
                KnowledgeSourceRevision.user_id == int(user_id),
                KnowledgeSourceRevision.status == "current",
                KnowledgeSource.user_id == int(user_id),
                KnowledgeSource.status == "active",
                exists().where(
                    ClaimEvidence.user_id == int(user_id),
                    ClaimEvidence.claim_id == Claim.id,
                ),
            )
        )).one()
        return (int(row[0] or 0), str(row[1] or ""), str(row[2] or ""), int(row[3] or 0))

    async def _write_state(self, *, user_id: int, signature: tuple[int, str, str, int]) -> None:
        await self.db.execute(
            sql_text(
                "INSERT INTO knowledge_claim_sparse_state(user_id, visible_count, max_claim_updated, max_source_updated, max_revision_id) "
                "VALUES (:user_id, :visible_count, :max_claim_updated, :max_source_updated, :max_revision_id) "
                "ON CONFLICT(user_id) DO UPDATE SET visible_count = excluded.visible_count, "
                "max_claim_updated = excluded.max_claim_updated, max_source_updated = excluded.max_source_updated, "
                "max_revision_id = excluded.max_revision_id"
            ),
            {
                "user_id": int(user_id),
                "visible_count": signature[0],
                "max_claim_updated": signature[1],
                "max_source_updated": signature[2],
                "max_revision_id": signature[3],
            },
        )

    async def _is_stale(self, *, user_id: int) -> bool:
        dirty = await self.db.scalar(
            sql_text("SELECT 1 FROM knowledge_sparse_dirty WHERE user_id = :user_id"),
            {"user_id": int(user_id)},
        )
        if dirty:
            return True
        state = (await self.db.execute(
            sql_text(
                "SELECT visible_count, max_claim_updated, max_source_updated, max_revision_id "
                "FROM knowledge_claim_sparse_state WHERE user_id = :user_id"
            ),
            {"user_id": int(user_id)},
        )).first()
        if state is None:
            return True
        if not settings.KNOWLEDGE_SPARSE_VERIFY_SIGNATURE:
            return False
        signature = await self._canonical_signature(user_id=int(user_id))
        return tuple(state) != signature

    async def _clear_claim_dirty(self, *, user_id: int, claim_id: int) -> None:
        await self.db.execute(
            sql_text(
                "DELETE FROM knowledge_sparse_dirty_claim "
                "WHERE user_id = :user_id AND claim_id = :claim_id"
            ),
            {"user_id": int(user_id), "claim_id": int(claim_id)},
        )

    async def _dirty_claim_ids(self, *, user_id: int) -> list[int]:
        rows = (await self.db.execute(
            sql_text(
                "SELECT claim_id FROM knowledge_sparse_dirty_claim "
                "WHERE user_id = :user_id ORDER BY claim_id LIMIT :limit"
            ),
            {"user_id": int(user_id), "limit": _INCREMENTAL_DIRTY_LIMIT + 1},
        )).all()
        return [int(row[0]) for row in rows]

    async def _sync_dirty_claims(self, *, user_id: int) -> None:
        claim_ids = await self._dirty_claim_ids(user_id=int(user_id))
        if len(claim_ids) > _INCREMENTAL_DIRTY_LIMIT:
            await self.rebuild_user(user_id=int(user_id))
            return
        for claim_id in claim_ids:
            await self.upsert_claim(
                user_id=int(user_id),
                claim_id=int(claim_id),
                clear_dirty=True,
            )

    @staticmethod
    def _tsquery(value: str) -> str:
        return " | ".join(tokenize_sparse_text(value))

    async def search(self, *, user_id: int, text: str, top_k: int = 30) -> list[SparseKnowledgeHit]:
        query = str(text or "").strip()
        tsquery = self._tsquery(query)
        if not tsquery or top_k <= 0:
            return []
        await self._ensure_supported()
        if await self._is_stale(user_id=int(user_id)):
            await self.rebuild_user(user_id=int(user_id))
        else:
            await self._sync_dirty_claims(user_id=int(user_id))
        rows = (await self.db.execute(
            sql_text(
                "SELECT claim_id, statement, "
                "ts_rank_cd(to_tsvector('simple', search_text), to_tsquery('simple', :query)) AS rank "
                "FROM knowledge_claim_sparse WHERE user_id = :user_id "
                "AND to_tsvector('simple', search_text) @@ to_tsquery('simple', :query) "
                "ORDER BY rank DESC, claim_id ASC LIMIT :limit"
            ),
            {"query": tsquery, "user_id": int(user_id), "limit": max(1, min(200, int(top_k) * 4))},
        )).all()
        scored = [
            SparseKnowledgeHit(int(claim_id), score, self.name)
            for claim_id, statement, _ in rows
            if (score := lexical_sparse_score(query, str(statement))) >= 0.18
        ]
        scored.sort(key=lambda row: (-row.score, row.claim_id))
        return scored[: max(1, min(100, int(top_k)))]

    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]:
        await self._ensure_supported()
        rows = (await self.db.execute(_visible_claim_statement(int(user_id)).order_by(Claim.id.asc()))).all()
        await self.db.execute(
            sql_text("DELETE FROM knowledge_claim_sparse WHERE user_id = :user_id"),
            {"user_id": int(user_id)},
        )
        for claim_id, statement, source_key in rows:
            search_text = " ".join(tokenize_sparse_text(str(statement)))
            if not search_text:
                continue
            await self.db.execute(
                sql_text(
                    "INSERT INTO knowledge_claim_sparse(user_id, claim_id, source_key, search_text, statement) "
                    "VALUES (:user_id, :claim_id, :source_key, :search_text, :statement) "
                    "ON CONFLICT(claim_id) DO UPDATE SET user_id = excluded.user_id, source_key = excluded.source_key, "
                    "search_text = excluded.search_text, statement = excluded.statement"
                ),
                {
                    "user_id": int(user_id),
                    "claim_id": int(claim_id),
                    "source_key": str(source_key),
                    "search_text": search_text,
                    "statement": str(statement),
                },
            )
        signature = await self._canonical_signature(user_id=int(user_id))
        await self._write_state(user_id=int(user_id), signature=signature)
        await self.db.execute(sql_text("ANALYZE knowledge_claim_sparse"))
        await self.db.execute(
            sql_text("DELETE FROM knowledge_sparse_dirty WHERE user_id = :user_id"),
            {"user_id": int(user_id)},
        )
        await self.db.execute(
            sql_text("DELETE FROM knowledge_sparse_dirty_claim WHERE user_id = :user_id"),
            {"user_id": int(user_id)},
        )
        await self.db.flush()
        return {"backend": self.name, "user_id": int(user_id), "rebuilt": True, "indexed_claims": len(rows)}

    async def upsert_claim(self, *, user_id: int, claim_id: int, clear_dirty: bool = True) -> dict[str, Any]:
        await self._ensure_supported()
        row = (await self.db.execute(
            _visible_claim_statement(int(user_id)).where(Claim.id == int(claim_id))
        )).first()
        if row is None:
            return await self.delete_claim(
                user_id=int(user_id),
                claim_id=int(claim_id),
                clear_dirty=bool(clear_dirty),
            )
        visible_claim_id, statement, source_key = row
        search_text = " ".join(tokenize_sparse_text(str(statement)))
        if search_text:
            await self.db.execute(
                sql_text(
                    "INSERT INTO knowledge_claim_sparse(user_id, claim_id, source_key, search_text, statement) "
                    "VALUES (:user_id, :claim_id, :source_key, :search_text, :statement) "
                    "ON CONFLICT(claim_id) DO UPDATE SET user_id = excluded.user_id, "
                    "source_key = excluded.source_key, search_text = excluded.search_text, "
                    "statement = excluded.statement"
                ),
                {
                    "user_id": int(user_id),
                    "claim_id": int(visible_claim_id),
                    "source_key": str(source_key),
                    "search_text": search_text,
                    "statement": str(statement),
                },
            )
        else:
            await self.db.execute(
                sql_text(
                    "DELETE FROM knowledge_claim_sparse WHERE user_id = :user_id AND claim_id = :claim_id"
                ),
                {"user_id": int(user_id), "claim_id": int(claim_id)},
            )
        if clear_dirty:
            await self._clear_claim_dirty(user_id=int(user_id), claim_id=int(claim_id))
        await self.db.flush()
        return {
            "backend": self.name,
            "user_id": int(user_id),
            "claim_id": int(claim_id),
            "upserted": bool(search_text),
        }

    async def delete_claim(self, *, user_id: int, claim_id: int, clear_dirty: bool = True) -> dict[str, Any]:
        await self._ensure_supported()
        result = await self.db.execute(
            sql_text(
                "DELETE FROM knowledge_claim_sparse WHERE user_id = :user_id AND claim_id = :claim_id"
            ),
            {"user_id": int(user_id), "claim_id": int(claim_id)},
        )
        if clear_dirty:
            await self._clear_claim_dirty(user_id=int(user_id), claim_id=int(claim_id))
        await self.db.flush()
        return {
            "backend": self.name,
            "user_id": int(user_id),
            "claim_id": int(claim_id),
            "deleted_rows": int(result.rowcount or 0),
        }

    async def mark_claim_dirty(self, *, user_id: int, claim_id: int) -> None:
        await self._ensure_supported()
        await self.db.execute(
            sql_text(
                "INSERT INTO knowledge_sparse_dirty_claim(user_id, claim_id) "
                "VALUES (:user_id, :claim_id) ON CONFLICT(user_id, claim_id) DO NOTHING"
            ),
            {"user_id": int(user_id), "claim_id": int(claim_id)},
        )
        await self.db.flush()

    async def mark_user_dirty(self, *, user_id: int) -> None:
        await self._ensure_supported()
        await self.db.execute(
            sql_text(
                "INSERT INTO knowledge_sparse_dirty(user_id) VALUES (:user_id) "
                "ON CONFLICT(user_id) DO NOTHING"
            ),
            {"user_id": int(user_id)},
        )
        await self.db.flush()

    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]:
        await self._ensure_supported()
        result = await self.db.execute(
            sql_text("DELETE FROM knowledge_claim_sparse WHERE user_id = :user_id AND source_key = :source_key"),
            {"user_id": int(user_id), "source_key": str(source_key)},
        )
        signature = await self._canonical_signature(user_id=int(user_id))
        await self._write_state(user_id=int(user_id), signature=signature)
        await self.db.flush()
        return {"backend": self.name, "user_id": int(user_id), "source_key": str(source_key), "deleted_rows": int(result.rowcount or 0)}

    async def health(self) -> dict[str, Any]:
        try:
            await self._ensure_supported()
        except Exception as exc:
            return {"ok": False, "backend": self.name, "persistent": True, "error": str(exc)}
        return {"ok": True, "backend": self.name, "persistent": True, "extension_required": False}


class AutoSparseKnowledgeIndex:
    """Dialect-selected persistent sparse index with query-time reference fallback.

    Projection writes still fail normally so the outbox can retry them. Only
    user-facing search is allowed to fall back, and it isolates primary errors
    inside a savepoint so a failed optional FTS query cannot poison the request
    transaction.
    """

    def __init__(self, db: AsyncSession, primary: SparseKnowledgeIndex) -> None:
        self.db = db
        self.primary = primary
        self.reference = ReferenceSparseKnowledgeIndex(db)
        self.name = f"auto_{getattr(primary, 'name', 'reference')}"

    async def search(self, *, user_id: int, text: str, top_k: int = 30) -> list[SparseKnowledgeHit]:
        try:
            async with self.db.begin_nested():
                return await self.primary.search(
                    user_id=int(user_id),
                    text=str(text),
                    top_k=int(top_k),
                )
        except Exception:
            return await self.reference.search(
                user_id=int(user_id),
                text=str(text),
                top_k=int(top_k),
            )

    async def rebuild_user(self, *, user_id: int) -> dict[str, Any]:
        return await self.primary.rebuild_user(user_id=int(user_id))

    async def upsert_claim(self, *, user_id: int, claim_id: int, clear_dirty: bool = True) -> dict[str, Any]:
        return await self.primary.upsert_claim(
            user_id=int(user_id),
            claim_id=int(claim_id),
            clear_dirty=bool(clear_dirty),
        )

    async def delete_claim(self, *, user_id: int, claim_id: int, clear_dirty: bool = True) -> dict[str, Any]:
        return await self.primary.delete_claim(
            user_id=int(user_id),
            claim_id=int(claim_id),
            clear_dirty=bool(clear_dirty),
        )

    async def delete_source(self, *, user_id: int, source_key: str) -> dict[str, Any]:
        return await self.primary.delete_source(
            user_id=int(user_id),
            source_key=str(source_key),
        )

    async def mark_claim_dirty(self, *, user_id: int, claim_id: int) -> None:
        await self.primary.mark_claim_dirty(
            user_id=int(user_id),
            claim_id=int(claim_id),
        )

    async def mark_user_dirty(self, *, user_id: int) -> None:
        await self.primary.mark_user_dirty(user_id=int(user_id))

    async def health(self) -> dict[str, Any]:
        primary = await self.primary.health()
        return {
            "ok": True,
            "backend": self.name,
            "persistent": bool(primary.get("persistent")),
            "primary": primary,
            "reference_fallback": True,
        }


async def mark_sparse_knowledge_dirty(
    db: AsyncSession,
    *,
    user_id: int,
    claim_id: int | None = None,
) -> bool:
    """Best-effort dirty marker isolated from the caller transaction.

    Persistent sparse projections are optional. A dialect/DDL failure must not
    leave the canonical write transaction aborted, so the marker runs inside a
    savepoint and rolls back only its own work on failure.
    """
    index = create_sparse_knowledge_index(db)
    if isinstance(index, ReferenceSparseKnowledgeIndex):
        return False
    try:
        async with db.begin_nested():
            if claim_id is None:
                await index.mark_user_dirty(user_id=int(user_id))
            else:
                await index.mark_claim_dirty(
                    user_id=int(user_id),
                    claim_id=int(claim_id),
                )
    except Exception:
        return False
    return True


def create_sparse_knowledge_index(db: AsyncSession) -> SparseKnowledgeIndex:
    backend = str(settings.KNOWLEDGE_SPARSE_BACKEND or "auto").strip().casefold()
    if backend == "sqlite_fts5":
        return SqliteFts5SparseKnowledgeIndex(db)
    if backend == "postgres_fts":
        return PostgresFtsSparseKnowledgeIndex(db)
    if backend == "auto":
        bind = db.get_bind()
        dialect = str(bind.dialect.name if bind is not None else "").casefold()
        if dialect == "sqlite":
            return AutoSparseKnowledgeIndex(db, SqliteFts5SparseKnowledgeIndex(db))
        if dialect == "postgresql":
            return AutoSparseKnowledgeIndex(db, PostgresFtsSparseKnowledgeIndex(db))
    return ReferenceSparseKnowledgeIndex(db)
