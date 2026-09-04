"""Time-zone aware scheduling helpers for Coach and AgentRuntime.

Database scheduler timestamps are stored as naive UTC values.  User-facing
quiet hours are wall-clock values in the learner's configured IANA time zone.
Keeping that conversion here prevents the HTTP policy path and the background
worker from slowly drifting into different interpretations.
"""
from __future__ import annotations

from datetime import date, datetime, time, timedelta
from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from app.utils.utc import to_db_utc, to_utc


DEFAULT_COACH_TIME_ZONE = "UTC"


def normalize_coach_time_zone(value: Any) -> str:
    """Return a validated IANA time zone name."""

    candidate = str(value or "").strip() or DEFAULT_COACH_TIME_ZONE
    if len(candidate) > 64:
        raise ValueError("time_zone 最长为 64 个字符")
    try:
        ZoneInfo(candidate)
    except (ZoneInfoNotFoundError, ValueError) as exc:
        raise ValueError("time_zone 必须是有效的 IANA 时区，例如 Asia/Shanghai") from exc
    return candidate


def parse_quiet_hour(value: Any) -> time | None:
    """Parse a strict ``HH:mm`` wall-clock value."""

    text = str(value or "").strip()
    if not text:
        return None
    try:
        parsed = datetime.strptime(text, "%H:%M")
    except ValueError as exc:
        raise ValueError("免打扰时间必须使用 HH:mm 格式") from exc
    return parsed.time()


def local_day_utc_bounds(now: datetime, *, time_zone: Any) -> tuple[date, datetime, datetime]:
    """Return local date and its half-open UTC bounds as naive datetimes."""

    zone = ZoneInfo(normalize_coach_time_zone(time_zone))
    local_now = to_utc(now).astimezone(zone)
    local_day = local_now.date()
    local_start = datetime.combine(local_day, time.min, tzinfo=zone)
    local_end = datetime.combine(local_day + timedelta(days=1), time.min, tzinfo=zone)
    return (
        local_day,
        to_db_utc(local_start),
        to_db_utc(local_end),
    )


def quiet_hours_end_utc(
    now: datetime,
    *,
    time_zone: Any,
    start: Any,
    end: Any,
) -> datetime | None:
    """Return the naive UTC quiet-window end when ``now`` is inside it.

    Equal start/end values represent a disabled (zero-length) window.  The
    returned value is suitable for ``proactive_next_evaluate_at``.
    """

    quiet_start = parse_quiet_hour(start)
    quiet_end = parse_quiet_hour(end)
    if quiet_start is None or quiet_end is None or quiet_start == quiet_end:
        return None

    zone = ZoneInfo(normalize_coach_time_zone(time_zone))
    local_now = to_utc(now).astimezone(zone)
    local_clock = local_now.time().replace(tzinfo=None)
    end_date: date

    if quiet_start < quiet_end:
        if not quiet_start <= local_clock < quiet_end:
            return None
        end_date = local_now.date()
    elif local_clock >= quiet_start:
        end_date = local_now.date() + timedelta(days=1)
    elif local_clock < quiet_end:
        end_date = local_now.date()
    else:
        return None

    local_end = datetime.combine(end_date, quiet_end, tzinfo=zone)
    return to_db_utc(local_end)


def is_quiet_time(
    now: datetime,
    *,
    time_zone: Any,
    start: Any,
    end: Any,
) -> bool:
    """Return whether ``now`` falls in the configured quiet window."""

    return quiet_hours_end_utc(
        now,
        time_zone=time_zone,
        start=start,
        end=end,
    ) is not None
