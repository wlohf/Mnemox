"""Shared, confirmation-first runtime orchestration for Coach.

The HTTP router, the server-side proactive worker, and future desktop delivery
must make exactly the same policy decision.  This module keeps that decision
and nudge creation in one place; it never performs a user-facing write such as
creating a task or changing a plan.
"""
from __future__ import annotations

import logging
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachPreference
from app.services.coach_action_attempt_service import expire_due_coach_nudges
from app.services.coach_action_service import create_coach_nudge
from app.services.coach_context_retriever import retrieve_coach_context
from app.services.coach_event_service import record_coach_event
from app.services.coach_feedback_service import list_recent_coach_feedback
from app.services.coach_learning_service import get_policy_skill_stats
from app.services.coach_policy_engine import evaluate_coach_policy
from app.services.coach_preference_service import (
    coach_preferences_to_dict,
    get_or_create_coach_preferences,
)
from app.services.coach_skills.base import CoachSkillContext
from app.services.coach_skills.registry import coach_skill_registry
from app.services.learning_snapshot_service import build_learning_snapshot
from app.services.note_quote_service import record_note_quote_usage, select_note_quote

logger = logging.getLogger(__name__)

NOTE_QUOTE_SKILL_IDS = {
    "low_motivation",
    "frustration_support",
    "restart_after_interruption",
}
PROACTIVE_REVIEW_DEBT_THRESHOLD = 6


async def evaluate_coach_event(
    db: AsyncSession,
    user_id: int,
    event: dict[str, Any],
    *,
    include_recent_notes: bool = True,
    include_memories: bool = True,
    preferences: dict[str, Any] | None = None,
    snapshot: dict[str, Any] | None = None,
) -> dict[str, Any]:
    """Evaluate one already-recorded event and create at most one nudge.

    The return shape is deliberately the existing Coach API shape.  The
    caller owns event recording and transaction commit, making this safe for
    both requests and background workers.
    """

    await expire_due_coach_nudges(db, user_id)
    active_snapshot = snapshot or await build_learning_snapshot(
        db,
        user_id,
        include_recent_notes=include_recent_notes,
        include_memories=include_memories,
    )
    active_preferences = preferences or await get_or_create_coach_preferences(db, user_id)
    recent_feedback = await list_recent_coach_feedback(db, user_id, limit=30)
    skill_stats = await get_policy_skill_stats(db, user_id)
    policy = evaluate_coach_policy(
        event,
        active_snapshot,
        active_preferences,
        recent_feedback,
        skill_stats,
    )
    if not policy.get("should_intervene"):
        return {"nudge": None, "policy": policy, "event": event}

    skill_id = str(policy.get("skill_id") or "")
    skill = coach_skill_registry.get(skill_id)
    if not skill:
        raise ValueError("Coach skill 未注册")

    coach_context = await retrieve_coach_context(db, user_id, event, active_snapshot)
    active_snapshot["coach_context"] = coach_context
    if skill_id in NOTE_QUOTE_SKILL_IDS:
        try:
            note_quote = await select_note_quote(db, user_id)
            if note_quote:
                active_snapshot["note_quote"] = note_quote
        except Exception as exc:
            # A personal note quote improves warmth but can never block the
            # core suggestion.
            logger.warning("coach note quote selection failed user_id=%s err=%s", user_id, exc)

    generated = await skill.generate(
        CoachSkillContext(
            user_id=user_id,
            event=event,
            snapshot=active_snapshot,
            policy=policy,
            recent_feedback=recent_feedback,
        )
    )
    nudge = await create_coach_nudge(
        db,
        user_id,
        event_id=event.get("id"),
        skill_id=skill_id,
        policy=policy,
        result=generated,
    )

    used_quote = (generated.explainability or {}).get("note_quote")
    if isinstance(used_quote, dict):
        try:
            await record_note_quote_usage(
                db,
                user_id,
                used_quote,
                channel="coach",
                nudge_id=str(nudge.get("id") or "") or None,
            )
        except Exception as exc:
            logger.warning("coach note quote usage failed user_id=%s err=%s", user_id, exc)

    return {"nudge": nudge, "policy": policy, "event": event}


async def run_proactive_review_debt_cycle(
    db: AsyncSession,
    user_id: int,
    *,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Run the first bounded AgentRuntime scenario: review debt only.

    A locked preference row serializes concurrent application instances for
    this user.  The cycle is opt-in, produces an Agent-panel nudge only, and
    relies on normal Coach caps, snooze and feedback policy before creating
    anything.  It never sends a browser notification, starts a timer, or
    changes a plan by itself.
    """

    current = now or datetime.now()
    preference_row = await db.scalar(
        select(CoachPreference)
        .where(CoachPreference.user_id == user_id)
        .with_for_update()
    )
    if preference_row is None:
        return {"status": "skipped", "reason": "not_opted_in", "nudge": None}
    preferences = coach_preferences_to_dict(preference_row)
    if not preferences.get("enabled") or not preferences.get("proactive_enabled"):
        return {"status": "skipped", "reason": "proactive_disabled", "nudge": None}

    snapshot = await build_learning_snapshot(
        db,
        user_id,
        include_recent_notes=False,
        include_memories=True,
    )
    due_review_count = int((snapshot.get("review") or {}).get("due_review_count") or 0)
    if due_review_count < PROACTIVE_REVIEW_DEBT_THRESHOLD:
        return {
            "status": "skipped",
            "reason": "review_debt_below_threshold",
            "due_review_count": due_review_count,
            "nudge": None,
        }

    event = await record_coach_event(
        db,
        user_id,
        "review.debt_high",
        "agent_runtime",
        {
            "origin": "server_scheduler",
            "due_review_count": due_review_count,
            "scenario": "review_debt_rescue_v1",
        },
        severity="warning" if due_review_count >= 10 else "info",
        # One opportunity per day is enough.  If the user snoozes or rejects
        # it, the normal Coach policy should not keep creating pressure.
        dedupe_key=f"agent-runtime:review-debt:{current.date().isoformat()}",
        occurred_at=current,
    )
    result = await evaluate_coach_event(
        db,
        user_id,
        event,
        include_recent_notes=False,
        include_memories=True,
        preferences=preferences,
        snapshot=snapshot,
    )
    return {
        "status": "nudge_created" if result.get("nudge") else "skipped",
        "reason": str((result.get("policy") or {}).get("reason") or "policy_blocked"),
        "due_review_count": due_review_count,
        **result,
    }
