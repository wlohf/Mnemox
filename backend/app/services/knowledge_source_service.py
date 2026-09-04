"""Canonical source lifecycle plus Stage 2 durable extraction registration.

The service deliberately performs ``flush`` only.  HTTP routes, workers, and
domain orchestrators retain commit/rollback ownership.
"""
from __future__ import annotations

import hashlib
import re
from typing import Any, Sequence

from sqlalchemy import exists, select, update
from sqlalchemy.dialects.postgresql import insert as postgresql_insert
from sqlalchemy.dialects.sqlite import insert as sqlite_insert
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.knowledge import (
    Claim,
    ClaimEvidence,
    KnowledgeExtractionRun,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.material import Material
from app.models.note import Note
from app.services.knowledge_extraction_service import (
    claim_fingerprint,
    ensure_default_extraction_runs,
    normalize_claim_statement,
)
from app.utils.utc import utc_now_db


SOURCE_TYPES = frozenset({"material", "note"})
CLAIM_KINDS = frozenset(
    {"definition", "principle", "causal", "recommendation", "comparison", "observation"}
)
REVIEW_STATUSES = frozenset({"pending", "confirmed", "rejected"})


def _sha256(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _source_key(source_type: str, source_record_id: int) -> str:
    normalized_type = str(source_type).strip().lower()
    if normalized_type not in SOURCE_TYPES:
        raise ValueError("Knowledge V2 只接受 material 或 note 来源。")
    return f"{normalized_type}:{int(source_record_id)}"


def _unit_slices(content: str, source_type: str) -> list[tuple[int, int, str]]:
    """Create deterministic, bounded character slices with stable locators."""

    text = str(content or "")
    if not text.strip():
        return []
    max_unit = int(settings.KNOWLEDGE_EXTRACTION_MAX_UNIT_CHARS)
    if source_type == "note" and len(text) <= max_unit:
        return [(0, len(text), text)]

    # Existing RAG settings are token-oriented.  Two characters per configured
    # token is a conservative local approximation, bounded by the Stage 0 hard
    # limit.  Exact character offsets remain authoritative for Evidence.
    size = min(max_unit, max(512, int(settings.RAG_CHUNK_SIZE) * 2))
    overlap = min(max(0, int(settings.RAG_CHUNK_OVERLAP) * 2), size // 4)
    step = max(1, size - overlap)
    slices: list[tuple[int, int, str]] = []
    for start in range(0, len(text), step):
        end = min(len(text), start + size)
        chunk = text[start:end]
        if chunk.strip():
            slices.append((start, end, chunk))
        if end >= len(text):
            break
    return slices


async def _ensure_source(
    db: AsyncSession,
    *,
    user_id: int,
    source_type: str,
    source_record_id: int,
    title: str,
) -> KnowledgeSource:
    source_key = _source_key(source_type, source_record_id)
    values = {
        "user_id": int(user_id),
        "source_type": str(source_type),
        "source_record_id": int(source_record_id),
        "source_key": source_key,
        "title_snapshot": str(title or "")[:200],
        "status": "active",
        "current_revision": 0,
    }
    bind = db.get_bind()
    dialect_name = bind.dialect.name if bind is not None else ""
    if dialect_name == "postgresql":
        await db.execute(
            postgresql_insert(KnowledgeSource)
            .values(**values)
            .on_conflict_do_nothing(constraint="uq_knowledge_sources_user_record")
        )
    elif dialect_name == "sqlite":
        await db.execute(
            sqlite_insert(KnowledgeSource)
            .values(**values)
            .on_conflict_do_nothing(
                index_elements=["user_id", "source_type", "source_record_id"]
            )
        )
    else:
        existing = await db.scalar(
            select(KnowledgeSource).where(
                KnowledgeSource.user_id == int(user_id),
                KnowledgeSource.source_type == str(source_type),
                KnowledgeSource.source_record_id == int(source_record_id),
            )
        )
        if existing is None:
            db.add(KnowledgeSource(**values))
            await db.flush()

    source = await db.scalar(
        select(KnowledgeSource)
        .where(
            KnowledgeSource.user_id == int(user_id),
            KnowledgeSource.source_type == str(source_type),
            KnowledgeSource.source_record_id == int(source_record_id),
        )
        .with_for_update()
        .execution_options(populate_existing=True)
    )
    if source is None:
        raise RuntimeError("Knowledge Source 原子登记后无法读取。")
    if source.source_key != source_key:
        raise RuntimeError("Knowledge Source 稳定键冲突。")
    return source


async def sync_source_snapshot(
    db: AsyncSession,
    *,
    user_id: int,
    source_type: str,
    source_record_id: int,
    title: str,
    content: str,
) -> KnowledgeSourceRevision:
    """Register a new immutable revision only when source content or title changed."""

    source_type = str(source_type).strip().lower()
    source = await _ensure_source(
        db,
        user_id=int(user_id),
        source_type=source_type,
        source_record_id=int(source_record_id),
        title=title,
    )
    normalized_title = str(title or "")[:200]
    canonical_content = str(content or "")
    canonical_hash = _sha256(canonical_content)
    current = await db.scalar(
        select(KnowledgeSourceRevision)
        .where(
            KnowledgeSourceRevision.knowledge_source_id == int(source.id),
            KnowledgeSourceRevision.status == "current",
        )
        .with_for_update()
    )
    if (
        current is not None
        and source.status == "active"
        and current.content_hash == canonical_hash
        and current.title_snapshot == normalized_title
    ):
        await ensure_default_extraction_runs(
            db,
            user_id=int(user_id),
            source_revision_id=int(current.id),
        )
        return current

    now = utc_now_db()
    if current is not None:
        old_claim_ids = list(
            (
                await db.scalars(
                    select(Claim.id).where(
                        Claim.user_id == int(user_id),
                        Claim.source_revision_id == int(current.id),
                    )
                )
            ).all()
        )
        old_unit_ids = list(
            (
                await db.scalars(
                    select(KnowledgeUnit.id).where(
                        KnowledgeUnit.user_id == int(user_id),
                        KnowledgeUnit.source_revision_id == int(current.id),
                    )
                )
            ).all()
        )
        current.status = "superseded"
        current.superseded_at = now
        await db.execute(
            update(Claim)
            .where(
                Claim.user_id == int(user_id),
                Claim.source_revision_id == int(current.id),
                Claim.lifecycle_status == "active",
            )
            .values(lifecycle_status="superseded", updated_at=now)
        )
        await db.execute(
            update(KnowledgeExtractionRun)
            .where(
                KnowledgeExtractionRun.user_id == int(user_id),
                KnowledgeExtractionRun.source_revision_id == int(current.id),
                KnowledgeExtractionRun.status.in_(("queued", "running", "failed")),
            )
            .values(
                status="cancelled",
                locked_at=None,
                lease_owner=None,
                finished_at=now,
                last_error="Source revision was superseded.",
                updated_at=now,
            )
        )
        from app.services.knowledge_projection_service import (
            enqueue_knowledge_projection_delete,
        )

        for claim_id in old_claim_ids:
            await enqueue_knowledge_projection_delete(
                db,
                user_id=int(user_id),
                object_type="claim",
                object_id=int(claim_id),
            )
        old_unit_type = "note_unit" if source_type == "note" else "material_unit"
        for unit_id in old_unit_ids:
            await enqueue_knowledge_projection_delete(
                db,
                user_id=int(user_id),
                object_type=old_unit_type,
                object_id=int(unit_id),
            )

    next_revision = int(source.current_revision or 0) + 1
    source.title_snapshot = normalized_title
    source.status = "active"
    source.current_revision = next_revision
    source.deleted_at = None
    revision = KnowledgeSourceRevision(
        user_id=int(user_id),
        knowledge_source_id=int(source.id),
        revision=next_revision,
        content_hash=canonical_hash,
        title_snapshot=normalized_title,
        status="current",
    )
    db.add(revision)
    await db.flush()

    unit_type = "note_body" if source_type == "note" else "chunk"
    source_key = _source_key(source_type, source_record_id)
    new_units: list[KnowledgeUnit] = []
    for ordinal, (start, end, unit_text) in enumerate(_unit_slices(canonical_content, source_type)):
        unit = KnowledgeUnit(
            user_id=int(user_id),
            source_revision_id=int(revision.id),
            unit_type=unit_type,
            ordinal=ordinal,
            text=unit_text,
            text_hash=_sha256(unit_text),
            locator={
                "source_key": source_key,
                "revision": next_revision,
                "chunk": ordinal,
                "char_start": start,
                "char_end": end,
            },
        )
        db.add(unit)
        new_units.append(unit)
    await db.flush()
    from app.services.knowledge_projection_service import enqueue_knowledge_object_projection

    object_type = "note_unit" if source_type == "note" else "material_unit"
    for unit in new_units:
        await enqueue_knowledge_object_projection(
            db,
            user_id=int(user_id),
            object_type=object_type,
            object_id=int(unit.id),
        )
    await ensure_default_extraction_runs(
        db,
        user_id=int(user_id),
        source_revision_id=int(revision.id),
    )
    return revision


async def register_material_source(
    db: AsyncSession,
    *,
    user_id: int,
    material_id: int,
) -> KnowledgeSourceRevision:
    material = await db.scalar(
        select(Material).where(
            Material.id == int(material_id),
            Material.user_id == int(user_id),
        )
    )
    if material is None:
        raise PermissionError("资料不存在或不属于当前用户。")
    return await sync_source_snapshot(
        db,
        user_id=int(user_id),
        source_type="material",
        source_record_id=int(material.id),
        title=str(material.title or ""),
        content=str(material.content or ""),
    )


async def register_note_source(
    db: AsyncSession,
    *,
    user_id: int,
    note_id: int,
) -> KnowledgeSourceRevision:
    note = await db.scalar(
        select(Note).where(Note.id == int(note_id), Note.user_id == int(user_id))
    )
    if note is None:
        raise PermissionError("笔记不存在或不属于当前用户。")
    return await sync_source_snapshot(
        db,
        user_id=int(user_id),
        source_type="note",
        source_record_id=int(note.id),
        title=str(note.title or ""),
        content=str(note.content or ""),
    )


async def delete_source(
    db: AsyncSession,
    *,
    user_id: int,
    source_type: str,
    source_record_id: int,
) -> bool:
    """Make a source and every derived Claim invisible before domain deletion."""

    source = await db.scalar(
        select(KnowledgeSource)
        .where(
            KnowledgeSource.user_id == int(user_id),
            KnowledgeSource.source_type == str(source_type),
            KnowledgeSource.source_record_id == int(source_record_id),
        )
        .with_for_update()
    )
    if source is None:
        return False
    if source.status == "deleted":
        return True

    now = utc_now_db()
    source.status = "deleted"
    source.title_snapshot = ""
    source.deleted_at = now
    revision_ids = list(
        (
            await db.scalars(
                select(KnowledgeSourceRevision.id).where(
                    KnowledgeSourceRevision.knowledge_source_id == int(source.id)
                )
            )
        ).all()
    )
    if revision_ids:
        unit_rows = (
            await db.execute(
                select(KnowledgeUnit.id, KnowledgeSource.source_type)
                .join(
                    KnowledgeSourceRevision,
                    KnowledgeSourceRevision.id == KnowledgeUnit.source_revision_id,
                )
                .join(
                    KnowledgeSource,
                    KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id,
                )
                .where(
                    KnowledgeUnit.user_id == int(user_id),
                    KnowledgeUnit.source_revision_id.in_(revision_ids),
                )
            )
        ).all()
        await db.execute(
            update(KnowledgeSourceRevision)
            .where(KnowledgeSourceRevision.id.in_(revision_ids))
            .values(status="deleted", superseded_at=now)
        )
        await db.execute(
            update(KnowledgeExtractionRun)
            .where(
                KnowledgeExtractionRun.user_id == int(user_id),
                KnowledgeExtractionRun.source_revision_id.in_(revision_ids),
                KnowledgeExtractionRun.status.in_(("queued", "running", "failed")),
            )
            .values(
                status="cancelled",
                locked_at=None,
                lease_owner=None,
                finished_at=now,
                last_error="Source was deleted.",
                updated_at=now,
            )
        )
        await db.execute(
            update(Claim)
            .where(Claim.user_id == int(user_id), Claim.source_revision_id.in_(revision_ids))
            .values(statement="", lifecycle_status="deleted", updated_at=now)
        )
        await db.execute(
            update(KnowledgeUnit)
            .where(
                KnowledgeUnit.user_id == int(user_id),
                KnowledgeUnit.source_revision_id.in_(revision_ids),
            )
            .values(text="")
        )
        claim_ids = list(
            (
                await db.scalars(
                    select(Claim.id).where(
                        Claim.user_id == int(user_id),
                        Claim.source_revision_id.in_(revision_ids),
                    )
                )
            ).all()
        )
        if claim_ids:
            await db.execute(
                update(ClaimEvidence)
                .where(
                    ClaimEvidence.user_id == int(user_id),
                    ClaimEvidence.claim_id.in_(claim_ids),
                )
                .values(excerpt="")
            )
        from app.services.knowledge_projection_service import (
            enqueue_knowledge_projection_delete,
        )

        for claim_id in claim_ids:
            await enqueue_knowledge_projection_delete(
                db,
                user_id=int(user_id),
                object_type="claim",
                object_id=int(claim_id),
            )
        for unit_id, deleted_source_type in unit_rows:
            await enqueue_knowledge_projection_delete(
                db,
                user_id=int(user_id),
                object_type=(
                    "note_unit" if str(deleted_source_type) == "note" else "material_unit"
                ),
                object_id=int(unit_id),
            )
    await db.flush()
    return True


async def create_manual_claim(
    db: AsyncSession,
    *,
    user_id: int,
    source_revision_id: int,
    knowledge_unit_id: int,
    statement: str,
    excerpt: str | None = None,
    char_start: int | None = None,
    char_end: int | None = None,
    claim_kind: str = "observation",
    confidence: float = 1.0,
    locator: dict[str, Any] | None = None,
) -> Claim:
    """Create or confirm one manually grounded Claim without auto extraction."""

    cleaned_statement = re.sub(r"\s+", " ", str(statement or "")).strip()
    if not cleaned_statement:
        raise ValueError("Claim 内容不能为空。")
    max_claim_chars = min(500, int(settings.KNOWLEDGE_CLAIM_MAX_CHARS))
    if len(cleaned_statement) > max_claim_chars:
        raise ValueError("Claim 超过允许的最大长度。")
    normalized_kind = str(claim_kind).strip().lower()
    if normalized_kind not in CLAIM_KINDS:
        raise ValueError("不支持的 Claim 类型。")
    normalized_confidence = float(confidence)
    if not 0.0 <= normalized_confidence <= 1.0:
        raise ValueError("Claim 置信度必须在 0 到 1 之间。")

    revision = await db.scalar(
        select(KnowledgeSourceRevision)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
        .where(
            KnowledgeSourceRevision.id == int(source_revision_id),
            KnowledgeSourceRevision.user_id == int(user_id),
            KnowledgeSourceRevision.status == "current",
            KnowledgeSource.user_id == int(user_id),
            KnowledgeSource.status == "active",
        )
    )
    if revision is None:
        raise PermissionError("来源版本不存在、不可见或不属于当前用户。")
    unit = await db.scalar(
        select(KnowledgeUnit).where(
            KnowledgeUnit.id == int(knowledge_unit_id),
            KnowledgeUnit.user_id == int(user_id),
            KnowledgeUnit.source_revision_id == int(source_revision_id),
        )
    )
    if unit is None:
        raise PermissionError("Evidence Unit 不属于当前来源版本或当前用户。")

    unit_text = str(unit.text or "")
    evidence_text = str(excerpt or "")
    if char_start is None and evidence_text:
        located = unit_text.find(evidence_text)
        if located < 0:
            raise ValueError("Evidence 摘录无法在 Unit 原文中定位。")
        char_start = located
        char_end = located + len(evidence_text)
    elif char_start is not None:
        start = int(char_start)
        end = int(char_end) if char_end is not None else start + len(evidence_text)
        if start < 0 or end <= start or end > len(unit_text):
            raise ValueError("Evidence 字符范围无效。")
        actual = unit_text[start:end]
        if evidence_text and actual != evidence_text:
            raise ValueError("Evidence 摘录与 Unit 字符范围不一致。")
        evidence_text = actual
        char_start, char_end = start, end
    else:
        raise ValueError("手工 Claim 必须提供可定位的 Evidence。")
    if not evidence_text:
        raise ValueError("Evidence 摘录不能为空。")

    fingerprint = claim_fingerprint(cleaned_statement)
    claim = await db.scalar(
        select(Claim).where(
            Claim.source_revision_id == int(source_revision_id),
            Claim.fingerprint == fingerprint,
        )
    )
    now = utc_now_db()
    if claim is None:
        claim = Claim(
            user_id=int(user_id),
            source_revision_id=int(source_revision_id),
            statement=cleaned_statement,
            claim_kind=normalized_kind,
            fingerprint=fingerprint,
            confidence=normalized_confidence,
            derivation_type="manual",
            review_status="confirmed",
            lifecycle_status="active",
            schema_version=1,
            reviewed_at=now,
        )
        db.add(claim)
        await db.flush()
    elif int(claim.user_id) != int(user_id):
        raise PermissionError("Claim 不属于当前用户。")
    else:
        claim.statement = cleaned_statement
        claim.claim_kind = normalized_kind
        claim.confidence = normalized_confidence
        claim.derivation_type = "manual"
        claim.review_status = "confirmed"
        claim.lifecycle_status = "active"
        claim.reviewed_at = now

    existing_evidence = await db.scalar(
        select(ClaimEvidence).where(
            ClaimEvidence.claim_id == int(claim.id),
            ClaimEvidence.knowledge_unit_id == int(unit.id),
            ClaimEvidence.char_start == int(char_start),
            ClaimEvidence.char_end == int(char_end),
        )
    )
    if existing_evidence is None:
        unit_locator = dict(unit.locator or {})
        unit_locator.update(locator or {})
        db.add(
            ClaimEvidence(
                user_id=int(user_id),
                claim_id=int(claim.id),
                knowledge_unit_id=int(unit.id),
                excerpt=evidence_text,
                char_start=int(char_start),
                char_end=int(char_end),
                locator=unit_locator,
                grounding_method="manual",
                confidence=normalized_confidence,
            )
        )
    await db.flush()
    from app.services.knowledge_projection_service import enqueue_knowledge_object_projection

    await enqueue_knowledge_object_projection(
        db,
        user_id=int(user_id),
        object_type="claim",
        object_id=int(claim.id),
    )
    return claim


async def review_claim(
    db: AsyncSession,
    *,
    user_id: int,
    claim_id: int,
    review_status: str,
) -> Claim:
    normalized_status = str(review_status).strip().lower()
    if normalized_status not in REVIEW_STATUSES:
        raise ValueError("不支持的 Claim 审核状态。")
    claim = await db.scalar(
        select(Claim).where(Claim.id == int(claim_id), Claim.user_id == int(user_id))
    )
    if claim is None:
        raise PermissionError("Claim 不存在或不属于当前用户。")
    if claim.lifecycle_status != "active":
        raise ValueError("已失效的 Claim 不能重新审核。")
    if normalized_status == "confirmed":
        has_evidence = bool(
            await db.scalar(
                select(
                    exists().where(
                        ClaimEvidence.claim_id == int(claim.id),
                        ClaimEvidence.user_id == int(user_id),
                    )
                )
            )
        )
        if not has_evidence:
            raise ValueError("没有 Evidence 的 Claim 不能确认为可展示。")
    claim.review_status = normalized_status
    claim.reviewed_at = utc_now_db()
    await db.flush()
    from app.services.knowledge_projection_service import enqueue_knowledge_object_projection

    await enqueue_knowledge_object_projection(
        db,
        user_id=int(user_id),
        object_type="claim",
        object_id=int(claim.id),
    )
    return claim


async def list_visible_claims(
    db: AsyncSession,
    *,
    user_id: int,
    review_statuses: Sequence[str] = ("confirmed",),
) -> list[Claim]:
    statuses = tuple(str(value) for value in review_statuses if str(value) in REVIEW_STATUSES)
    if not statuses:
        return []
    result = await db.scalars(
        select(Claim)
        .join(
            KnowledgeSourceRevision,
            KnowledgeSourceRevision.id == Claim.source_revision_id,
        )
        .join(
            KnowledgeSource,
            KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id,
        )
        .where(
            Claim.user_id == int(user_id),
            Claim.lifecycle_status == "active",
            Claim.review_status.in_(statuses),
            KnowledgeSourceRevision.user_id == int(user_id),
            KnowledgeSourceRevision.status == "current",
            KnowledgeSource.user_id == int(user_id),
            KnowledgeSource.status == "active",
            exists().where(
                ClaimEvidence.claim_id == Claim.id,
                ClaimEvidence.user_id == int(user_id),
            ),
        )
        .order_by(Claim.updated_at.desc(), Claim.id.desc())
    )
    return list(result.all())
