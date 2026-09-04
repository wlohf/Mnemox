"""Coach preference persistence."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachPreference
from app.services.coach_policy_engine import SUPPORTED_CHANNELS, default_coach_preferences
from app.services.coach_time_service import normalize_coach_time_zone, parse_quiet_hour
from app.utils.utc import to_utc_iso, utc_now_db


def _utc_iso(value: datetime | None) -> str | None:
    return to_utc_iso(value) if value is not None else None


def coach_preferences_to_dict(row: CoachPreference | None) -> dict[str, Any]:
    base = default_coach_preferences()
    if not row:
        return base
    return {
        **base,
        "enabled": bool(row.enabled),
        "proactive_enabled": bool(row.proactive_enabled),
        "desktop_notifications_enabled": bool(row.desktop_notifications_enabled),
        "time_zone": normalize_coach_time_zone(row.time_zone),
        "quiet_hours_start": row.quiet_hours_start,
        "quiet_hours_end": row.quiet_hours_end,
        "max_nudges_per_day": int(row.max_nudges_per_day or base["max_nudges_per_day"]),
        "min_minutes_between_nudges": int(row.min_minutes_between_nudges or base["min_minutes_between_nudges"]),
        "allowed_channels": row.allowed_channels if isinstance(row.allowed_channels, list) else base["allowed_channels"],
        "disabled_skill_ids": row.disabled_skill_ids if isinstance(row.disabled_skill_ids, list) else [],
        "proactive_last_evaluated_at": _utc_iso(row.proactive_last_evaluated_at),
        "proactive_next_evaluate_at": _utc_iso(row.proactive_next_evaluate_at),
        "proactive_failure_count": int(row.proactive_failure_count or 0),
        "updated_at": _utc_iso(row.updated_at),
    }


async def get_or_create_coach_preferences(db: AsyncSession, user_id: int) -> dict[str, Any]:
    result = await db.execute(select(CoachPreference).where(CoachPreference.user_id == user_id))
    row = result.scalar_one_or_none()
    if not row:
        defaults = default_coach_preferences()
        row = CoachPreference(
            user_id=user_id,
            enabled=defaults["enabled"],
            proactive_enabled=defaults["proactive_enabled"],
            desktop_notifications_enabled=defaults["desktop_notifications_enabled"],
            time_zone=defaults["time_zone"],
            quiet_hours_start=defaults["quiet_hours_start"],
            quiet_hours_end=defaults["quiet_hours_end"],
            max_nudges_per_day=defaults["max_nudges_per_day"],
            min_minutes_between_nudges=defaults["min_minutes_between_nudges"],
            allowed_channels=defaults["allowed_channels"],
            disabled_skill_ids=defaults["disabled_skill_ids"],
        )
        db.add(row)
        await db.flush()
        await db.refresh(row)
    return coach_preferences_to_dict(row)


async def update_coach_preferences(db: AsyncSession, user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    await get_or_create_coach_preferences(db, user_id)
    result = await db.execute(select(CoachPreference).where(CoachPreference.user_id == user_id))
    row = result.scalar_one()

    if "enabled" in patch:
        row.enabled = bool(patch["enabled"])
    if "proactive_enabled" in patch:
        row.proactive_enabled = bool(patch["proactive_enabled"])
    if "desktop_notifications_enabled" in patch:
        row.desktop_notifications_enabled = bool(patch["desktop_notifications_enabled"])
    if "time_zone" in patch:
        row.time_zone = normalize_coach_time_zone(patch["time_zone"])
    if "quiet_hours_start" in patch:
        parsed_start = parse_quiet_hour(patch["quiet_hours_start"])
        row.quiet_hours_start = parsed_start.strftime("%H:%M") if parsed_start else None
    if "quiet_hours_end" in patch:
        parsed_end = parse_quiet_hour(patch["quiet_hours_end"])
        row.quiet_hours_end = parsed_end.strftime("%H:%M") if parsed_end else None
    if "max_nudges_per_day" in patch:
        row.max_nudges_per_day = max(1, min(10, int(patch["max_nudges_per_day"] or 3)))
    if "min_minutes_between_nudges" in patch:
        row.min_minutes_between_nudges = max(0, min(24 * 60, int(patch["min_minutes_between_nudges"] or 60)))
    if "allowed_channels" in patch and isinstance(patch["allowed_channels"], list):
        channels = [str(item)[:40] for item in patch["allowed_channels"][:8]]
        row.allowed_channels = [item for item in channels if item in SUPPORTED_CHANNELS] or default_coach_preferences()["allowed_channels"]
    if "disabled_skill_ids" in patch and isinstance(patch["disabled_skill_ids"], list):
        row.disabled_skill_ids = [str(item)[:80] for item in patch["disabled_skill_ids"][:30]]
    row.updated_at = utc_now_db()
    await db.flush()
    await db.refresh(row)
    return coach_preferences_to_dict(row)
