"""Deterministic, observation-only Coach intervention experiment v0.

The first experiment is deliberately A/A: both variants execute the exact
same policy. Its purpose is to prove assignment stability, immutable lifecycle
instrumentation, attribution windows, and coverage before a policy difference
is ever allowed.
"""
from __future__ import annotations

import hashlib
from collections import defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.config import settings
from app.models.learning_event import LearningEvent
from app.services.learning_event_service import CanonicalEventType, normalize_learning_event_type
from app.utils.utc import to_db_utc, to_utc_iso, utc_now_db


COACH_EXPERIMENT_ASSIGNMENT_VERSION = 1
COACH_EXPERIMENT_MODE = "aa_observation"
COACH_EXPERIMENT_VARIANTS = ("control", "shadow")
COACH_EXPERIMENT_ATTRIBUTION_DAYS = 7


def build_coach_experiment_assignment(
    user_id: int,
    *,
    enabled: bool | None = None,
    experiment_id: str | None = None,
    split_percent: int | None = None,
) -> dict[str, Any] | None:
    """Return a stable user-level A/A assignment without storing PII."""

    active = settings.COACH_INTERVENTION_EXPERIMENT_ENABLED if enabled is None else bool(enabled)
    if not active:
        return None
    clean_experiment_id = str(
        experiment_id or settings.COACH_INTERVENTION_EXPERIMENT_ID or "coach_intervention_aa_v1"
    ).strip()[:80]
    if not clean_experiment_id:
        raise ValueError("Coach experiment id 不能为空")
    clean_split = int(
        settings.COACH_INTERVENTION_EXPERIMENT_SPLIT_PERCENT
        if split_percent is None
        else split_percent
    )
    if clean_split < 1 or clean_split > 99:
        raise ValueError("Coach experiment split 必须在 1 到 99 之间")

    digest = hashlib.sha256(
        f"coach-experiment:{COACH_EXPERIMENT_ASSIGNMENT_VERSION}:{clean_experiment_id}:{int(user_id)}".encode()
    ).digest()
    bucket = int.from_bytes(digest[:8], "big") % 10_000
    variant = "control" if bucket < clean_split * 100 else "shadow"
    return {
        "experiment_id": clean_experiment_id,
        "assignment_version": COACH_EXPERIMENT_ASSIGNMENT_VERSION,
        "bucket": bucket,
        "variant": variant,
        "mode": COACH_EXPERIMENT_MODE,
        "policy_applied": False,
    }


def _event_payload(event: LearningEvent) -> dict[str, Any]:
    payload = event.event_data or {}
    return payload if isinstance(payload, dict) else {}


def _event_time(event: LearningEvent) -> datetime | None:
    value = event.timestamp
    if not isinstance(value, datetime):
        return None
    return to_db_utc(value)


def _event_type(event: LearningEvent) -> str:
    return normalize_learning_event_type(str(event.event_type or ""))


def _rate(numerator: int, denominator: int) -> float | None:
    return round(numerator / denominator * 100, 1) if denominator > 0 else None


