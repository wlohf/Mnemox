"""Explainable learner-model service built on replayable evidence."""
from __future__ import annotations

import math
from collections import Counter, defaultdict
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import Concept, ConceptLink
from app.models.learner_model import LearnerEvidence, UserConceptState
from app.models.learning_event import LearningEvent
from app.services.learning_event_service import record_learning_event


LEARNER_MODEL_VERSION = "explainable-rules-v1"
EVIDENCE_PAYLOAD_VERSION = 1

DIRECT_EVIDENCE_TYPES = frozenset(
    {
        "answer",
        "recall",
        "explanation",
        "application",
        "hint_count",
        "review_result",
    }
)
INDIRECT_EVIDENCE_TYPES = frozenset(
    {
        "study_duration",
        "study_frequency",
        "repeated_question",
        "interruption",
        "recovery",
    }
)
LEGACY_EVIDENCE_TYPES = frozenset({"legacy_mastery"})
MANUAL_EVIDENCE_TYPES = frozenset({"manual_override"})

_EVIDENCE_CATEGORIES = {
    **{evidence_type: "direct" for evidence_type in DIRECT_EVIDENCE_TYPES},
    **{evidence_type: "indirect" for evidence_type in INDIRECT_EVIDENCE_TYPES},
    **{evidence_type: "legacy" for evidence_type in LEGACY_EVIDENCE_TYPES},
    **{evidence_type: "manual" for evidence_type in MANUAL_EVIDENCE_TYPES},
}
_DIRECT_WEIGHTS = {
    "answer": 1.0,
    "recall": 1.1,
    "explanation": 1.15,
    "application": 1.25,
    "hint_count": 0.75,
    "review_result": 1.0,
    "legacy_mastery": 0.35,
}
_HALF_LIFE_DAYS = 90.0


def _clamp(value: float, lower: float, upper: float) -> float:
    return max(lower, min(upper, float(value)))


def _naive_local(value: datetime | None = None) -> datetime:
    """Normalize timestamps to the application's naive local-time convention."""
    current = value or datetime.now()
    if current.tzinfo is None:
        return current
    return current.astimezone().replace(tzinfo=None)


