"""Mutation boundary for user-owned ClaimRelation rows."""
from __future__ import annotations

from sqlalchemy import exists, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.knowledge import (
    Claim,
    ClaimEvidence,
    ClaimRelation,
    KnowledgeSource,
    KnowledgeSourceRevision,
)
from app.utils.utc import utc_now_db


RELATION_TYPES = frozenset({"supports", "contradicts", "refines", "exemplifies", "analogous_to"})
DERIVATION_TYPES = frozenset({"explicit", "inferred", "manual", "migration"})


async def create_claim_relation(
    db: AsyncSession,
    *,
    user_id: int,
    from_claim_id: int,
    to_claim_id: int,
    relation_type: str,
    confidence: float,
    derivation_type: str = "manual",
    review_status: str | None = None,
    rationale: str = "",
    evidence_provenance: dict | None = None,
    model_version: str | None = None,
    evaluator_version: str | None = None,
) -> ClaimRelation:
    """Create or update a relation and flush; the caller owns commit."""
    user_id = int(user_id)
    left, right = int(from_claim_id), int(to_claim_id)
    if left == right:
        raise ValueError("ClaimRelation 不允许自环")
    relation_type = str(relation_type)
    derivation_type = str(derivation_type)
    if relation_type not in RELATION_TYPES or derivation_type not in DERIVATION_TYPES:
        raise ValueError("不支持的 ClaimRelation 类型")
    if relation_type == "analogous_to" and left > right:
        left, right = right, left
    claims = list((await db.scalars(
        select(Claim)
        .join(KnowledgeSourceRevision, KnowledgeSourceRevision.id == Claim.source_revision_id)
        .join(KnowledgeSource, KnowledgeSource.id == KnowledgeSourceRevision.knowledge_source_id)
        .where(
            Claim.user_id == user_id,
            Claim.id.in_((left, right)),
            Claim.lifecycle_status == "active",
            KnowledgeSourceRevision.user_id == user_id,
            KnowledgeSourceRevision.status == "current",
            KnowledgeSource.user_id == user_id,
            KnowledgeSource.status == "active",
            exists().where(ClaimEvidence.user_id == user_id, ClaimEvidence.claim_id == Claim.id),
        )
    )).all())
    if {int(row.id) for row in claims} != {left, right}:
        raise PermissionError("Claim 不存在、非 current/active、无证据或不属于当前用户")
    status = review_status or ("confirmed" if derivation_type == "manual" else "pending")
    if status not in {"pending", "confirmed", "rejected"}:
        raise ValueError("不支持的审核状态")
    row = await db.scalar(select(ClaimRelation).where(
        ClaimRelation.user_id == user_id,
        ClaimRelation.from_claim_id == left,
        ClaimRelation.to_claim_id == right,
        ClaimRelation.relation_type == relation_type,
    ))
    if row is None:
        row = ClaimRelation(user_id=user_id, from_claim_id=left, to_claim_id=right, relation_type=relation_type)
        db.add(row)
    row.confidence = max(0.0, min(1.0, float(confidence)))
    row.derivation_type = derivation_type
    row.review_status = status
    row.rationale = str(rationale or "")[:500]
    row.evidence_provenance = dict(evidence_provenance or {})
    row.model_version = model_version
    row.evaluator_version = evaluator_version
    if status == "confirmed":
        row.reviewed_at = utc_now_db()
    await db.flush()
    return row
