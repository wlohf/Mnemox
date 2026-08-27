"""Deterministic, isolated Coach behavior regression simulation.

This module intentionally exercises the same immutable learning-event ledger
and north-star metric aggregation used by the product.  Its data is synthetic
and must never be treated as evidence that a real intervention changed learner
behavior.  It is useful for catching attribution, policy and metric regressions
before a public beta collects enough real observations.
"""
from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.coach_policy_engine import default_coach_preferences, evaluate_coach_policy
from app.services.learning_event_service import (
    CanonicalEventType,
    record_coach_nudge_event,
    record_learning_event,
    record_review_completed_event,
    record_review_scheduled_event,
)
from app.services.north_star_metrics_service import build_north_star_metrics


SIMULATION_VERSION = "coach-behavior-synthetic-v1"
SIMULATION_NOW = datetime(2026, 8, 27, 12, 0, 0)


def _nudge(nudge_id: str) -> dict[str, Any]:
    """Return a privacy-safe, actionable nudge fixture.

    The title and body are deliberately absent: lifecycle events must only use
    bounded identifiers and action metadata, even in test tooling.
    """

    return {
        "id": nudge_id,
        "event_id": f"event_{nudge_id}",
        "skill_id": "restart_after_interruption",
        "channel": "in_app_nudge",
        "priority": "medium",
        "suggested_action": {"type": "route", "route": "/pomodoro"},
        "requires_confirmation": False,
    }


def _policy_checks(now: datetime) -> dict[str, Any]:
    """Exercise the proactive allow, cooldown and disruption guardrails."""

    snapshot = {
        "generated_at": now.isoformat(),
        "review": {"due_review_count": 6},
        "learning": {},
        "risk_flags": {"review_debt_high": True},
        "coach": {"today_nudge_count": 0, "last_nudge_at": None},
    }
    event = {
        "event_type": "review.debt_high",
        "source": "agent_runtime",
        "severity": "info",
        "payload": {"scenario": "review_debt_rescue_v1"},
    }
    preferences = {
        **default_coach_preferences(),
        "proactive_enabled": True,
        "allowed_channels": ["agent_panel"],
    }
    allowed = evaluate_coach_policy(event, snapshot, preferences, [])
    cooldown = evaluate_coach_policy(
        event,
        {
            **snapshot,
            "coach": {"today_nudge_count": 0, "last_nudge_at": (now - timedelta(minutes=10)).isoformat()},
        },
        preferences,
        [],
    )
    disruption = evaluate_coach_policy(
        event,
        snapshot,
        preferences,
        [],
        [
            {
                "skill_id": "review_debt_rescue",
                "channel": "agent_panel",
                "event_type": "review.debt_high",
                "too_disruptive_count": 2,
                "recent_score": -2.0,
            }
        ],
    )
    return {
        "review_debt_can_create_agent_panel_draft": (
            allowed.get("should_intervene") is True
            and allowed.get("skill_id") == "review_debt_rescue"
            and allowed.get("channel") == "agent_panel"
        ),
        "cooldown_blocks_repeat_touch": cooldown.get("reason") == "cooldown_active",
        "negative_disruption_feedback_blocks_repeat_touch": (
            disruption.get("reason") == "learned_disruption_feedback"
        ),
        "decisions": {
            "allowed": {key: allowed.get(key) for key in ("should_intervene", "skill_id", "channel", "reason")},
            "cooldown": {key: cooldown.get(key) for key in ("should_intervene", "reason")},
            "disruption": {key: disruption.get(key) for key in ("should_intervene", "reason")},
        },
    }