def _parse_datetime(value: Any) -> datetime | None:
    if isinstance(value, datetime):
        return _naive_local(value)
    if not value:
        return None
    try:
        return _naive_local(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


def _to_iso(value: datetime | None) -> str | None:
    return value.isoformat() if value else None


def _evidence_to_dict(evidence: LearnerEvidence) -> dict[str, Any]:
    return {
        "id": evidence.id,
        "user_id": evidence.user_id,
        "concept_id": evidence.concept_id,
        "evidence_type": evidence.evidence_type,
        "evidence_category": evidence.evidence_category,
        "dimension": evidence.dimension,
        "score": float(evidence.score),
        "reliability": float(evidence.reliability),
        "source_event_id": evidence.source_event_id,
        "source_type": evidence.source_type,
        "source_id": evidence.source_id,
        "observed_at": _to_iso(evidence.observed_at),
        "model_version": evidence.model_version,
        "payload_version": evidence.payload_version,
        "payload": evidence.payload or {},
        "created_at": _to_iso(evidence.created_at),
    }


def _state_to_dict(state: UserConceptState) -> dict[str, Any]:
    return {
        "user_id": state.user_id,
        "concept_id": state.concept_id,
        "mastery_estimate": round(float(state.mastery_estimate), 4),
        "confidence": round(float(state.confidence), 4),
        "forgetting_risk": round(float(state.forgetting_risk), 4),
        "mastery_dimensions": state.mastery_dimensions or {},
        "common_error_type": state.common_error_type,
        "last_evidence_at": _to_iso(state.last_evidence_at),
        "last_reviewed_at": _to_iso(state.last_reviewed_at),
        "next_review_at": _to_iso(state.next_review_at),
        "manual_override": state.manual_override,
        "source_event_id": state.source_event_id,
        "reliability": round(float(state.reliability), 4),
        "model_version": state.model_version,
        "updated_at": _to_iso(state.updated_at),
        "explanation_summary": state.explanation_summary or {},
    }


async def _get_owned_concept(db: AsyncSession, user_id: int, concept_id: int) -> Concept:
    result = await db.execute(
        select(Concept).where(Concept.id == concept_id, Concept.user_id == user_id)
    )
    concept = result.scalar_one_or_none()
    if concept is None:
        raise LookupError("概念不存在")
    return concept


async def _validate_source_event(
    db: AsyncSession,
    user_id: int,
    source_event_id: int | None,
) -> None:
    if source_event_id is None:
        return
    event_id = await db.scalar(
        select(LearningEvent.id).where(
            LearningEvent.id == source_event_id,
            LearningEvent.user_id == user_id,
        )
    )
    if event_id is None:
        raise LookupError("来源学习事件不存在")


async def _lock_concept_projection(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
) -> None:
    """Serialize concurrent projections for one user/concept on PostgreSQL.

    Locking the stable concept row before reading evidence gives concurrent
    workers a fresh READ COMMITTED snapshot after the predecessor commits.
    SQLite ignores ``FOR UPDATE`` but still serializes the eventual write.
    """
    await db.scalar(
        select(Concept.id)
        .where(Concept.id == int(concept_id), Concept.user_id == int(user_id))
        .with_for_update()
    )


async def record_evidence(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
    evidence_type: str,
    *,
    score: float,
    reliability: float,
    source_event_id: int | None,
    source_type: str,
    source_id: str | int | None = None,
    dimension: str | None = None,
    observed_at: datetime | None = None,
    payload: dict[str, Any] | None = None,
    model_version: str = LEARNER_MODEL_VERSION,
    payload_version: int = EVIDENCE_PAYLOAD_VERSION,
) -> dict[str, Any]:
    """Append one immutable evidence row and update its derived concept state.

    Direct and indirect types are a closed contract. Non-legacy evidence must
    point at a user-owned ``LearningEvent`` so every state update is auditable.
    """
    clean_type = str(evidence_type or "").strip()
    category = _EVIDENCE_CATEGORIES.get(clean_type)
    if category is None:
        raise ValueError(f"不支持的学习证据类型: {clean_type}")
    normalized_score = float(score)
    normalized_reliability = float(reliability)
    if not 0.0 <= normalized_score <= 1.0:
        raise ValueError("score 必须位于 0 到 1 之间")
    if not 0.0 <= normalized_reliability <= 1.0:
        raise ValueError("reliability 必须位于 0 到 1 之间")
    clean_source_type = str(source_type or "").strip()[:40]
    if not clean_source_type:
        raise ValueError("source_type 不能为空")
    if category != "legacy" and source_event_id is None:
        raise ValueError("非 legacy 学习证据必须关联 source_event_id")

    await _get_owned_concept(db, int(user_id), int(concept_id))
    await _validate_source_event(db, int(user_id), source_event_id)
    await _lock_concept_projection(db, int(user_id), int(concept_id))

    if source_event_id is not None:
        existing = await db.scalar(
            select(LearnerEvidence).where(
                LearnerEvidence.user_id == user_id,
                LearnerEvidence.concept_id == concept_id,
                LearnerEvidence.evidence_type == clean_type,
                LearnerEvidence.source_event_id == source_event_id,
            )
        )
        if existing is not None:
            state = await recompute_concept_state(db, user_id, concept_id)
            return {"evidence": _evidence_to_dict(existing), "state": state, "created": False}

    evidence = LearnerEvidence(
        user_id=int(user_id),
        concept_id=int(concept_id),
        evidence_type=clean_type,
        evidence_category=category,
        dimension=(str(dimension).strip()[:40] if dimension else None),
        score=normalized_score,
        reliability=normalized_reliability,
        source_event_id=source_event_id,
        source_type=clean_source_type,
        source_id=(str(source_id).strip()[:160] if source_id is not None else None),
        observed_at=_naive_local(observed_at),
        model_version=str(model_version or LEARNER_MODEL_VERSION)[:50],
        payload_version=max(1, int(payload_version)),
        payload=dict(payload or {}),
    )
    db.add(evidence)
    await db.flush()
    await db.refresh(evidence)
    state = await recompute_concept_state(db, user_id, concept_id)
    return {"evidence": _evidence_to_dict(evidence), "state": state, "created": True}


async def get_concept_state(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
) -> dict[str, Any]:
    """Return the user-scoped derived state with a one-release legacy fallback."""
    concept = await _get_owned_concept(db, int(user_id), int(concept_id))
    state = await db.scalar(
        select(UserConceptState).where(
            UserConceptState.user_id == user_id,
            UserConceptState.concept_id == concept_id,
        )
    )
    if state is not None:
        # Risk and confidence include recency decay. Refresh the projection on
        # reads so an inactive learner does not retain yesterday's risk forever.
        return await recompute_concept_state(db, user_id, concept_id)

    has_evidence = await db.scalar(
        select(LearnerEvidence.id)
        .where(
            LearnerEvidence.user_id == user_id,
            LearnerEvidence.concept_id == concept_id,
        )
        .limit(1)
    )
    if has_evidence is not None:
        return await recompute_concept_state(db, user_id, concept_id)

    # Migration should normally have materialized a state. This fallback keeps
    # old local databases readable for one release without making new writes to
    # Concept.mastery or treating it as the normal authority.
    legacy_mastery = _clamp(float(concept.mastery or 0.0), 0.0, 100.0)
    return {
        "user_id": int(user_id),
        "concept_id": int(concept_id),
        "mastery_estimate": legacy_mastery,
        "confidence": 0.0,
        "forgetting_risk": 1.0,
        "mastery_dimensions": {},
        "common_error_type": None,
        "last_evidence_at": None,
        "last_reviewed_at": None,
        "next_review_at": None,
        "manual_override": None,
        "source_event_id": None,
        "reliability": 0.0,
        "model_version": "legacy-compatibility-read-v1",
        "updated_at": _to_iso(concept.updated_at),
        "explanation_summary": {
            "basis": "legacy_compatibility_read",
            "authoritative": False,
            "migration_required": True,
        },
    }


async def ensure_concept_state(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
) -> UserConceptState:
    """Create an explicit empty state for a newly created concept."""
    await _get_owned_concept(db, int(user_id), int(concept_id))
    state = await db.scalar(
        select(UserConceptState).where(
            UserConceptState.user_id == user_id,
            UserConceptState.concept_id == concept_id,
        )
    )
    if state is not None:
        return state
    state = UserConceptState(
        user_id=int(user_id),
        concept_id=int(concept_id),
        mastery_estimate=0.0,
        confidence=0.0,
        forgetting_risk=0.85,
        mastery_dimensions={},
        model_version=LEARNER_MODEL_VERSION,
        reliability=0.0,
        explanation_summary={
            "basis": "no_evidence",
            "authoritative": True,
            "direct_evidence_count": 0,
            "indirect_signal_count": 0,
        },
    )
    db.add(state)
    await db.flush()
    return state


def _indirect_adjustments(evidence: list[LearnerEvidence]) -> tuple[float, float, list[str]]:
    confidence_delta = 0.0
    risk_delta = 0.0
    effects: list[str] = []
    for item in evidence:
        intensity = float(item.score) * float(item.reliability)
        if item.evidence_type == "study_duration":
            confidence_delta += 0.03 * intensity
            risk_delta -= 0.04 * intensity
        elif item.evidence_type == "study_frequency":
            confidence_delta += 0.05 * intensity
            risk_delta -= 0.06 * intensity
        elif item.evidence_type == "repeated_question":
            confidence_delta -= 0.08 * intensity
            risk_delta += 0.10 * intensity
        elif item.evidence_type == "interruption":
            confidence_delta -= 0.05 * intensity
            risk_delta += 0.12 * intensity
        elif item.evidence_type == "recovery":
            confidence_delta += 0.02 * intensity
            risk_delta -= 0.08 * intensity
        effects.append(item.evidence_type)
    return confidence_delta, risk_delta, sorted(set(effects))


def _direct_quality_score(evidence: LearnerEvidence) -> float:
    """Convert each direct input to the common 'higher is better' scale."""
    raw_score = float(evidence.score)
    if evidence.evidence_type == "hint_count":
        # For hint_count, ``score`` is normalized hint dependence: 0 means no
        # hint and 1 means maximum dependence. Keep the raw input replayable
        # while making its mastery effect explicit and monotonic.
        return 1.0 - raw_score
    return raw_score


async def recompute_concept_state(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
    *,
    as_of: datetime | None = None,
    persist: bool | None = None,
) -> dict[str, Any]:
    """Rebuild one state solely from replayable evidence using transparent rules.

    An explicit ``as_of`` is a historical snapshot by default. It must not
    replace the current projection, which powers the concept overview.
    """
    await _get_owned_concept(db, int(user_id), int(concept_id))
    should_persist = as_of is None if persist is None else bool(persist)
    if should_persist:
        await _lock_concept_projection(db, int(user_id), int(concept_id))
    current_time = _naive_local(as_of)
    rows = (
        await db.execute(
            select(LearnerEvidence)
            .where(
                LearnerEvidence.user_id == user_id,
                LearnerEvidence.concept_id == concept_id,
                LearnerEvidence.observed_at <= current_time,
            )
            .order_by(LearnerEvidence.observed_at.asc(), LearnerEvidence.id.asc())
        )
    ).scalars().all()

    direct = [row for row in rows if row.evidence_category in {"direct", "legacy"}]
    indirect = [row for row in rows if row.evidence_category == "indirect"]
    manual = [row for row in rows if row.evidence_category == "manual"]

    weighted_score = 0.0
    total_weight = 0.0
    reliability_weight = 0.0
    dimensions: dict[str, list[float]] = defaultdict(lambda: [0.0, 0.0])
    type_counts: Counter[str] = Counter()
    for item in direct:
        age_days = max(0.0, (current_time - _naive_local(item.observed_at)).total_seconds() / 86400.0)
        recency_weight = 0.5 ** (age_days / _HALF_LIFE_DAYS)
        base_weight = _DIRECT_WEIGHTS[item.evidence_type]
        weight = base_weight * float(item.reliability) * recency_weight
        quality_score = _direct_quality_score(item)
        weighted_score += quality_score * weight
        total_weight += weight
        reliability_weight += float(item.reliability) * base_weight * recency_weight
        dimension_name = str(item.dimension or "overall")[:40]
        dimensions[dimension_name][0] += quality_score * weight
        dimensions[dimension_name][1] += weight
        type_counts[item.evidence_type] += 1

    mastery = (weighted_score / total_weight * 100.0) if total_weight else 0.0
    aggregate_reliability = (
        reliability_weight
        / sum(
            _DIRECT_WEIGHTS[item.evidence_type]
            * (0.5 ** (max(0.0, (current_time - _naive_local(item.observed_at)).total_seconds() / 86400.0) / _HALF_LIFE_DAYS))
            for item in direct
        )
        if direct
        else 0.0
    )
    confidence = 1.0 - math.exp(-total_weight / 1.75) if total_weight else 0.0

    latest_direct_at = max((_naive_local(item.observed_at) for item in direct), default=None)
    if latest_direct_at is None:
        forgetting_risk = 0.85
    else:
        age_days = max(0.0, (current_time - latest_direct_at).total_seconds() / 86400.0)
        forgetting_risk = 0.15 + min(0.70, age_days / 120.0) + (1.0 - mastery / 100.0) * 0.25

    confidence_delta, risk_delta, indirect_effects = _indirect_adjustments(indirect)
    confidence = _clamp(confidence + confidence_delta, 0.0, 1.0)
    forgetting_risk = _clamp(forgetting_risk + risk_delta, 0.0, 1.0)

    mastery_dimensions = {
        name: round(values[0] / values[1] * 100.0, 4)
        for name, values in dimensions.items()
        if values[1] > 0
    }
    common_error_type = None
    for item in reversed(direct):
        error_type = (item.payload or {}).get("error_type")
        if error_type and float(item.score) < 0.7:
            common_error_type = str(error_type)[:80]
            break

    reviews = [item for item in direct if item.evidence_type == "review_result"]
    latest_review = reviews[-1] if reviews else None
    next_review_at = _parse_datetime((latest_review.payload or {}).get("next_review_at")) if latest_review else None

    active_override: dict[str, Any] | None = None
    if manual:
        candidate = dict(manual[-1].payload or {})
        if candidate.get("active", True):
            active_override = candidate
            mastery = _clamp(float(candidate.get("mastery_estimate", mastery)), 0.0, 100.0)
            aggregate_reliability = 1.0
            if candidate.get("confidence") is not None:
                confidence = _clamp(float(candidate["confidence"]), 0.0, 1.0)
            if candidate.get("forgetting_risk") is not None:
                forgetting_risk = _clamp(float(candidate["forgetting_risk"]), 0.0, 1.0)

    latest = rows[-1] if rows else None
    latest_with_event = next((row for row in reversed(rows) if row.source_event_id is not None), None)
    explanation = {
        "basis": "direct_evidence" if direct else "no_direct_evidence",
        "direct_evidence_count": len(direct),
        "indirect_signal_count": len(indirect),
        "direct_types": dict(sorted(type_counts.items())),
        "indirect_effects": indirect_effects,
        "indirect_mastery_delta": 0.0,
        "legacy_evidence_count": type_counts.get("legacy_mastery", 0),
        "manual_override_active": active_override is not None,
        "rule": "reliability_weighted_score_with_90_day_decay",
        "score_semantics": "higher_is_better; hint_count is inverted from dependence",
    }
    state_model_version = LEARNER_MODEL_VERSION
    legacy_only = (
        bool(direct)
        and all(item.evidence_type == "legacy_mastery" for item in direct)
        and not indirect
        and not manual
    )
    if legacy_only:
        # Replaying a migrated legacy snapshot must reproduce its initial state
        # under the legacy model version. Once real evidence arrives, v1 rules
        # take over and the legacy input receives only its low configured weight.
        confidence = 0.35
        forgetting_risk = 0.5
        aggregate_reliability = 0.35
        mastery_dimensions = {}
        explanation = {
            "basis": "legacy Concept.mastery migration",
            "recomputable": "true",
        }
        state_model_version = "legacy-concept-mastery-v1"

    state = None
    if should_persist:
        state = await db.scalar(
            select(UserConceptState).where(
                UserConceptState.user_id == user_id,
                UserConceptState.concept_id == concept_id,
            )
        )
    if state is None:
        state = UserConceptState(
            user_id=int(user_id),
            concept_id=int(concept_id),
            model_version=LEARNER_MODEL_VERSION,
        )
        if should_persist:
            db.add(state)

    state.mastery_estimate = _clamp(mastery, 0.0, 100.0)
    state.confidence = confidence
    state.forgetting_risk = forgetting_risk
    state.mastery_dimensions = mastery_dimensions
    state.common_error_type = common_error_type
    state.last_evidence_at = _naive_local(latest.observed_at) if latest else None
    state.last_reviewed_at = _naive_local(latest_review.observed_at) if latest_review else None
    state.next_review_at = next_review_at
    state.manual_override = active_override
    state.source_event_id = latest_with_event.source_event_id if latest_with_event else None
    state.reliability = _clamp(aggregate_reliability, 0.0, 1.0)
    state.model_version = state_model_version
    state.explanation_summary = explanation
    state.updated_at = current_time
    if not should_persist:
        return _state_to_dict(state)
    await db.flush()
    await db.refresh(state)
    return _state_to_dict(state)


async def apply_manual_override(
    db: AsyncSession,
    user_id: int,
    concept_id: int,
    *,
    mastery_estimate: float | None,
    reason: str,
    confidence: float | None = None,
    forgetting_risk: float | None = None,
    occurred_at: datetime | None = None,
) -> dict[str, Any]:
    """Apply or clear a user correction as an event-backed, replayable input."""
    await _get_owned_concept(db, int(user_id), int(concept_id))
    clean_reason = str(reason or "").strip()
    if not clean_reason:
        raise ValueError("人工修正必须提供 reason")
    if mastery_estimate is not None and not 0.0 <= float(mastery_estimate) <= 100.0:
        raise ValueError("mastery_estimate 必须位于 0 到 100 之间")
    if confidence is not None and not 0.0 <= float(confidence) <= 1.0:
        raise ValueError("confidence 必须位于 0 到 1 之间")
    if forgetting_risk is not None and not 0.0 <= float(forgetting_risk) <= 1.0:
        raise ValueError("forgetting_risk 必须位于 0 到 1 之间")

    observed_at = _naive_local(occurred_at)
    override_payload = {
        "active": mastery_estimate is not None,
        "mastery_estimate": float(mastery_estimate) if mastery_estimate is not None else None,
        "confidence": float(confidence) if confidence is not None else None,
        "forgetting_risk": float(forgetting_risk) if forgetting_risk is not None else None,
        "reason": clean_reason[:500],
        "applied_at": observed_at.isoformat(),
    }
    event = await record_learning_event(
        db,
        int(user_id),
        "learner.manual_override",
        source="learner_model",
        payload={"concept_id": int(concept_id), **override_payload},
        occurred_at=observed_at,
        metadata={"model_version": LEARNER_MODEL_VERSION},
    )
    from app.models.learner_model import ProjectionOutbox
    from app.services.projection_outbox_service import process_outbox

    outbox_id = await db.scalar(
        select(ProjectionOutbox.id).where(
            ProjectionOutbox.user_id == int(user_id),
            ProjectionOutbox.source_event_id == int(event["id"]),
            ProjectionOutbox.concept_id == int(concept_id),
        )
    )
    if outbox_id is None:
        raise RuntimeError("人工修正事件未生成投影任务")
    projection = await process_outbox(
        db,
        user_id=int(user_id),
        outbox_ids=[int(outbox_id)],
    )
    if projection["processed"] != 1:
        raise RuntimeError("人工修正投影处理失败")
    evidence = await db.scalar(
        select(LearnerEvidence).where(
            LearnerEvidence.user_id == int(user_id),
            LearnerEvidence.concept_id == int(concept_id),
            LearnerEvidence.evidence_type == "manual_override",
            LearnerEvidence.source_event_id == int(event["id"]),
        )
    )
    if evidence is None:
        raise RuntimeError("人工修正投影未生成证据")
    return {
        "evidence": _evidence_to_dict(evidence),
        "state": await get_concept_state(db, int(user_id), int(concept_id)),
        "created": True,
    }


async def record_review_result_evidence(
    db: AsyncSession,
    user_id: int,
    *,
    target_type: str,
    target_id: int,
    quality: int,
    source_event_id: int,
    observed_at: datetime,
    next_review_at: datetime | None,
    concept_id: int | None = None,
    normalized_score: float | None = None,
) -> int:
    """Project one completed review event onto linked user-owned concepts."""
    if not 0 <= int(quality) <= 5:
        raise ValueError("quality 必须位于 0 到 5 之间")
    concept_ids = set(
        (
            await db.execute(
                select(ConceptLink.concept_id).where(
                    ConceptLink.user_id == user_id,
                    ConceptLink.target_type == str(target_type),
                    ConceptLink.target_id == int(target_id),
                )
            )
        ).scalars().all()
    )
    if concept_id is not None:
        owned_id = await db.scalar(
            select(Concept.id).where(Concept.id == int(concept_id), Concept.user_id == user_id)
        )
        if owned_id is not None:
            concept_ids.add(int(owned_id))

    evidence_score = float(normalized_score) if normalized_score is not None else int(quality) / 5.0
    evidence_score = _clamp(evidence_score, 0.0, 1.0)
    for linked_concept_id in sorted(concept_ids):
        await record_evidence(
            db,
            int(user_id),
            int(linked_concept_id),
            "review_result",
            score=evidence_score,
            reliability=0.9,
            source_event_id=int(source_event_id),
            source_type="review",
            source_id=f"{target_type}:{int(target_id)}",
            dimension="recall",
            observed_at=observed_at,
            payload={
                "quality": int(quality),
                "next_review_at": _to_iso(next_review_at),
                "scheduler_role": "timing_only",
            },
        )
    return len(concept_ids)
