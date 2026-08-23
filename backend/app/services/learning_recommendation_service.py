"""Explainable, read-only learning decisions from canonical SQL evidence."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.concept import Concept, ConceptEdge, ConceptLink
from app.models.goal import Goal
from app.models.learner_model import LearnerEvidence, UserConceptState
from app.models.material import Chapter
from app.models.question import ReviewSchedule
from app.services.concept_graph_service import get_prerequisite_gaps


RECOMMENDATION_MODEL_VERSION = "explainable-learning-rules-v1"


def _local_now(value: datetime | None = None) -> datetime:
    value = value or datetime.now()
    return value.astimezone().replace(tzinfo=None) if value.tzinfo else value


def _goal_urgency(goal: Goal | None, now: datetime) -> float:
    if goal is None or goal.deadline is None:
        return 0.0
    remaining_days = (goal.deadline - now.date()).days
    if remaining_days <= 0:
        return 1.0
    return round(max(0.0, min(1.0, 1.0 - remaining_days / 30.0)), 4)


def _score(
    *,
    forgetting_risk: float,
    goal_relevance: float,
    prerequisite_blockage: float,
    error_frequency: float,
    urgency: float,
    recent_fatigue: float,
) -> tuple[float, dict[str, float]]:
    components = {
        "forgetting_risk": round(max(0.0, min(1.0, forgetting_risk)) * 0.28, 4),
        "goal_relevance": round(max(0.0, min(1.0, goal_relevance)) * 0.20, 4),
        "prerequisite_blockage": round(max(0.0, min(1.0, prerequisite_blockage)) * 0.24, 4),
        "error_frequency": round(max(0.0, min(1.0, error_frequency)) * 0.16, 4),
        "urgency": round(max(0.0, min(1.0, urgency)) * 0.12, 4),
        "recent_fatigue": round(-max(0.0, min(1.0, recent_fatigue)) * 0.12, 4),
    }
    return round(sum(components.values()), 4), components


async def list_learning_recommendations(
    db: AsyncSession,
    user_id: int,
    *,
    limit: int = 10,
    as_of: datetime | None = None,
) -> dict[str, Any]:
    """Rank confirmed concepts without modifying goals, plans, or user state."""
    now = _local_now(as_of)
    concept_rows = (
        await db.execute(
            select(Concept, UserConceptState)
            .outerjoin(
                UserConceptState,
                (UserConceptState.user_id == int(user_id)) & (UserConceptState.concept_id == Concept.id),
            )
            .where(Concept.user_id == int(user_id), Concept.review_status == "confirmed")
            .order_by(Concept.id.asc())
        )
    ).all()
    if not concept_rows:
        return {
            "items": [], "total": 0, "generated_at": now.isoformat(),
            "model_version": RECOMMENDATION_MODEL_VERSION,
        }

    concepts = {int(concept.id): concept for concept, _ in concept_rows}
    states = {int(concept.id): state for concept, state in concept_rows}
    concept_ids = set(concepts)
    links = (
        await db.execute(
            select(ConceptLink).where(
                ConceptLink.user_id == int(user_id), ConceptLink.concept_id.in_(concept_ids),
            )
        )
    ).scalars().all()
    links_by_concept: dict[int, list[ConceptLink]] = defaultdict(list)
    for row in links:
        links_by_concept[int(row.concept_id)].append(row)

    chapter_ids = {int(row.target_id) for row in links if row.target_type == "chapter"}
    chapters: dict[int, Chapter] = {}
    if chapter_ids:
        chapter_rows = (
            await db.execute(select(Chapter).where(Chapter.id.in_(chapter_ids)))
        ).scalars().all()
        chapters = {int(row.id): row for row in chapter_rows}

    goals = list((
        await db.execute(
            select(Goal).where(Goal.user_id == int(user_id), Goal.status == "active").order_by(Goal.id.asc())
        )
    ).scalars().all())
    goals_by_material: dict[int, list[Goal]] = defaultdict(list)
    for goal in goals:
        if goal.material_id is not None:
            goals_by_material[int(goal.material_id)].append(goal)

    reviews = list((
        await db.execute(
            select(ReviewSchedule).where(
                ReviewSchedule.user_id == int(user_id), ReviewSchedule.status == "pending",
                ReviewSchedule.is_archived.is_(False),
            )
        )
    ).scalars().all())
    review_by_target: dict[tuple[str, int], ReviewSchedule] = {}
    for row in reviews:
        key = (str(row.item_type or ""), int(row.item_id or 0))
        current = review_by_target.get(key)
        if current is None or (row.scheduled_date or now) < (current.scheduled_date or now):
            review_by_target[key] = row

    evidence_rows = list((
        await db.execute(
            select(LearnerEvidence).where(
                LearnerEvidence.user_id == int(user_id), LearnerEvidence.concept_id.in_(concept_ids),
                LearnerEvidence.observed_at >= now - timedelta(days=7),
            ).order_by(LearnerEvidence.observed_at.desc(), LearnerEvidence.id.desc())
        )
    ).scalars().all())
    evidence_by_concept: dict[int, list[LearnerEvidence]] = defaultdict(list)
    for row in evidence_rows:
        evidence_by_concept[int(row.concept_id)].append(row)

    candidates: dict[tuple[str, int, int | None], dict[str, Any]] = {}

    def add_candidate(
        *,
        task_type: str,
        concept_id: int,
        reason: str,
        action: str,
        goal: Goal | None,
        risk: float,
        blockage: float = 0.0,
        errors: float = 0.0,
        extra_urgency: float = 0.0,
        blocked_concept_id: int | None = None,
        review: ReviewSchedule | None = None,
    ) -> None:
        concept = concepts.get(int(concept_id))
        state = states.get(int(concept_id))
        if concept is None:
            return
        latest = state.last_evidence_at if state is not None else None
        fatigue = 1.0 if latest and _local_now(latest) >= now - timedelta(hours=2) else 0.0
        urgency = max(_goal_urgency(goal, now), extra_urgency)
        score, components = _score(
            forgetting_risk=risk, goal_relevance=1.0 if goal else 0.0,
            prerequisite_blockage=blockage, error_frequency=errors,
            urgency=urgency, recent_fatigue=fatigue,
        )
        key = (task_type, int(concept_id), blocked_concept_id)
        candidate = {
            "task_type": task_type,
            "concept_id": int(concept_id),
            "concept_name": concept.name,
            "score": score,
            "score_components": components,
            "reason": reason,
            "suggested_action": action,
            "estimated_minutes": 5 if task_type in {"review_due", "retrieval_practice"} else 10,
            "mastery_estimate": round(float(state.mastery_estimate), 2) if state is not None else 0.0,
            "confidence": round(float(state.confidence), 4) if state is not None else 0.0,
            "forgetting_risk": round(risk, 4),
            "goal_id": int(goal.id) if goal is not None else None,
            "goal_title": goal.title if goal is not None else None,
            "blocked_concept_id": blocked_concept_id,
            "blocked_concept_name": concepts[blocked_concept_id].name if blocked_concept_id in concepts else None,
            "evidence_ids": [int(row.id) for row in evidence_by_concept.get(int(concept_id), [])[:5]],
            "review_schedule_id": int(review.id) if review is not None else None,
            "fsrs_stability": float(review.stability) if review is not None and review.stability is not None else None,
            "next_review_at": (
                review.scheduled_date.isoformat()
                if review is not None and review.scheduled_date is not None
                else (state.next_review_at.isoformat() if state is not None and state.next_review_at else None)
            ),
        }
        previous = candidates.get(key)
        if previous is None or score > previous["score"]:
            candidates[key] = candidate

    for concept_id, concept in concepts.items():
        state = states.get(concept_id)
        risk = float(state.forgetting_risk) if state is not None else 0.85
        mastery = float(state.mastery_estimate) if state is not None else 0.0
        confidence = float(state.confidence) if state is not None else 0.0
        attempt_count = int(state.attempt_count or 0) if state is not None else 0
        correct_count = int(state.correct_count or 0) if state is not None else 0
        recent_errors = sum(
            1 for row in evidence_by_concept.get(concept_id, [])
            if row.evidence_category == "direct" and row.evidence_type != "hint_count" and float(row.score) < 0.6
        )
        error_frequency = max(recent_errors / 3.0, (attempt_count - correct_count) / max(attempt_count, 1))

        concept_goals: list[Goal] = []
        concept_review: ReviewSchedule | None = None
        for link in links_by_concept.get(concept_id, []):
            if link.target_type == "material":
                concept_goals.extend(goals_by_material.get(int(link.target_id), []))
            if link.target_type == "chapter":
                chapter = chapters.get(int(link.target_id))
                if chapter is not None:
                    concept_goals.extend(goals_by_material.get(int(chapter.material_id), []))
                review = review_by_target.get(("chapter", int(link.target_id)))
                if review is not None:
                    concept_review = review
            if link.target_type in {"wrong_question", "question"}:
                review = review_by_target.get(("question", int(link.target_id)))
                if review is not None:
                    concept_review = review
        if not concept_goals:
            concept_goals = [
                goal for goal in goals
                if concept.name.casefold() in f"{goal.title} {goal.description or ''}".casefold()
            ]
        goal = min(concept_goals, key=lambda row: row.deadline or datetime.max.date()) if concept_goals else None

        due_at = concept_review.scheduled_date if concept_review is not None else (state.next_review_at if state is not None else None)
        due = bool(due_at and _local_now(due_at) <= now + timedelta(hours=24))
        if due or risk >= 0.68:
            reason = (
                f"“{concept.name}”的复习已到期，当前遗忘风险为 {risk * 100:.0f}%。"
                if due else f"“{concept.name}”的遗忘风险已达到 {risk * 100:.0f}%，建议先进行无提示回忆。"
            )
            add_candidate(
                task_type="review_due", concept_id=concept_id, reason=reason,
                action=f"用 3 到 5 分钟不看资料复述“{concept.name}”。", goal=goal,
                risk=risk, errors=error_frequency, extra_urgency=1.0 if due else 0.2,
                review=concept_review,
            )

        gaps = await get_prerequisite_gaps(db, user_id, concept_id)
        for gap in gaps:
            prerequisite_id = int(gap["concept_id"])
            prerequisite_state = states.get(prerequisite_id)
            prerequisite_risk = float(prerequisite_state.forgetting_risk) if prerequisite_state is not None else 0.85
            add_candidate(
                task_type="prerequisite_gap", concept_id=prerequisite_id,
                reason=(
                    f"学习“{concept.name}”前，需要先补齐“{gap['name']}”："
                    f"其掌握度仅 {gap['mastery_estimate']:.0f}%，置信度为 {gap['confidence'] * 100:.0f}%。"
                ),
                action=f"先用一个例子解释“{gap['name']}”，再回到“{concept.name}”。",
                goal=goal, risk=prerequisite_risk,
                blockage=max(0.4, 1.0 - float(gap["mastery_estimate"]) / 100.0),
                errors=error_frequency, blocked_concept_id=concept_id,
            )

        if mastery >= 40 and confidence < 0.65:
            add_candidate(
                task_type="retrieval_practice", concept_id=concept_id,
                reason=(
                    f"“{concept.name}”目前显示掌握度 {mastery:.0f}%，"
                    f"但直接证据置信度只有 {confidence * 100:.0f}%，尚不能证明真正掌握。"
                ),
                action=f"合上资料，用自己的话完整解释“{concept.name}”。",
                goal=goal, risk=risk, errors=error_frequency,
            )

        if recent_errors >= 1 or (state is not None and state.common_error_type):
            error_label = str(state.common_error_type or "近期反复出错") if state is not None else "近期反复出错"
            add_candidate(
                task_type="targeted_practice", concept_id=concept_id,
                reason=(
                    f"过去 7 天内，“{concept.name}”出现 {recent_errors} 次低分证据，"
                    f"主要问题为“{error_label}”。"
                ),
                action=f"针对“{error_label}”完成一道“{concept.name}”的变式题。",
                goal=goal, risk=risk, errors=error_frequency,
            )

        if goal is not None and mastery < 85 and not gaps:
            add_candidate(
                task_type="continue_goal", concept_id=concept_id,
                reason=f"“{concept.name}”属于当前目标“{goal.title}”，掌握度 {mastery:.0f}%，适合继续推进。",
                action=f"围绕“{concept.name}”完成当前学习目标的下一段练习。",
                goal=goal, risk=risk, errors=error_frequency,
            )

    ordered = sorted(
        candidates.values(),
        key=lambda item: (-float(item["score"]), item["task_type"] != "prerequisite_gap", int(item["concept_id"])),
    )
    bounded = ordered[: max(1, min(50, int(limit)))]
    return {
        "items": bounded,
        "total": len(ordered),
        "generated_at": now.isoformat(),
        "model_version": RECOMMENDATION_MODEL_VERSION,
        "decision_rule": (
            "0.28*forgetting_risk + 0.20*goal_relevance + 0.24*prerequisite_blockage "
            "+ 0.16*error_frequency + 0.12*urgency - 0.12*recent_fatigue"
        ),
    }
