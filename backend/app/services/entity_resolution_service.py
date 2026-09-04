"""Conservative Concept resolution for grounded extraction mentions."""
from __future__ import annotations

import hashlib
import logging
from difflib import SequenceMatcher
from typing import Any, Iterable

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.concept import Concept, ConceptAlias
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    EntityResolutionCandidate,
    KnowledgeExtractionRun,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.schemas.knowledge_extraction import ExtractedConceptMention
from app.services.concept_graph_service import add_concept_alias
from app.services.concept_service import normalize_concept_name, upsert_concept
from app.services.knowledge_embedding_service import (
    KnowledgeEmbeddingUnavailable,
    get_knowledge_embedding_index,
)
from app.services.knowledge_projection_service import enqueue_knowledge_object_projection
from app.utils.utc import to_utc_iso, utc_now_db


logger = logging.getLogger(__name__)


def _identity_hash(
    *,
    claim_id: int,
    mention_normalized: str,
    relation_type: str,
    candidate_concept_id: int | None,
) -> str:
    raw = (
        f"claim:{int(claim_id)}|mention:{mention_normalized}|relation:{relation_type}|"
        f"candidate:{int(candidate_concept_id) if candidate_concept_id is not None else 'new'}"
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


async def _ensure_candidate(
    db: AsyncSession,
    *,
    run: KnowledgeExtractionRun,
    unit: KnowledgeUnit,
    claim: Claim,
    mention: ExtractedConceptMention,
    candidate_concept_id: int | None,
    exact_score: float = 0.0,
    alias_score: float = 0.0,
    lexical_score: float = 0.0,
    vector_score: float = 0.0,
    context_score: float = 0.0,
    combined_score: float = 0.0,
    decision: str = "pending",
    decided_by: str | None = None,
    resolved_concept_id: int | None = None,
) -> EntityResolutionCandidate:
    normalized = normalize_concept_name(mention.text)
    identity = _identity_hash(
        claim_id=int(claim.id),
        mention_normalized=normalized,
        relation_type=str(mention.relation_type),
        candidate_concept_id=candidate_concept_id,
    )
    row = await db.scalar(
        select(EntityResolutionCandidate).where(
            EntityResolutionCandidate.user_id == int(run.user_id),
            EntityResolutionCandidate.identity_hash == identity,
        )
    )
    now = utc_now_db()
    if row is None:
        row = EntityResolutionCandidate(
            user_id=int(run.user_id),
            extraction_run_id=int(run.id),
            knowledge_unit_id=int(unit.id),
            claim_id=int(claim.id),
            mention_text=str(mention.text)[:120],
            mention_normalized=normalized,
            mention_context=str(claim.statement or "")[:500],
            relation_type=str(mention.relation_type),
            candidate_concept_id=(
                int(candidate_concept_id) if candidate_concept_id is not None else None
            ),
            exact_score=max(0.0, min(1.0, float(exact_score))),
            alias_score=max(0.0, min(1.0, float(alias_score))),
            lexical_score=max(0.0, min(1.0, float(lexical_score))),
            vector_score=max(0.0, min(1.0, float(vector_score))),
            context_score=max(0.0, min(1.0, float(context_score))),
            combined_score=max(0.0, min(1.0, float(combined_score))),
            decision=str(decision),
            resolved_concept_id=(
                int(resolved_concept_id) if resolved_concept_id is not None else None
            ),
            decided_by=decided_by,
            decided_at=(now if decided_by else None),
            identity_hash=identity,
        )
        db.add(row)
        await db.flush()
    elif row.decision == "pending" and decision != "pending":
        row.decision = str(decision)
        row.resolved_concept_id = (
            int(resolved_concept_id) if resolved_concept_id is not None else None
        )
        row.decided_by = decided_by
        row.decided_at = now if decided_by else None
        row.exact_score = max(float(row.exact_score or 0.0), float(exact_score))
        row.alias_score = max(float(row.alias_score or 0.0), float(alias_score))
        row.combined_score = max(float(row.combined_score or 0.0), float(combined_score))
    return row


async def _ensure_link(
    db: AsyncSession,
    *,
    user_id: int,
    claim: Claim,
    concept: Concept,
    mention: ExtractedConceptMention,
    derivation_type: str,
    confidence: float,
    candidate_id: int | None,
) -> ClaimConceptLink:
    if int(claim.user_id) != int(user_id) or int(concept.user_id) != int(user_id):
        raise PermissionError("Claim 与 Concept 必须属于同一用户。")
    row = await db.scalar(
        select(ClaimConceptLink).where(
            ClaimConceptLink.user_id == int(user_id),
            ClaimConceptLink.claim_id == int(claim.id),
            ClaimConceptLink.concept_id == int(concept.id),
            ClaimConceptLink.relation_type == str(mention.relation_type),
        )
    )
    if row is None:
        row = ClaimConceptLink(
            user_id=int(user_id),
            claim_id=int(claim.id),
            concept_id=int(concept.id),
            relation_type=str(mention.relation_type),
            mention_text=str(mention.text)[:120],
            confidence=max(0.0, min(1.0, float(confidence))),
            derivation_type=str(derivation_type),
            review_status="confirmed",
            resolution_candidate_id=(int(candidate_id) if candidate_id is not None else None),
        )
        db.add(row)
        await db.flush()
    else:
        row.confidence = max(float(row.confidence or 0.0), float(confidence))
        row.review_status = "confirmed"
        row.mention_text = str(mention.text)[:120]
        row.derivation_type = str(derivation_type)
        if candidate_id is not None:
            row.resolution_candidate_id = int(candidate_id)
    return row


async def _reject_siblings(
    db: AsyncSession,
    *,
    candidate: EntityResolutionCandidate,
    except_id: int | None,
) -> None:
    siblings = list(
        (
            await db.scalars(
                select(EntityResolutionCandidate).where(
                    EntityResolutionCandidate.user_id == int(candidate.user_id),
                    EntityResolutionCandidate.claim_id == int(candidate.claim_id),
                    EntityResolutionCandidate.mention_normalized
                    == str(candidate.mention_normalized),
                    EntityResolutionCandidate.relation_type == str(candidate.relation_type),
                    EntityResolutionCandidate.decision == "pending",
                )
            )
        ).all()
    )
    now = utc_now_db()
    for sibling in siblings:
        if except_id is not None and int(sibling.id) == int(except_id):
            continue
        sibling.decision = "rejected"
        sibling.decided_by = candidate.decided_by or "rule"
        sibling.decided_at = now


async def _same_source_user_mapping(
    db: AsyncSession,
    *,
    user_id: int,
    source_revision_id: int,
    mention_normalized: str,
    relation_type: str,
) -> Concept | None:
    source_id = await db.scalar(
        select(KnowledgeSourceRevision.knowledge_source_id).where(
            KnowledgeSourceRevision.id == int(source_revision_id),
            KnowledgeSourceRevision.user_id == int(user_id),
        )
    )
    if source_id is None:
        return None
    return await db.scalar(
        select(Concept)
        .join(
            EntityResolutionCandidate,
            EntityResolutionCandidate.resolved_concept_id == Concept.id,
        )
        .join(Claim, Claim.id == EntityResolutionCandidate.claim_id)
        .join(
            KnowledgeSourceRevision,
            KnowledgeSourceRevision.id == Claim.source_revision_id,
        )
        .where(
            EntityResolutionCandidate.user_id == int(user_id),
            EntityResolutionCandidate.mention_normalized == str(mention_normalized),
            EntityResolutionCandidate.relation_type == str(relation_type),
            EntityResolutionCandidate.decision.in_(("accepted", "create_new")),
            EntityResolutionCandidate.decided_by == "user",
            Claim.user_id == int(user_id),
            KnowledgeSourceRevision.user_id == int(user_id),
            KnowledgeSourceRevision.knowledge_source_id == int(source_id),
            Concept.user_id == int(user_id),
            Concept.review_status == "confirmed",
        )
        .order_by(
            EntityResolutionCandidate.decided_at.desc(),
            EntityResolutionCandidate.id.desc(),
        )
        .limit(1)
    )


async def resolve_claim_mentions(
    db: AsyncSession,
    *,
    run: KnowledgeExtractionRun,
    unit: KnowledgeUnit,
    claim: Claim,
    mentions: Iterable[ExtractedConceptMention],
    embedding_index: Any | None = None,
) -> dict[str, int]:
    """Resolve exact identities and persist review-only semantic alternatives."""

    stats = {"mentions": 0, "exact": 0, "alias": 0, "reused": 0, "pending": 0}
    seen: set[tuple[str, str]] = set()
    for mention in list(mentions)[: int(settings.KNOWLEDGE_RESOLUTION_MAX_MENTIONS_PER_CLAIM)]:
        normalized = normalize_concept_name(mention.text)
        identity = (normalized, str(mention.relation_type))
        if len(normalized) < 2 or identity in seen:
            continue
        seen.add(identity)
        stats["mentions"] += 1
        concept = await db.scalar(
            select(Concept).where(
                Concept.user_id == int(run.user_id),
                Concept.name_normalized == normalized,
                Concept.review_status == "confirmed",
            )
        )
        derivation = "canonical_exact"
        if concept is None:
            concept = await db.scalar(
                select(Concept)
                .join(ConceptAlias, ConceptAlias.concept_id == Concept.id)
                .where(
                    Concept.user_id == int(run.user_id),
                    Concept.review_status == "confirmed",
                    ConceptAlias.user_id == int(run.user_id),
                    ConceptAlias.alias_normalized == normalized,
                )
            )
            derivation = "alias_exact"
        if concept is None:
            concept = await _same_source_user_mapping(
                db,
                user_id=int(run.user_id),
                source_revision_id=int(run.source_revision_id),
                mention_normalized=normalized,
                relation_type=str(mention.relation_type),
            )
            derivation = "user"
        if concept is not None:
            candidate = await _ensure_candidate(
                db,
                run=run,
                unit=unit,
                claim=claim,
                mention=mention,
                candidate_concept_id=int(concept.id),
                exact_score=(1.0 if derivation == "canonical_exact" else 0.0),
                alias_score=(1.0 if derivation == "alias_exact" else 0.0),
                combined_score=1.0,
                decision="accepted",
                decided_by="rule",
                resolved_concept_id=int(concept.id),
            )
            await _ensure_link(
                db,
                user_id=int(run.user_id),
                claim=claim,
                concept=concept,
                mention=mention,
                derivation_type=derivation,
                confidence=1.0,
                candidate_id=int(candidate.id),
            )
            await _reject_siblings(db, candidate=candidate, except_id=int(candidate.id))
            if derivation == "canonical_exact":
                stats["exact"] += 1
            elif derivation == "alias_exact":
                stats["alias"] += 1
            else:
                stats["reused"] += 1
            continue

        confirmed = list(
            (
                await db.scalars(
                    select(Concept).where(
                        Concept.user_id == int(run.user_id),
                        Concept.review_status == "confirmed",
                    )
                )
            ).all()
        )
        lexical_scores = {
            int(item.id): SequenceMatcher(
                None,
                normalized,
                str(item.name_normalized),
            ).ratio()
            for item in confirmed
        }
        vector_scores: dict[int, float] = {}
        if settings.KNOWLEDGE_EMBEDDING_ENABLED:
            try:
                rows = await (embedding_index or get_knowledge_embedding_index()).query_concepts(
                    user_id=int(run.user_id),
                    text=f"{mention.text}\n{claim.statement}",
                    top_k=int(settings.KNOWLEDGE_RESOLUTION_TOP_K),
                )
                vector_scores = {
                    int(item["concept_id"]): max(0.0, min(1.0, float(item["score"])))
                    for item in rows
                }
            except (KnowledgeEmbeddingUnavailable, TimeoutError, ValueError, RuntimeError):
                vector_scores = {}
            except Exception as exc:
                # Candidate review and exact resolution remain available when
                # Chroma or a provider fails. Do not make extraction partial.
                logger.warning(
                    "knowledge semantic resolution unavailable; exact review path remains active: %s",
                    type(exc).__name__,
                )
                vector_scores = {}
        candidate_ids = sorted(
            set(vector_scores)
            | {
                concept_id
                for concept_id, score in lexical_scores.items()
                if score >= float(settings.KNOWLEDGE_RESOLUTION_LEXICAL_THRESHOLD)
            },
            key=lambda concept_id: (
                -vector_scores.get(concept_id, 0.0),
                -lexical_scores.get(concept_id, 0.0),
                concept_id,
            ),
        )[: int(settings.KNOWLEDGE_RESOLUTION_TOP_K)]
        owned_confirmed_ids = {int(item.id) for item in confirmed}
        candidate_ids = [
            concept_id for concept_id in candidate_ids if concept_id in owned_confirmed_ids
        ]
        hydrated = {
            int(item.id): item
            for item in confirmed
            if int(item.id) in set(candidate_ids)
        }
        for concept_id in candidate_ids:
            if concept_id not in hydrated:
                continue
            vector_score = vector_scores.get(concept_id, 0.0)
            lexical_score = lexical_scores.get(concept_id, 0.0)
            combined = min(1.0, 0.72 * vector_score + 0.28 * lexical_score)
            await _ensure_candidate(
                db,
                run=run,
                unit=unit,
                claim=claim,
                mention=mention,
                candidate_concept_id=concept_id,
                lexical_score=lexical_score,
                vector_score=vector_score,
                context_score=0.0,
                combined_score=combined,
            )
            stats["pending"] += 1
        if not candidate_ids:
            await _ensure_candidate(
                db,
                run=run,
                unit=unit,
                claim=claim,
                mention=mention,
                candidate_concept_id=None,
            )
            stats["pending"] += 1
    await db.flush()
    return stats


def serialize_resolution_candidate(
    row: EntityResolutionCandidate,
    *,
    concept: Concept | None = None,
    claim: Claim | None = None,
    unit: KnowledgeUnit | None = None,
    source: KnowledgeSource | None = None,
) -> dict[str, Any]:
    return {
        "id": int(row.id),
        "claim_id": int(row.claim_id),
        "knowledge_unit_id": int(row.knowledge_unit_id),
        "mention_text": row.mention_text,
        "mention_normalized": row.mention_normalized,
        "mention_context": row.mention_context,
        "relation_type": row.relation_type,
        "candidate_concept_id": (
            int(row.candidate_concept_id) if row.candidate_concept_id is not None else None
        ),
        "candidate_concept_name": concept.name if concept is not None else None,
        "scores": {
            "exact": float(row.exact_score),
            "alias": float(row.alias_score),
            "lexical": float(row.lexical_score),
            "vector": float(row.vector_score),
            "context": float(row.context_score),
            "combined": float(row.combined_score),
        },
        "decision": row.decision,
        "resolved_concept_id": (
            int(row.resolved_concept_id) if row.resolved_concept_id is not None else None
        ),
        "decided_by": row.decided_by,
        "decided_at": to_utc_iso(row.decided_at) if row.decided_at else None,
        "claim_statement": claim.statement if claim is not None else None,
        "evidence_excerpt": str(unit.text or "")[:500] if unit is not None else None,
        "source_type": source.source_type if source is not None else None,
        "source_id": int(source.source_record_id) if source is not None else None,
        "source_title": source.title_snapshot if source is not None else None,
        "created_at": to_utc_iso(row.created_at) if row.created_at else None,
    }


async def list_resolution_candidates(
    db: AsyncSession,
    *,
    user_id: int,
    decision: str = "pending",
    limit: int = 100,
    source_type: str | None = None,
    source_id: int | None = None,
) -> list[dict[str, Any]]:
    query = (
        select(
            EntityResolutionCandidate,
            Concept,
            Claim,
            KnowledgeUnit,
            KnowledgeSource,
        )
        .outerjoin(
            Concept,
            and_(
                Concept.id == EntityResolutionCandidate.candidate_concept_id,
                Concept.user_id == int(user_id),
            ),
        )
        .join(Claim, Claim.id == EntityResolutionCandidate.claim_id)
        .join(KnowledgeUnit, KnowledgeUnit.id == EntityResolutionCandidate.knowledge_unit_id)
        .join(
            KnowledgeSourceRevision,
            KnowledgeSourceRevision.id == Claim.source_revision_id,
        )
        .join(
            KnowledgeSource,
            KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id,
        )
        .where(
            EntityResolutionCandidate.user_id == int(user_id),
            Claim.user_id == int(user_id),
            Claim.lifecycle_status == "active",
            KnowledgeUnit.user_id == int(user_id),
            KnowledgeSourceRevision.user_id == int(user_id),
            KnowledgeSourceRevision.status == "current",
            KnowledgeSource.user_id == int(user_id),
            KnowledgeSource.status == "active",
        )
    )
    if decision != "all":
        query = query.where(EntityResolutionCandidate.decision == str(decision))
    if source_type is not None:
        query = query.where(KnowledgeSource.source_type == str(source_type))
    if source_id is not None:
        query = query.where(KnowledgeSource.source_record_id == int(source_id))
    rows = (
        await db.execute(
            query.order_by(
                EntityResolutionCandidate.created_at.desc(),
                EntityResolutionCandidate.combined_score.desc(),
                EntityResolutionCandidate.id.desc(),
            ).limit(max(1, min(500, int(limit))))
        )
    ).all()
    return [
        serialize_resolution_candidate(
            candidate,
            concept=concept,
            claim=claim,
            unit=unit,
            source=source,
        )
        for candidate, concept, claim, unit, source in rows
    ]


async def resolve_candidate(
    db: AsyncSession,
    *,
    user_id: int,
    candidate_id: int,
    action: str,
    concept_id: int | None = None,
    concept_name: str | None = None,
) -> dict[str, Any]:
    candidate = await db.scalar(
        select(EntityResolutionCandidate)
        .where(
            EntityResolutionCandidate.id == int(candidate_id),
            EntityResolutionCandidate.user_id == int(user_id),
        )
        .with_for_update()
    )
    if candidate is None:
        raise PermissionError("解析候选不存在或不属于当前用户。")
    normalized_action = str(action).strip().lower()
    if normalized_action not in {"link", "link_add_alias", "create_new", "reject"}:
        raise ValueError("不支持的解析操作。")
    claim = await db.scalar(
        select(Claim).where(
            Claim.id == int(candidate.claim_id),
            Claim.user_id == int(user_id),
            Claim.lifecycle_status == "active",
        )
    )
    if claim is None:
        raise ValueError("候选所属 Claim 已失效。")
    if candidate.decision != "pending":
        return serialize_resolution_candidate(candidate, claim=claim)
    now = utc_now_db()
    if normalized_action == "reject":
        candidate.decision = "rejected"
        candidate.decided_by = "user"
        candidate.decided_at = now
        await _reject_siblings(db, candidate=candidate, except_id=None)
        await db.flush()
        return serialize_resolution_candidate(candidate, claim=claim)

    if normalized_action == "create_new":
        clean_name = str(concept_name or candidate.mention_text).strip()
        concept = await upsert_concept(
            db,
            int(user_id),
            clean_name,
            source="entity_resolution",
            review_status="confirmed",
        )
        if concept is None:
            raise ValueError("新概念名称无效。")
        decision = "create_new"
    else:
        target_id = int(concept_id or candidate.candidate_concept_id or 0)
        concept = await db.scalar(
            select(Concept).where(
                Concept.id == target_id,
                Concept.user_id == int(user_id),
                Concept.review_status == "confirmed",
            )
        )
        if concept is None:
            raise ValueError("目标概念不存在、未确认或不属于当前用户。")
        if normalized_action == "link_add_alias":
            await add_concept_alias(
                db,
                int(user_id),
                int(concept.id),
                candidate.mention_text,
                source="entity_resolution",
            )
        decision = "accepted"
    mention = ExtractedConceptMention(
        text=candidate.mention_text,
        relation_type=candidate.relation_type,
    )
    candidate.decision = decision
    candidate.resolved_concept_id = int(concept.id)
    candidate.decided_by = "user"
    candidate.decided_at = now
    await _ensure_link(
        db,
        user_id=int(user_id),
        claim=claim,
        concept=concept,
        mention=mention,
        derivation_type="user",
        confidence=1.0,
        candidate_id=int(candidate.id),
    )
    await _reject_siblings(db, candidate=candidate, except_id=int(candidate.id))
    await enqueue_knowledge_object_projection(
        db,
        user_id=int(user_id),
        object_type="concept",
        object_id=int(concept.id),
    )
    await db.flush()
    return serialize_resolution_candidate(candidate, concept=concept, claim=claim)


async def pending_resolution_count(db: AsyncSession, *, user_id: int) -> int:
    return int(
        await db.scalar(
            select(func.count(EntityResolutionCandidate.id))
            .join(Claim, Claim.id == EntityResolutionCandidate.claim_id)
            .join(
                KnowledgeSourceRevision,
                KnowledgeSourceRevision.id == Claim.source_revision_id,
            )
            .join(
                KnowledgeSource,
                KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id,
            )
            .where(
                EntityResolutionCandidate.user_id == int(user_id),
                EntityResolutionCandidate.decision == "pending",
                Claim.user_id == int(user_id),
                Claim.lifecycle_status == "active",
                KnowledgeSourceRevision.user_id == int(user_id),
                KnowledgeSourceRevision.status == "current",
                KnowledgeSource.user_id == int(user_id),
                KnowledgeSource.status == "active",
            )
        )
        or 0
    )
