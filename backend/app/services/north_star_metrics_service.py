"""North-star metric aggregation over the immutable learning event ledger."""
from __future__ import annotations

from collections import defaultdict
from datetime import datetime, timedelta
from statistics import median
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning_event import LearningEvent
from app.services.learning_event_service import CanonicalEventType, normalize_learning_event_type


METRIC_DEFINITIONS_VERSION = 2
DEFAULT_ATTRIBUTION_WINDOW_DAYS = 7
DEFAULT_RECOVERY_WINDOW_HOURS = 72
DEFAULT_REVIEW_GRACE_HOURS = 24
MIN_EFFECTIVE_STUDY_SECONDS = 15 * 60


NORTH_STAR_METRIC_DEFINITIONS = {
    "suggestion_execution_rate": {
        "label": "建议已确认执行率",
        "numerator": "展示后 7 天内完成的可执行 Coach nudge 数；区分真实领域行为与用户确认",
        "denominator": "已完整经过 7 天归因窗口的可执行 Coach nudge 展示数",
        "unit": "percent",
    },
    "interruption_recovery_time": {
        "label": "中断恢复时长",
        "numerator": "每次成熟中断到下一次学习开始的分钟数",
        "denominator": "已完整经过 72 小时观察窗口的番茄钟中断数",
        "unit": "minutes",
    },
    "review_on_time_rate": {
        "label": "复习按时率",
        "numerator": "到期后 24 小时内完成的已成熟复习机会数",
        "denominator": "已完整经过 24 小时宽限期的排期复习机会数",
        "unit": "percent",
    },
    "weekly_effective_study_sessions": {
        "label": "每周有效学习时段数",
        "numerator": "完成且时长至少 15 分钟的番茄钟数",
        "denominator": "当前自然周；同时返回所选窗口内每周计数",
        "unit": "sessions",
    },
}


def validate_metric_time_zone(time_zone: str) -> str:
    """Validate an IANA zone even though legacy timestamps are naive values."""

    candidate = str(time_zone or "").strip() or "UTC"
    try:
        ZoneInfo(candidate)
    except ZoneInfoNotFoundError as exc:
        raise ValueError("time_zone 必须是有效的 IANA 时区，例如 Asia/Tokyo") from exc
    return candidate


def _as_datetime(value: Any, *, zone: ZoneInfo | None = None) -> datetime | None:
    if isinstance(value, datetime):
        return value.astimezone(zone).replace(tzinfo=None) if value.tzinfo and zone else value.replace(tzinfo=None) if value.tzinfo else value
    if not isinstance(value, str) or not value:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    return parsed.astimezone(zone).replace(tzinfo=None) if parsed.tzinfo and zone else parsed.replace(tzinfo=None) if parsed.tzinfo else parsed


def _event_type(event: LearningEvent) -> str:
    return normalize_learning_event_type(str(event.event_type or ""))


def _event_payload(event: LearningEvent) -> dict[str, Any]:
    payload = event.event_data or {}
    return payload if isinstance(payload, dict) else {}


def _event_timestamp(event: LearningEvent, *, zone: ZoneInfo | None = None) -> datetime | None:
    return _as_datetime(event.timestamp, zone=zone)


def _event_id(event: LearningEvent) -> str:
    return str(event.id)


def _percent(numerator: int, denominator: int) -> float | None:
    if denominator <= 0:
        return None
    return round(numerator / denominator * 100, 1)


def _review_opportunity_key(payload: dict[str, Any]) -> str | None:
    review_key = str(payload.get("review_key") or "").strip()
    scheduled_for = str(payload.get("scheduled_for") or "").strip()
    if not review_key or not scheduled_for:
        return None
    return f"{review_key}:{scheduled_for}"


def _is_effective_pomodoro(event: LearningEvent) -> bool:
    if _event_type(event) != CanonicalEventType.POMODORO_COMPLETED:
        return False
    seconds = event.duration
    if seconds is None:
        duration_minutes = _event_payload(event).get("duration")
        try:
            seconds = int(float(duration_minutes) * 60)
        except (TypeError, ValueError):
            seconds = 0
    return int(seconds or 0) >= MIN_EFFECTIVE_STUDY_SECONDS


