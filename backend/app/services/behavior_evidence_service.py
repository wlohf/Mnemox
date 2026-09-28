"""Read canonical focus records once, with explicit missingness and provenance.

Events/notes/reports may describe the same focus session. They are not added to
its minutes or evidence count. This read-only layer does not create memories,
infer traits, or reinterpret unknown historical wall-clock times as UTC.
"""
from __future__ import annotations

from collections import Counter
from datetime import datetime, time, timedelta
from hashlib import sha256
import json
import math
from statistics import median
from zoneinfo import ZoneInfo

from sqlalchemy import and_, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachPreference
from app.models.goal import Goal, Task
from app.models.memory import UserMemory
from app.models.pomodoro import Pomodoro
from app.models.session import StudySession
from app.schemas.behavior_evidence import BehaviorEvidenceReport, BehaviorSource, FocusEvidence
from app.services.coach_time_service import normalize_coach_time_zone
from app.utils.utc import to_db_utc, to_utc, to_utc_iso, utc_now_db

EVIDENCE_VERSION = 1
MAX_FOCUS_RECORDS = 5000


async def resolve_analysis_time_zone(db: AsyncSession, user_id: int) -> tuple[str, str]:
    value = await db.scalar(select(CoachPreference.time_zone).where(CoachPreference.user_id == user_id))
    if not value:
        return "UTC", "default_utc"
    try:
        return normalize_coach_time_zone(value), "coach_preference"
    except ValueError:
        return "UTC", "invalid_preference_fallback"


def valid_duration_minutes(value: object) -> float | None:
    try:
        number = float(value)  # type: ignore[arg-type]
    except (TypeError, ValueError, OverflowError):
        return None
    return round(number, 4) if math.isfinite(number) and 0 < number <= 1440 else None


def focus_evidence(
    row: Pomodoro,
    *,
    time_zone: str,
    now: datetime,
    task: Task | None = None,
    session_id: int | None = None,
    legacy_demo: bool = False,
) -> FocusEvidence:
    """Normalize one owned row; linked objects must already pass ownership checks."""
    flags: list[str] = []
    origin = str(row.record_origin or "legacy")
    if legacy_demo:
        origin = "demo"
        flags.append("legacy_demo_marker")
    if origin in {"demo", "simulation"}:
        flags.append("synthetic_record")
    elif origin == "legacy":
        flags.append("legacy_origin")
    start_estimated = origin == "offline_estimated"
    if start_estimated:
        flags.append("estimated_start_time")

    trusted_time = row.time_basis == "utc"
    started = to_db_utc(row.started_at) if row.started_at else None
    ended = to_db_utc(row.ended_at) if row.ended_at else None
    occurred = ended or started
    if not trusted_time:
        flags.append("unknown_time_basis")
    if started is None:
        flags.append("missing_start")
    if occurred is None:
        flags.append("missing_occurrence")
    if started and ended and ended < started:
        flags.append("invalid_time_order")
    if occurred and occurred > to_db_utc(now):
        flags.append("future_record")
    if ended is None:
        flags.append("unfinished_record")

    planned = valid_duration_minutes(row.planned_duration)
    actual = valid_duration_minutes(row.actual_duration)
    reported = valid_duration_minutes(row.duration)
    if planned is None:
        flags.append("missing_planned_duration")
    if actual is None:
        flags.append("missing_actual_duration" if row.actual_duration is None else "invalid_actual_duration")
    # A long real session remains visible; the flag is not a conclusion or an
    # exclusion threshold. Wall-clock and active time need not be identical.
    if actual is not None and actual >= 180:
        flags.append("long_session_review")
    if actual is not None and started and ended and trusted_time and not start_estimated:
        if actual > (ended - started).total_seconds() / 60 + 1:
            flags.append("duration_exceeds_elapsed")
    if row.task_id and task is None:
        flags.append("unavailable_task_context")

    outcome = "in_progress" if ended is None else (
        "early_done" if row.stop_reason == "early_done" else "completed" if row.completed else "interrupted"
    )
    if row.completed and row.stop_reason in {"interrupted", "distracted"}:
        flags.append("conflicting_outcome")

    local = to_utc(occurred).astimezone(ZoneInfo(time_zone)) if occurred and trusted_time else None
    canonical = {
        "id": row.id, "user_id": row.user_id, "origin": origin,
        "time_basis": row.time_basis,
        "started_at": started.isoformat() if started else None,
        "ended_at": ended.isoformat() if ended else None,
        "planned": planned, "actual": actual, "recorded": reported,
        "completed": bool(row.completed), "stop_reason": row.stop_reason,
        "note": row.note, "task_name": row.task_name, "task_id": task.id if task else None,
        "task_title": task.title if task else None,
        "task_version": task.sync_version if task else None,
        "task_type": task.task_type if task else None,
        "session_id": session_id, "client_record_id": row.client_record_id,
    }
    # Include invalid/missing originals too: a correction that only changes a
    # quality flag must still invalidate downstream source references. Convert
    # numeric types consistently across a flush/reload of the same SQL row.
    for field in ("planned_duration", "actual_duration", "duration"):
        value = getattr(row, field)
        try:
            canonical[f"raw_{field}"] = str(float(value)) if value is not None else None
        except (TypeError, ValueError, OverflowError):
            canonical[f"raw_{field}"] = str(value)
    version = sha256(json.dumps(canonical, ensure_ascii=False, sort_keys=True).encode()).hexdigest()
    excluded = {"synthetic_record", "unknown_time_basis", "missing_occurrence", "invalid_time_order", "future_record", "unfinished_record", "conflicting_outcome"}
    return FocusEvidence(
        source=BehaviorSource(
            id=int(row.id), version=version,
            occurred_at=to_utc_iso(occurred) if occurred and trusted_time else None,
            recorded_at=to_utc_iso(row.created_at) if row.created_at else None,
        ),
        evidence_group=f"study_session:{session_id}" if session_id else f"pomodoro:{row.id}",
        origin=origin, local_date=local.date().isoformat() if local else None,
        local_hour=local.hour if local else None, outcome=outcome, stop_reason=row.stop_reason,
        started_at=to_utc_iso(started) if started and trusted_time and not start_estimated else None,
        ended_at=to_utc_iso(ended) if ended and trusted_time else None,
        planned_minutes=planned, actual_minutes=actual, recorded_minutes=reported,
        task_id=int(task.id) if task else None, task_type=task.task_type if task else None,
        task_name=task.title if task else row.task_name if row.task_id is None else None,
        goal_id=int(task.goal_id) if task else None,
        included=not bool(excluded.intersection(flags)), quality_flags=flags,
    )


