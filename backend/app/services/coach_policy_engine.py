"""Deterministic bounded-autonomy policy for coach interventions.

Coach 可以主动响应事件，但必须先经过用户偏好、免打扰、冷却、每日上限和反馈学习约束。
生成内容只进入 nudge/workflow 草稿，真正写入学习数据仍交给确认式执行链路。
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from typing import Any


DEFAULT_ALLOWED_CHANNELS = ["chat_inline", "in_app_nudge", "agent_panel"]
SUPPORTED_CHANNELS = [*DEFAULT_ALLOWED_CHANNELS, "desktop_notification"]
NEGATIVE_OUTCOMES = {"dismissed", "too_disruptive", "too_hard", "too_easy", "irrelevant", "not_my_style", "later", "snoozed"}


def default_coach_preferences() -> dict[str, Any]:
    return {
        "enabled": True,
        "proactive_enabled": False,
        "desktop_notifications_enabled": False,
        "quiet_hours_start": None,
        "quiet_hours_end": None,
        "max_nudges_per_day": 3,
        "min_minutes_between_nudges": 60,
        "allowed_channels": DEFAULT_ALLOWED_CHANNELS.copy(),
        "disabled_skill_ids": [],
    }


def _parse_iso_datetime(value: Any) -> datetime | None:
    if not value:
        return None
    if isinstance(value, datetime):
        return value
    try:
        return datetime.fromisoformat(str(value))
    except Exception:
        return None


def _parse_hhmm(value: Any) -> time | None:
    text = str(value or "").strip()
    if not text:
        return None
    try:
        hour, minute = text.split(":", 1)
        return time(hour=max(0, min(23, int(hour))), minute=max(0, min(59, int(minute))))
    except Exception:
        return None


def _is_quiet_time(now: datetime, start: Any, end: Any) -> bool:
    quiet_start = _parse_hhmm(start)
    quiet_end = _parse_hhmm(end)
    if not quiet_start or not quiet_end:
        return False
    current = now.time()
    if quiet_start <= quiet_end:
        return quiet_start <= current <= quiet_end
    return current >= quiet_start or current <= quiet_end


def _event_skill(event: dict[str, Any], snapshot: dict[str, Any]) -> tuple[str | None, str]:
    event_type = str(event.get("event_type") or "")
    payload = event.get("payload") or {}
    text = str(payload.get("text") or payload.get("message") or "").lower()
    risk_flags = snapshot.get("risk_flags") or {}
    due_review_count = int((snapshot.get("review") or {}).get("due_review_count") or 0)
    today_completed_pomodoros = int((snapshot.get("learning") or {}).get("today_completed_pomodoros") or 0)

    if event_type == "chat.frustration_detected":
        return "frustration_support", "explicit_chat_frustration"
    if event_type == "chat.overload_detected":
        return "minimum_next_step", "explicit_chat_overload"
    if event_type == "chat.low_motivation_detected":
        return "low_motivation", "explicit_chat_emotion"
    if event_type in {"plan.day_started_without_plan", "plan.collapsed"} or (
        event_type in {"app.evaluate", "app.inactive_returned"} and risk_flags.get("no_daily_plan")
    ):
        return "planning_rescue", "planning_missing"
    if event_type in {"pomodoro.completed", "session.meaningful_completed"}:
        return "reflection_prompt", "completed_focus_session"
    if any(word in text for word in ["学不进去", "不想学", "没动力", "坚持不下去", "太累了", "不想继续", "cannot study", "can't study"]):
        return "low_motivation", "text_low_motivation"
    if any(word in text for word in ["我很差", "很失败", "做不到", "崩溃", "烦死", "气死", "废物", "frustrated", "hopeless"]):
        return "frustration_support", "text_frustration"
    if any(word in text for word in ["太多了", "不知道先做什么", "无从下手", "来不及", "任务太多", "overwhelmed", "too much"]):
        return "minimum_next_step", "text_overload"
    if event_type in {"pomodoro.interrupted", "pomodoro.distracted"}:
        return "restart_after_interruption", "pomodoro_stopped"
    if event_type in {"task.overdue", "app.inactive_returned"} and (
        int((snapshot.get("tasks") or {}).get("overdue_task_count") or 0) > 0
        or due_review_count > 0
    ):
        return "minimum_next_step", "resume_or_overdue"
    if event_type == "review.debt_high" or risk_flags.get("review_debt_high") or due_review_count >= 6:
        return "review_debt_rescue", "review_due_threshold"
    return None, "no_matching_skill"


def _select_channel(event: dict[str, Any], preferences: dict[str, Any], skill_id: str | None) -> str:
    event_type = str(event.get("event_type") or "")
    source = str(event.get("source") or "")
    requested = str(event.get("channel") or "")
    if requested:
        channel = requested
    elif source == "chat" or event_type.startswith("chat."):
        channel = "chat_inline"
    elif source in {"agent", "agent_panel"}:
        channel = "agent_panel"
    elif skill_id == "review_debt_rescue":
        channel = "agent_panel"
    else:
        channel = "in_app_nudge"

    allowed = preferences.get("allowed_channels") or DEFAULT_ALLOWED_CHANNELS
    if not isinstance(allowed, list) or not allowed:
        allowed = DEFAULT_ALLOWED_CHANNELS
    if channel == "desktop_notification" and preferences.get("desktop_notifications_enabled") is not True:
        channel = "in_app_nudge"
    if channel not in allowed:
        channel = next((item for item in allowed if item in SUPPORTED_CHANNELS and item != "desktop_notification"), "in_app_nudge")
    return channel


def _recent_negative_count(skill_id: str, recent_feedback: list[dict[str, Any]]) -> int:
    count = 0
    for item in recent_feedback:
        if item.get("skill_id") != skill_id:
            continue
        if item.get("outcome") in NEGATIVE_OUTCOMES:
            count += 1
    return count


def _snoozed_until(skill_id: str, recent_feedback: list[dict[str, Any]], now: datetime) -> datetime | None:
    latest: datetime | None = None
    for item in recent_feedback:
        if item.get("skill_id") != skill_id:
            continue
        if item.get("outcome") not in {"later", "snoozed"}:
            continue
        snooze_until = _parse_iso_datetime(item.get("snooze_until"))
        if snooze_until and now < snooze_until and (latest is None or snooze_until > latest):
            latest = snooze_until
    return latest


def _skill_stat_score(stat: dict[str, Any], channel: str, event_type: str) -> tuple[int, int]:
    exactness = 0
    if str(stat.get("channel") or "") == channel:
        exactness += 2
    elif not stat.get("channel"):
        exactness += 1
    if str(stat.get("event_type") or "") == event_type:
        exactness += 2
    elif not stat.get("event_type"):
        exactness += 1
    total = sum(int(stat.get(key) or 0) for key in ("shown_count", "accepted_count", "completed_count", "helpful_count", "dismissed_count", "too_disruptive_count"))
    return exactness, total


def _stat_for_skill(
    skill_id: str,
    channel: str,
    event_type: str,
    skill_stats: list[dict[str, Any]] | None,
) -> dict[str, Any] | None:
    matches: list[dict[str, Any]] = []
    for item in skill_stats or []:
        if item.get("skill_id") != skill_id:
            continue
        stat_channel = str(item.get("channel") or "")
        stat_event_type = str(item.get("event_type") or "")
        if stat_channel and stat_channel != channel:
            continue
        if stat_event_type and stat_event_type != event_type:
            continue
        matches.append(item)
    if not matches:
        return None
    return max(matches, key=lambda item: _skill_stat_score(item, channel, event_type))


def _positive_signal(stat: dict[str, Any] | None) -> str | None:
    if not stat:
        return None
    shown = max(1, int(stat.get("shown_count") or 0))
    positive = sum(int(stat.get(key) or 0) for key in ("accepted_count", "completed_count", "helpful_count"))
    if positive >= 2 and positive / shown >= 0.5:
        return f"历史反馈偏正向 positive={positive}, shown={shown}"
    return None


def evaluate_coach_policy(
    event: dict[str, Any],
    snapshot: dict[str, Any],
    preferences: dict[str, Any] | None,
    recent_feedback: list[dict[str, Any]],
    skill_stats: list[dict[str, Any]] | None = None,
) -> dict[str, Any]:
    """Return a deterministic intervention decision before any skill generation."""

    now = _parse_iso_datetime(snapshot.get("generated_at")) or datetime.now()
    prefs = {**default_coach_preferences(), **(preferences or {})}
    if not prefs.get("enabled", True):
        return {
            "should_intervene": False,
            "intervention_type": None,
            "priority": "low",
            "skill_id": None,
            "channel": None,
            "cooldown_until": None,
            "reason": "coach_disabled",
            "evidence": ["Coach 已关闭"],
            "requires_confirmation": False,
        }

    skill_id, match_reason = _event_skill(event, snapshot)
    if not skill_id:
        return {
            "should_intervene": False,
            "intervention_type": None,
            "priority": "low",
            "skill_id": None,
            "channel": None,
            "cooldown_until": None,
            "reason": match_reason,
            "evidence": [],
            "requires_confirmation": False,
        }

    disabled = prefs.get("disabled_skill_ids") or []
    if isinstance(disabled, list) and skill_id in disabled:
        return {
            "should_intervene": False,
            "intervention_type": "nudge",
            "priority": "low",
            "skill_id": skill_id,
            "channel": None,
            "cooldown_until": None,
            "reason": "skill_disabled",
            "evidence": [f"{skill_id} 已被关闭"],
            "requires_confirmation": False,
        }

    snoozed_until = _snoozed_until(skill_id, recent_feedback, now)
    if snoozed_until and str(event.get("severity") or "") != "critical":
        return {
            "should_intervene": False,
            "intervention_type": "nudge",
            "priority": "low",
            "skill_id": skill_id,
            "channel": None,
            "cooldown_until": snoozed_until.isoformat(),
            "reason": "snoozed",
            "evidence": [f"{skill_id} 已稍后提醒，直到 {snoozed_until.strftime('%H:%M')}"],
            "requires_confirmation": False,
        }

    channel = _select_channel(event, prefs, skill_id)
    is_reactive_chat = channel == "chat_inline" or str(event.get("event_type") or "").startswith("chat.")
    if channel == "desktop_notification":
        if not prefs.get("desktop_notifications_enabled"):
            channel = "in_app_nudge"
        elif _is_quiet_time(now, prefs.get("quiet_hours_start"), prefs.get("quiet_hours_end")):
            return {
                "should_intervene": False,
                "intervention_type": "nudge",
                "priority": "low",
                "skill_id": skill_id,
                "channel": "desktop_notification",
                "cooldown_until": None,
                "reason": "quiet_hours",
                "evidence": ["当前处于免打扰时段"],
                "requires_confirmation": False,
            }

    severity = str(event.get("severity") or "info")
    priority = "high" if severity in {"warning", "high", "critical"} else "medium"
    if skill_id == "review_debt_rescue" and int((snapshot.get("review") or {}).get("due_review_count") or 0) >= 10:
        priority = "high"
    if channel == "agent_panel":
        priority = "low" if priority == "medium" else priority

    coach_state = snapshot.get("coach") or {}
    last_nudge_at = _parse_iso_datetime(coach_state.get("last_nudge_at"))
    min_minutes = max(0, int(prefs.get("min_minutes_between_nudges") or 60))
    if last_nudge_at and min_minutes > 0 and not is_reactive_chat:
        cooldown_until = last_nudge_at + timedelta(minutes=min_minutes)
        if now < cooldown_until and severity not in {"critical"}:
            return {
                "should_intervene": False,
                "intervention_type": "nudge",
                "priority": priority,
                "skill_id": skill_id,
                "channel": channel,
                "cooldown_until": cooldown_until.isoformat(),
                "reason": "cooldown_active",
                "evidence": [f"距离上次 Coach nudge 未满 {min_minutes} 分钟"],
                "requires_confirmation": False,
            }

    today_count = int(coach_state.get("today_nudge_count") or 0)
    max_per_day = max(1, int(prefs.get("max_nudges_per_day") or 3))
    if today_count >= max_per_day and priority != "high" and not is_reactive_chat:
        return {
            "should_intervene": False,
            "intervention_type": "nudge",
            "priority": priority,
            "skill_id": skill_id,
            "channel": channel,
            "cooldown_until": None,
            "reason": "daily_cap_reached",
            "evidence": [f"今日已达到 {max_per_day} 次 Coach nudge 上限"],
            "requires_confirmation": False,
        }

    event_type = str(event.get("event_type") or "")
    learned_stat = _stat_for_skill(skill_id, channel, event_type, skill_stats)
    too_disruptive_count = int((learned_stat or {}).get("too_disruptive_count") or 0)
    disruptive_score = float((learned_stat or {}).get("recent_score") or 0.0)
    if (
        learned_stat
        and too_disruptive_count >= 2
        and disruptive_score <= -2.0
        and not is_reactive_chat
        and severity != "critical"
    ):
        return {
            "should_intervene": False,
            "intervention_type": "nudge",
            "priority": "low",
            "skill_id": skill_id,
            "channel": channel,
            "cooldown_until": None,
            "reason": "learned_disruption_feedback",
            "evidence": [f"{skill_id} 在 {channel} 已有 {too_disruptive_count} 次被标记太打扰"],
            "requires_confirmation": False,
        }

    negative_count = _recent_negative_count(skill_id, recent_feedback)
    if negative_count >= 2 and not str(event.get("event_type") or "").startswith("chat."):
        return {
            "should_intervene": False,
            "intervention_type": "nudge",
            "priority": "low",
            "skill_id": skill_id,
            "channel": channel,
            "cooldown_until": None,
            "reason": "recent_negative_feedback",
            "evidence": [f"近期已有 {negative_count} 次类似建议被延后或拒绝"],
            "requires_confirmation": False,
        }

    evidence = [match_reason]
    if skill_id == "review_debt_rescue":
        evidence.append(f"due_review_count={int((snapshot.get('review') or {}).get('due_review_count') or 0)}")
    if skill_id == "restart_after_interruption":
        evidence.append(f"recent_interrupted_count={int((snapshot.get('learning') or {}).get('recent_interrupted_count') or 0)}")
    if skill_id == "planning_rescue":
        evidence.append(f"daily_plan_exists={bool((snapshot.get('daily_plan') or {}).get('has_content'))}")
    if skill_id == "reflection_prompt":
        evidence.append(f"today_completed_pomodoros={int((snapshot.get('learning') or {}).get('today_completed_pomodoros') or 0)}")
    positive_signal = _positive_signal(learned_stat)
    if positive_signal:
        evidence.append(positive_signal)

    return {
        "should_intervene": True,
        "intervention_type": "nudge",
        "priority": priority,
        "skill_id": skill_id,
        "channel": channel,
        "cooldown_until": None,
        "reason": "policy_allowed",
        "evidence": evidence,
        "requires_confirmation": False,
    }