async def build_synthetic_coach_behavior_report(
    db: AsyncSession,
    user_id: int,
    *,
    now: datetime = SIMULATION_NOW,
) -> dict[str, Any]:
    """Seed one isolated virtual learner and return the computed regression report.

    ``db`` must point to a throwaway database.  The helper writes synthetic
    events so callers can exercise the real ledger path, but it never reads or
    writes production data on its own.
    """

    # Eight mature actionable suggestions: four are tied to a real domain
    # event, two rely on explicit learner confirmation, and two are abandoned.
    # Two newer suggestions remain deliberately outside the attribution window.
    shown_at = now - timedelta(days=9)
    for index in range(10):
        nudge = _nudge(f"synthetic_nudge_{index}")
        created_at = shown_at if index < 8 else now - timedelta(days=2)
        await record_coach_nudge_event(
            db,
            user_id,
            nudge,
            CanonicalEventType.COACH_NUDGE_SHOWN,
            occurred_at=created_at,
        )
        if index < 6:
            await record_coach_nudge_event(
                db,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_ACCEPTED,
                outcome="accepted",
                occurred_at=created_at + timedelta(minutes=1),
            )
        if index < 8:
            await record_coach_nudge_event(
                db,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_STARTED,
                outcome="started",
                occurred_at=created_at + timedelta(minutes=2),
            )
        if index < 4:
            await record_coach_nudge_event(
                db,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_COMPLETED,
                outcome="completed",
                attribution={"method": "domain_event", "attempt_id": f"synthetic_attempt_{index}"},
                occurred_at=created_at + timedelta(minutes=25),
            )
        elif index < 6:
            await record_coach_nudge_event(
                db,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_COMPLETED,
                outcome="completed",
                attribution={"method": "user_confirmation", "attempt_id": f"synthetic_attempt_{index}"},
                occurred_at=created_at + timedelta(minutes=25),
            )
        elif index < 8:
            await record_coach_nudge_event(
                db,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_ABANDONED,
                outcome="abandoned",
                occurred_at=created_at + timedelta(minutes=25),
            )

    # Three mature interruptions: two recover, one does not.  The newest one
    # intentionally remains inside the 72-hour observation window.
    for index, recovery_minutes in enumerate((30, 60, None, 15)):
        interrupted_at = now - timedelta(days=9 - index * 2) if index < 3 else now - timedelta(days=1)
        await record_learning_event(
            db,
            user_id,
            CanonicalEventType.POMODORO_INTERRUPTED,
            source="synthetic_simulation",
            payload={"pomodoro_id": 100 + index},
            occurred_at=interrupted_at,
        )
        if recovery_minutes is not None:
            await record_learning_event(
                db,
                user_id,
                CanonicalEventType.POMODORO_STARTED,
                source="synthetic_simulation",
                payload={"pomodoro_id": 200 + index},
                occurred_at=interrupted_at + timedelta(minutes=recovery_minutes),
            )

    # Four mature review opportunities (two on time) and one still inside the
    # grace period.  This protects the denominator semantics from regressions.
    for index in range(5):
        due_at = now - timedelta(days=8 - index) if index < 4 else now - timedelta(hours=8)
        await record_review_scheduled_event(
            db,
            user_id,
            entity_type="review_schedule",
            entity_id=300 + index,
            due_at=due_at,
            source="synthetic_simulation",
            item_type="chapter",
            item_id=index + 1,
            occurred_at=due_at - timedelta(days=2),
        )
        if index < 2:
            await record_review_completed_event(
                db,
                user_id,
                entity_type="review_schedule",
                entity_id=300 + index,
                scheduled_for=due_at,
                source="synthetic_simulation",
                quality=4,
                occurred_at=due_at + timedelta(hours=2),
            )

    # Three qualifying sessions in the current calendar week.
    for index in range(3):
        await record_learning_event(
            db,
            user_id,
            CanonicalEventType.POMODORO_COMPLETED,
            source="synthetic_simulation",
            payload={"pomodoro_id": 400 + index},
            duration=25 * 60,
            occurred_at=now - timedelta(days=index),
        )

    metrics = await build_north_star_metrics(db, user_id, days=14, time_zone="UTC", now=now)
    checks = {
        "suggestion_execution_separates_domain_and_confirmation": (
            metrics["metrics"]["suggestion_execution_rate"] == {
                **metrics["metrics"]["suggestion_execution_rate"],
                "value": 75.0,
                "numerator": 6,
                "denominator": 8,
                "completed_by_domain_event_count": 4,
                "completed_by_user_confirmation_count": 2,
                "abandoned_count": 2,
                "pending_attribution_count": 2,
            }
        ),
        "interruption_recovery_uses_mature_observations_only": (
            metrics["metrics"]["interruption_recovery_time"].get("value") == 45.0
            and metrics["metrics"]["interruption_recovery_time"].get("denominator") == 3
            and metrics["metrics"]["interruption_recovery_time"].get("unrecovered_count") == 1
            and metrics["metrics"]["interruption_recovery_time"].get("pending_observation_count") == 1
        ),
        "review_on_time_rate_keeps_open_observations_out_of_denominator": (
            metrics["metrics"]["review_on_time_rate"].get("value") == 50.0
            and metrics["metrics"]["review_on_time_rate"].get("denominator") == 4
            and metrics["metrics"]["review_on_time_rate"].get("pending_observation_count") == 1
        ),
        "weekly_effective_sessions_apply_minimum_duration": (
            metrics["metrics"]["weekly_effective_study_sessions"].get("value") == 3
        ),
    }
    policy = _policy_checks(now)
    all_checks = {**checks, **{key: value for key, value in policy.items() if isinstance(value, bool)}}
    return {
        "simulation": {
            "version": SIMULATION_VERSION,
            "mode": "synthetic_policy_and_metric_regression",
            "generated_at": now.isoformat(),
            "data_scope": "throwaway database only",
            "important_limit": "模拟数据只能验证链路和策略边界，不能证明对真实用户有效。",
        },
        "checks": all_checks,
        "passed": all(all_checks.values()),
        "policy": policy["decisions"],
        "metrics": metrics["metrics"],
        "next_evidence": {
            "required_for_effect_claim": "使用真实、知情同意的用户行为样本，按既定归因窗口复核。",
            "model_promotion": "学习者模型仍只接受真实 holdout 数据，不接受本模拟数据。",
        },
    }