async def read_focus_evidence(
    db: AsyncSession, user_id: int, *, time_zone: str, now: datetime,
    start: datetime | None = None, end: datetime | None = None,
) -> tuple[list[FocusEvidence], bool]:
    """Bounded canonical read. No query trusts a client-supplied user/source ID."""
    observed = func.coalesce(Pomodoro.ended_at, Pomodoro.started_at, Pomodoro.created_at)
    owned_tasks = select(Task).join(Goal).where(Goal.user_id == user_id).subquery()
    from sqlalchemy.orm import aliased
    task = aliased(Task, owned_tasks)
    statement = (
        select(Pomodoro, task, StudySession.id)
        .outerjoin(task, task.id == Pomodoro.task_id)
        .outerjoin(StudySession, and_(StudySession.id == Pomodoro.session_id, StudySession.user_id == user_id))
        .where(Pomodoro.user_id == user_id)
        .order_by(observed.desc(), Pomodoro.id.desc())
        .limit(MAX_FOCUS_RECORDS + 1)
    )
    if start is not None:
        statement = statement.where(observed >= start)
    if end is not None:
        statement = statement.where(observed < end)
    rows = (await db.execute(statement.execution_options(populate_existing=True))).all()
    # Old demo rows had no origin field. Recognize only the generator's exact
    # marker in a seeded account; never rewrite or delete historical data.
    seeded = await db.scalar(select(UserMemory.id).where(
        UserMemory.user_id == user_id, UserMemory.memory_key == "demo_mnemox_seeded",
    ).limit(1))
    records = [focus_evidence(
        p, task=t, session_id=s, time_zone=time_zone, now=now,
        legacy_demo=bool(seeded and p.record_origin == "legacy" and p.note == "Demo 专注记录"),
    ) for p, t, s in rows[:MAX_FOCUS_RECORDS]]
    return records, len(rows) > MAX_FOCUS_RECORDS


def measured_minutes(record: FocusEvidence) -> float | None:
    if not record.included or "duration_exceeds_elapsed" in record.quality_flags:
        return None
    return record.actual_minutes


def summarize_focus(records: list[FocusEvidence]) -> dict:
    eligible = [r for r in records if r.included]
    measured = [value for r in eligible if (value := measured_minutes(r)) is not None]
    completed = sum(r.outcome in {"completed", "early_done"} for r in eligible)
    hours = Counter(r.local_hour for r in eligible if r.local_hour is not None)
    return {
        "finished_count": len(eligible), "completed_count": completed,
        "interrupted_count": sum(r.outcome == "interrupted" for r in eligible),
        "early_done_count": sum(r.outcome == "early_done" for r in eligible),
        "distracted_count": sum(r.stop_reason == "distracted" for r in eligible),
        "completion_rate": round(completed / len(eligible), 4) if eligible else None,
        "actual_minutes": round(sum(measured), 4) if measured else None,
        "actual_duration_count": len(measured),
        "unknown_actual_duration_count": len(eligible) - len(measured),
        "median_actual_minutes": round(median(measured), 4) if measured else None,
        "mean_actual_minutes": round(sum(measured) / len(measured), 4) if measured else None,
        "hour_counts": {str(h): hours.get(h, 0) for h in range(24)},
        "most_recorded_hour": min(hours, key=lambda h: (-hours[h], h)) if hours else None,
    }


