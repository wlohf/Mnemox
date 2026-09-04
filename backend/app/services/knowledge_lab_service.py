"""Read-only dogfooding views for the post-Stage-7 Knowledge Lab.

The lab is not a second knowledge model. It rehydrates one user-owned Material's
current canonical Source/Revision/Claim/Evidence/Concept state so the WebUI can
inspect real extraction quality before running Association or Knowledge Path.
"""
from __future__ import annotations

from collections import Counter, defaultdict
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import Concept
from app.models.knowledge import (
    Claim,
    ClaimConceptLink,
    ClaimEvidence,
    KnowledgeSource,
    KnowledgeSourceRevision,
    KnowledgeUnit,
)
from app.models.material import Material
from app.utils.utc import to_utc_iso


LAB_CLAIM_REVIEW_STATUSES = ("pending", "confirmed", "rejected")


async def material_claim_snapshot(
    db: AsyncSession,
    *,
    user_id: int,
    material_id: int,
    review_status: str = "all",
    limit: int = 200,
) -> dict[str, Any]:
    """Return a bounded owner-scoped inspection snapshot for one Material."""
    user_id = int(user_id)
    material_id = int(material_id)
    selected_status = str(review_status or "all").strip().lower()
    if selected_status != "all" and selected_status not in LAB_CLAIM_REVIEW_STATUSES:
        raise ValueError("unsupported claim review status")
    max_claims = max(1, min(500, int(limit)))

    material = await db.scalar(
        select(Material).where(
            Material.id == material_id,
            Material.user_id == user_id,
        )
    )
    if material is None:
        raise PermissionError("material_not_found")

    source = await db.scalar(
        select(KnowledgeSource).where(
            KnowledgeSource.user_id == user_id,
            KnowledgeSource.source_type == "material",
            KnowledgeSource.source_record_id == material_id,
            KnowledgeSource.status == "active",
        )
    )
    base: dict[str, Any] = {
        "material": {
            "id": int(material.id),
            "title": str(material.title),
            "file_type": str(material.file_type or ""),
        },
        "source": {
            "registered": source is not None,
            "source_id": int(source.id) if source is not None else None,
            "current_revision": int(source.current_revision) if source is not None else 0,
        },
        "counts": {status: 0 for status in LAB_CLAIM_REVIEW_STATUSES},
        "claims": [],
        "truncated": False,
    }
    base["counts"]["total"] = 0
    if source is None:
        return base

    revision = await db.scalar(
        select(KnowledgeSourceRevision).where(
            KnowledgeSourceRevision.user_id == user_id,
            KnowledgeSourceRevision.knowledge_source_id == int(source.id),
            KnowledgeSourceRevision.status == "current",
        )
    )
    if revision is None:
        return base
    base["source"].update(
        {
            "revision_id": int(revision.id),
            "revision": int(revision.revision),
            "title": str(revision.title_snapshot or source.title_snapshot or material.title),
        }
    )

    all_claims = list(
        (
            await db.scalars(
                select(Claim)
                .where(
                    Claim.user_id == user_id,
                    Claim.source_revision_id == int(revision.id),
                    Claim.lifecycle_status == "active",
                )
                .order_by(Claim.id.asc())
            )
        ).all()
    )
    status_counts = Counter(str(row.review_status) for row in all_claims)
    base["counts"] = {
        "total": len(all_claims),
        **{status: int(status_counts.get(status, 0)) for status in LAB_CLAIM_REVIEW_STATUSES},
    }
    filtered = (
        all_claims
        if selected_status == "all"
        else [row for row in all_claims if str(row.review_status) == selected_status]
    )
    base["truncated"] = len(filtered) > max_claims
    claims = filtered[:max_claims]
    claim_ids = tuple(int(row.id) for row in claims)
    if not claim_ids:
        return base

    evidence_rows = list(
        (
            await db.execute(
                select(ClaimEvidence, KnowledgeUnit)
                .join(KnowledgeUnit, KnowledgeUnit.id == ClaimEvidence.knowledge_unit_id)
                .where(
                    ClaimEvidence.user_id == user_id,
                    ClaimEvidence.claim_id.in_(claim_ids),
                    KnowledgeUnit.user_id == user_id,
                    KnowledgeUnit.source_revision_id == int(revision.id),
                )
                .order_by(
                    ClaimEvidence.claim_id.asc(),
                    ClaimEvidence.confidence.desc(),
                    ClaimEvidence.id.asc(),
                )
            )
        ).all()
    )
    evidence_by_claim: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for evidence, unit in evidence_rows:
        bucket = evidence_by_claim[int(evidence.claim_id)]
        if len(bucket) >= 3:
            continue
        bucket.append(
            {
                "id": int(evidence.id),
                "excerpt": str(evidence.excerpt),
                "confidence": round(float(evidence.confidence), 4),
                "grounding_method": str(evidence.grounding_method),
                "locator": dict(evidence.locator or {}),
                "unit": {
                    "id": int(unit.id),
                    "type": str(unit.unit_type),
                    "ordinal": int(unit.ordinal),
                },
            }
        )

    concept_rows = list(
        (
            await db.execute(
                select(ClaimConceptLink, Concept)
                .join(Concept, Concept.id == ClaimConceptLink.concept_id)
                .where(
                    ClaimConceptLink.user_id == user_id,
                    ClaimConceptLink.claim_id.in_(claim_ids),
                    Concept.user_id == user_id,
                )
                .order_by(
                    ClaimConceptLink.claim_id.asc(),
                    ClaimConceptLink.review_status.asc(),
                    ClaimConceptLink.confidence.desc(),
                    ClaimConceptLink.id.asc(),
                )
            )
        ).all()
    )
    concepts_by_claim: dict[int, list[dict[str, Any]]] = defaultdict(list)
    for link, concept in concept_rows:
        bucket = concepts_by_claim[int(link.claim_id)]
        if len(bucket) >= 12:
            continue
        bucket.append(
            {
                "link_id": int(link.id),
                "concept_id": int(concept.id),
                "name": str(concept.name),
                "relation_type": str(link.relation_type),
                "confidence": round(float(link.confidence), 4),
                "review_status": str(link.review_status),
            }
        )

    base["claims"] = [
        {
            "id": int(claim.id),
            "statement": str(claim.statement),
            "claim_kind": str(claim.claim_kind),
            "confidence": round(float(claim.confidence), 4),
            "derivation_type": str(claim.derivation_type),
            "review_status": str(claim.review_status),
            "reviewed_at": to_utc_iso(claim.reviewed_at) if claim.reviewed_at else None,
            "evidence": evidence_by_claim.get(int(claim.id), []),
            "concepts": concepts_by_claim.get(int(claim.id), []),
        }
        for claim in claims
    ]
    return base