async def build_coach_experiment_report(
    db: AsyncSession,
    user_id: int,
    *,
    days: int = 28,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Aggregate one learner's instrumented Coach lifecycle events.

    The report cannot change policy and never compares users. Mature rates
    include only exposures whose seven-day attribution window has closed.
    """

    if days < 7 or days > 90:
        raise ValueError("days 必须在 7 到 90 之间")
    end_at = to_db_utc(now) if now is not None else utc_now_db()
    start_at = end_at - timedelta(days=days)
    assignment = build_coach_experiment_assignment(user_id)
    experiment_id = str(
        (assignment or {}).get("experiment_id")
        or settings.COACH_INTERVENTION_EXPERIMENT_ID
        or "coach_intervention_aa_v1"
    )[:80]

    result = await db.execute(
        select(LearningEvent)
        .where(
            LearningEvent.user_id == user_id,
            LearningEvent.timestamp >= start_at,
            LearningEvent.timestamp <= end_at,
            LearningEvent.event_type.like("coach.nudge.%"),
        )
        .order_by(LearningEvent.timestamp.asc(), LearningEvent.id.asc())
    )
    events = list(result.scalars().all())
    outcomes_by_nudge: dict[str, list[LearningEvent]] = defaultdict(list)
    for event in events:
        nudge_id = str(_event_payload(event).get("nudge_id") or "").strip()
        if nudge_id and _event_type(event) != CanonicalEventType.COACH_NUDGE_SHOWN:
            outcomes_by_nudge[nudge_id].append(event)

    variants = {
        variant: {
            "variant": variant,
            "shown_count": 0,
            "mature_exposure_count": 0,
            "pending_attribution_count": 0,
            "accepted_count": 0,
            "started_count": 0,
            "completed_count": 0,
            "completed_by_domain_event_count": 0,
            "abandoned_count": 0,
            "dismissed_count": 0,
        }
        for variant in COACH_EXPERIMENT_VARIANTS
    }
    uninstrumented_shown = 0
    attribution_window = timedelta(days=COACH_EXPERIMENT_ATTRIBUTION_DAYS)

    for shown in events:
        if _event_type(shown) != CanonicalEventType.COACH_NUDGE_SHOWN:
            continue
        payload = _event_payload(shown)
        if not bool(payload.get("actionable")):
            continue
        experiment = payload.get("experiment")
        if not isinstance(experiment, dict) or experiment.get("experiment_id") != experiment_id:
            uninstrumented_shown += 1
            continue
        variant = str(experiment.get("variant") or "")
        if variant not in variants:
            uninstrumented_shown += 1
            continue
        bucket = variants[variant]
        bucket["shown_count"] += 1
        shown_at = _event_time(shown)
        if shown_at is None or shown_at + attribution_window > end_at:
            bucket["pending_attribution_count"] += 1
            continue
        bucket["mature_exposure_count"] += 1
        nudge_id = str(payload.get("nudge_id") or "")
        valid_outcomes = [
            outcome
            for outcome in outcomes_by_nudge.get(nudge_id, [])
            if (outcome_at := _event_time(outcome)) is not None
            and shown_at <= outcome_at <= shown_at + attribution_window
        ]
        outcome_types = {_event_type(item) for item in valid_outcomes}
        outcome_values = {str(_event_payload(item).get("outcome") or "") for item in valid_outcomes}

        if (
            CanonicalEventType.COACH_NUDGE_ACCEPTED in outcome_types
            or CanonicalEventType.COACH_NUDGE_COMPLETED in outcome_types
            or outcome_values.intersection({"accepted", "helpful", "completed"})
        ):
            bucket["accepted_count"] += 1
        if CanonicalEventType.COACH_NUDGE_STARTED in outcome_types or "started" in outcome_values:
            bucket["started_count"] += 1
        completed_events = [
            item
            for item in valid_outcomes
            if _event_type(item) == CanonicalEventType.COACH_NUDGE_COMPLETED
            or str(_event_payload(item).get("outcome") or "") == "completed"
        ]
        if completed_events:
            bucket["completed_count"] += 1
            if any(
                isinstance(_event_payload(item).get("attribution"), dict)
                and _event_payload(item)["attribution"].get("method") == "domain_event"
                for item in completed_events
            ):
                bucket["completed_by_domain_event_count"] += 1
        if CanonicalEventType.COACH_NUDGE_ABANDONED in outcome_types or "abandoned" in outcome_values:
            bucket["abandoned_count"] += 1
        if (
            CanonicalEventType.COACH_NUDGE_DISMISSED in outcome_types
            or outcome_values.intersection({"dismissed", "too_disruptive", "irrelevant"})
        ):
            bucket["dismissed_count"] += 1

    variant_rows = []
    for variant in COACH_EXPERIMENT_VARIANTS:
        row = variants[variant]
        denominator = int(row["mature_exposure_count"])
        variant_rows.append(
            {
                **row,
                "acceptance_rate": _rate(int(row["accepted_count"]), denominator),
                "start_rate": _rate(int(row["started_count"]), denominator),
                "execution_rate": _rate(int(row["completed_count"]), denominator),
            }
        )

    instrumented_shown = sum(int(row["shown_count"]) for row in variant_rows)
    return {
        "enabled": assignment is not None,
        "experiment_id": experiment_id,
        "mode": COACH_EXPERIMENT_MODE if assignment is not None else "disabled",
        "policy_behavior_changed": False,
        "assignment": assignment,
        "period": {
            "days": days,
            "start_at": to_utc_iso(start_at),
            "end_at": to_utc_iso(end_at),
            "attribution_window_days": COACH_EXPERIMENT_ATTRIBUTION_DAYS,
        },
        "variants": variant_rows,
        "coverage": {
            "instrumented_shown_count": instrumented_shown,
            "uninstrumented_shown_count": uninstrumented_shown,
            "ledger_event_count": len(events),
        },
        "decision_readiness": {
            "ready": False,
            "reason": "aa_observation_only" if assignment is not None else "feature_disabled",
            "minimum_mature_exposures_per_variant": 20,
        },
        "disclaimer": "当前为 A/A 观察模式，两组执行完全相同的 Coach 策略；统计不能证明因果效果，也不会自动调整策略。",
    }