def build_evidence_report(
    records: list[FocusEvidence], *, user_id: int, time_zone: str, time_zone_source: str,
    now: datetime, days: int, truncated: bool,
) -> BehaviorEvidenceReport:
    zone = ZoneInfo(time_zone)
    last_day = to_utc(now).astimezone(zone).date()
    first_day = last_day - timedelta(days=days - 1)
    daily = []
    for offset in range(days):
        day = (first_day + timedelta(days=offset)).isoformat()
        subset = [r for r in records if r.local_date == day and r.included]
        values = summarize_focus(subset)
        daily.append({
            "date": day, "record_count": len(subset),
            "actual_minutes": values["actual_minutes"],
            "unknown_duration_count": values["unknown_actual_duration_count"],
            "status": "observed" if subset else "no_observation",
        })
    eligible = [r for r in records if r.included]
    context_counts = Counter(r.task_type for r in eligible if r.task_type)
    limitations = [
        "descriptive_observations_not_traits", "unrecorded_activity_unknown",
        "task_context_is_current_not_historical", "group_counts_do_not_prove_independence",
    ]
    if len(context_counts) < 2:
        limitations.append("limited_task_context_coverage")
    if time_zone_source not in {"coach_preference", "explicit_context"}:
        limitations.append("time_zone_not_confirmed")
    if truncated:
        limitations.append("record_limit_reached")
    return BehaviorEvidenceReport(
        user_id=user_id, time_zone=time_zone, time_zone_source=time_zone_source,
        generated_at=to_utc_iso(now),
        window={"first_local_date": first_day.isoformat(), "last_local_date": last_day.isoformat(), "days": days, "attribution": "session_end"},
        coverage={
            "scanned_record_count": len(records), "included_record_count": len(eligible),
            "excluded_record_count": len(records) - len(eligible),
            "experience_group_count": len({r.evidence_group for r in eligible}),
            "observed_days": len({r.local_date for r in eligible}),
            "task_type_counts": dict(sorted(context_counts.items())),
            "unlinked_task_count": sum(r.task_id is None for r in eligible),
            "truncated": truncated,
        },
        metrics=summarize_focus(records), daily=daily,
        quality_counts=dict(sorted(Counter(flag for r in records for flag in r.quality_flags).items())),
        limitations=limitations, records=records,
    )


async def get_behavior_evidence(
    db: AsyncSession, user_id: int, *, days: int = 30, now: datetime | None = None,
    time_zone: str | None = None,
) -> BehaviorEvidenceReport:
    if not 1 <= days <= 366:
        raise ValueError("days must be between 1 and 366")
    now = to_db_utc(now or utc_now_db())
    if time_zone is None:
        time_zone, tz_source = await resolve_analysis_time_zone(db, user_id)
    else:
        time_zone, tz_source = normalize_coach_time_zone(time_zone), "explicit_context"
    zone = ZoneInfo(time_zone)
    local_day = to_utc(now).astimezone(zone).date()
    start = to_db_utc(datetime.combine(local_day - timedelta(days=days - 1), time.min, tzinfo=zone))
    end = to_db_utc(datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=zone))
    records, truncated = await read_focus_evidence(db, user_id, time_zone=time_zone, now=now, start=start, end=end)
    return build_evidence_report(records, user_id=user_id, time_zone=time_zone,
                                 time_zone_source=tz_source, now=now, days=days, truncated=truncated)


async def read_focus_date_range(db, user_id, first_day=None, last_day=None, *, now=None):
    """Shared local-date window for legacy statistics endpoints as well as DI."""
    now = to_db_utc(now or utc_now_db())
    zone_name, _ = await resolve_analysis_time_zone(db, user_id)
    zone = ZoneInfo(zone_name)
    today = to_utc(now).astimezone(zone).date()
    last_day = last_day or today
    start = to_db_utc(datetime.combine(first_day, time.min, tzinfo=zone)) if first_day else None
    end = to_db_utc(datetime.combine(last_day + timedelta(days=1), time.min, tzinfo=zone))
    records, truncated = await read_focus_evidence(db, user_id, time_zone=zone_name, now=now, start=start, end=end)
    return records, {'time_zone': zone_name, 'today': today, 'truncated': truncated,
                     'unknown_duration_count': sum(r.included and measured_minutes(r) is None for r in records)}