def _local_week_start(value: datetime) -> datetime:
    return (value - timedelta(days=value.weekday())).replace(hour=0, minute=0, second=0, microsecond=0)


async def build_north_star_metrics(
    db: AsyncSession,
    user_id: int,
    *,
    days: int = 28,
    time_zone: str = "UTC",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Compute the four metric definitions from raw, user-scoped event data.

    The event column predates timezone-aware storage and contains naive values.
    ``time_zone`` therefore defines the wall-clock interpretation and period
    grouping; it does not retroactively convert historical timestamps.
    """

    if days < 7 or days > 90:
        raise ValueError("days 必须在 7 到 90 之间")
    clean_time_zone = validate_metric_time_zone(time_zone)
    metric_zone = ZoneInfo(clean_time_zone)
    end_at = _as_datetime(now, zone=metric_zone) or datetime.now(metric_zone).replace(tzinfo=None)
    start_at = end_at - timedelta(days=days)
    # A review can be scheduled well before its due date. Keeping one year of
    # ledger history gives the first v1 report enough context without scanning
    # the entire event table for every request.
    lookup_start = start_at - timedelta(days=366)
    result = await db.execute(
        select(LearningEvent)
        .where(
            LearningEvent.user_id == user_id,
            LearningEvent.timestamp >= lookup_start,
            LearningEvent.timestamp <= end_at,
        )
        .order_by(LearningEvent.timestamp.asc(), LearningEvent.id.asc())
    )
    events = [event for event in result.scalars().all() if _event_timestamp(event, zone=metric_zone) is not None]

    window_events = [
        event for event in events if (event_time := _event_timestamp(event, zone=metric_zone)) is not None and start_at <= event_time <= end_at
    ]
    lifecycle_events: dict[str, list[LearningEvent]] = defaultdict(list)
    for event in events:
        lifecycle_events[_event_type(event)].append(event)

    attribution_window = timedelta(days=DEFAULT_ATTRIBUTION_WINDOW_DAYS)
    shown_events = [
        event
        for event in window_events
        if _event_type(event) == CanonicalEventType.COACH_NUDGE_SHOWN
        and bool(_event_payload(event).get("actionable"))
    ]
    outcomes_by_nudge: dict[str, list[LearningEvent]] = defaultdict(list)
    outcome_types = {
        CanonicalEventType.COACH_NUDGE_ACCEPTED,
        CanonicalEventType.COACH_NUDGE_STARTED,
        CanonicalEventType.COACH_NUDGE_COMPLETED,
        CanonicalEventType.COACH_NUDGE_ABANDONED,
        CanonicalEventType.COACH_NUDGE_FEEDBACK,
    }
    for event_type in outcome_types:
        for event in lifecycle_events[event_type]:
            nudge_id = str(_event_payload(event).get("nudge_id") or "").strip()
            if nudge_id:
                outcomes_by_nudge[nudge_id].append(event)

    mature_shown: list[LearningEvent] = []
    pending_shown = 0
    execution_confirmed = 0
    execution_domain_confirmed = 0
    execution_user_confirmed = 0
    accepted = 0
    started = 0
    abandoned = 0
    for shown in shown_events:
        shown_at = _event_timestamp(shown, zone=metric_zone)
        if not shown_at:
            continue
        if shown_at + attribution_window > end_at:
            pending_shown += 1
            continue
        mature_shown.append(shown)
        nudge_id = str(_event_payload(shown).get("nudge_id") or "").strip()
        for outcome in outcomes_by_nudge.get(nudge_id, []):
            outcome_at = _event_timestamp(outcome, zone=metric_zone)
            if not outcome_at or outcome_at < shown_at or outcome_at > shown_at + attribution_window:
                continue
            outcome_type = _event_type(outcome)
            outcome_payload = _event_payload(outcome)
            outcome_value = str(outcome_payload.get("outcome") or "")
            if outcome_type == CanonicalEventType.COACH_NUDGE_COMPLETED or outcome_value == "completed":
                execution_confirmed += 1
                attribution = outcome_payload.get("attribution") or {}
                if isinstance(attribution, dict) and attribution.get("method") == "domain_event":
                    execution_domain_confirmed += 1
                else:
                    execution_user_confirmed += 1
                break
        for outcome in outcomes_by_nudge.get(nudge_id, []):
            outcome_at = _event_timestamp(outcome, zone=metric_zone)
            if not outcome_at or outcome_at < shown_at or outcome_at > shown_at + attribution_window:
                continue
            outcome_type = _event_type(outcome)
            outcome_value = str(_event_payload(outcome).get("outcome") or "")
            if outcome_type in {CanonicalEventType.COACH_NUDGE_ACCEPTED, CanonicalEventType.COACH_NUDGE_COMPLETED} or outcome_value in {"accepted", "completed", "helpful"}:
                accepted += 1
                break
        for outcome in outcomes_by_nudge.get(nudge_id, []):
            outcome_at = _event_timestamp(outcome, zone=metric_zone)
            if not outcome_at or outcome_at < shown_at or outcome_at > shown_at + attribution_window:
                continue
            outcome_type = _event_type(outcome)
            outcome_value = str(_event_payload(outcome).get("outcome") or "")
            if outcome_type == CanonicalEventType.COACH_NUDGE_STARTED or outcome_value == "started":
                started += 1
                break
        for outcome in outcomes_by_nudge.get(nudge_id, []):
            outcome_at = _event_timestamp(outcome, zone=metric_zone)
            if not outcome_at or outcome_at < shown_at or outcome_at > shown_at + attribution_window:
                continue
            outcome_type = _event_type(outcome)
            outcome_value = str(_event_payload(outcome).get("outcome") or "")
            if outcome_type == CanonicalEventType.COACH_NUDGE_ABANDONED or outcome_value == "abandoned":
                abandoned += 1
                break

    recovery_window = timedelta(hours=DEFAULT_RECOVERY_WINDOW_HOURS)
    learning_starts = [
        event
        for event in lifecycle_events[CanonicalEventType.POMODORO_STARTED]
        if _event_timestamp(event, zone=metric_zone) is not None
    ]
    interruptions = [
        event
        for event in window_events
        if _event_type(event) == CanonicalEventType.POMODORO_INTERRUPTED
    ]
    recovery_minutes: list[float] = []
    mature_interruptions = 0
    pending_interruptions = 0
    for interruption in interruptions:
        interrupted_at = _event_timestamp(interruption, zone=metric_zone)
        if not interrupted_at:
            continue
        if interrupted_at + recovery_window > end_at:
            pending_interruptions += 1
            continue
        mature_interruptions += 1
        next_start = next(
            (
                _event_timestamp(start, zone=metric_zone)
                for start in learning_starts
                if (_event_timestamp(start, zone=metric_zone) or end_at) >= interrupted_at
                and (_event_timestamp(start, zone=metric_zone) or end_at) <= interrupted_at + recovery_window
            ),
            None,
        )
        if next_start:
            recovery_minutes.append(round((next_start - interrupted_at).total_seconds() / 60, 1))

    scheduled_events = [
        event
        for event in lifecycle_events[CanonicalEventType.REVIEW_SCHEDULED]
        if _review_opportunity_key(_event_payload(event)) is not None
    ]
    completed_by_opportunity: dict[str, list[LearningEvent]] = defaultdict(list)
    for event in lifecycle_events[CanonicalEventType.REVIEW_COMPLETED]:
        opportunity_key = _review_opportunity_key(_event_payload(event))
        if opportunity_key:
            completed_by_opportunity[opportunity_key].append(event)

    review_grace = timedelta(hours=DEFAULT_REVIEW_GRACE_HOURS)
    opportunities: dict[str, tuple[datetime, LearningEvent]] = {}
    for event in scheduled_events:
        payload = _event_payload(event)
        opportunity_key = _review_opportunity_key(payload)
        due_at = _as_datetime(payload.get("scheduled_for"), zone=metric_zone)
        if not opportunity_key or not due_at or not (start_at <= due_at <= end_at):
            continue
        existing = opportunities.get(opportunity_key)
        if not existing or (_event_timestamp(event, zone=metric_zone) or start_at) > (_event_timestamp(existing[1], zone=metric_zone) or start_at):
            opportunities[opportunity_key] = (due_at, event)

    mature_opportunities = 0
    pending_opportunities = 0
    on_time_reviews = 0
    for opportunity_key, (due_at, _scheduled_event) in opportunities.items():
        if due_at + review_grace > end_at:
            pending_opportunities += 1
            continue
        mature_opportunities += 1
        completions = completed_by_opportunity.get(opportunity_key, [])
        if any(
            (completed_at := _event_timestamp(event, zone=metric_zone)) is not None
            and completed_at <= due_at + review_grace
            for event in completions
        ):
            on_time_reviews += 1

    effective_by_week: dict[datetime, set[str]] = defaultdict(set)
    for event in window_events:
        if not _is_effective_pomodoro(event):
            continue
        event_at = _event_timestamp(event, zone=metric_zone)
        if not event_at:
            continue
        payload = _event_payload(event)
        pomodoro_key = str(payload.get("pomodoro_id") or _event_id(event))
        effective_by_week[_local_week_start(event_at)].add(pomodoro_key)
    current_week_start = _local_week_start(end_at)
    weekly_counts = [
        {
            "week_start": week_start.date().isoformat(),
            "count": len(session_ids),
        }
        for week_start, session_ids in sorted(effective_by_week.items())
    ]
    weekly_average = (
        round(sum(item["count"] for item in weekly_counts) / len(weekly_counts), 1)
        if weekly_counts
        else 0.0
    )

    return {
        "definitions_version": METRIC_DEFINITIONS_VERSION,
        "generated_at": end_at.isoformat(),
        "period": {
            "start_at": start_at.isoformat(),
            "end_at": end_at.isoformat(),
            "days": days,
            "time_zone": clean_time_zone,
            "timestamp_interpretation": "naive application clock in requested time zone",
        },
        "metrics": {
            "suggestion_execution_rate": {
                "value": _percent(execution_confirmed, len(mature_shown)),
                "numerator": execution_confirmed,
                "denominator": len(mature_shown),
                "accepted_count": accepted,
                "started_count": started,
                "completed_by_domain_event_count": execution_domain_confirmed,
                "completed_by_user_confirmation_count": execution_user_confirmed,
                "abandoned_count": abandoned,
                "pending_attribution_count": pending_shown,
                "attribution_window_days": DEFAULT_ATTRIBUTION_WINDOW_DAYS,
                "evidence": "domain_event_or_user_confirmation",
            },
            "interruption_recovery_time": {
                "value": round(float(median(recovery_minutes)), 1) if recovery_minutes else None,
                "average_minutes": round(sum(recovery_minutes) / len(recovery_minutes), 1) if recovery_minutes else None,
                "recovered_count": len(recovery_minutes),
                "denominator": mature_interruptions,
                "unrecovered_count": max(0, mature_interruptions - len(recovery_minutes)),
                "pending_observation_count": pending_interruptions,
                "observation_window_hours": DEFAULT_RECOVERY_WINDOW_HOURS,
            },
            "review_on_time_rate": {
                "value": _percent(on_time_reviews, mature_opportunities),
                "numerator": on_time_reviews,
                "denominator": mature_opportunities,
                "pending_observation_count": pending_opportunities,
                "grace_hours": DEFAULT_REVIEW_GRACE_HOURS,
            },
            "weekly_effective_study_sessions": {
                "value": len(effective_by_week.get(current_week_start, set())),
                "current_week_start": current_week_start.date().isoformat(),
                "weekly_average": weekly_average,
                "weekly_counts": weekly_counts,
                "minimum_duration_minutes": MIN_EFFECTIVE_STUDY_SECONDS // 60,
            },
        },
        "coverage": {
            "ledger_event_count": len(events),
            "window_event_count": len(window_events),
            "raw_event_required": True,
            "legacy_data_note": "v1 指标只使用有明确契约的原始事件；历史聚合数据不会补写为事件。",
        },
    }
