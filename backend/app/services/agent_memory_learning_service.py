"""Deterministic Agent long-memory learning from normalized events."""
from __future__ import annotations

import json
from collections import Counter, defaultdict
from datetime import datetime, timedelta
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.learning_event import LearningEvent
from app.models.memory import UserMemory
from app.services.agent_long_memory_service import (
    CONFIRMED,
    STAGED,
    rebuild_core_profile,
    upsert_agent_memory,
)

CHECKPOINT_KEY = "agent_memory_learning_checkpoint"


def _now() -> datetime:
    return datetime.now()


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _payload(event: LearningEvent) -> dict[str, Any]:
    return event.event_data if isinstance(event.event_data, dict) else {}


def _safe_title(value: Any, limit: int = 80) -> str:
    text = " ".join(str(value or "").split())
    return text[:limit]


def _event_to_evidence(event: LearningEvent, *, include_payload_title: bool = True) -> dict[str, Any]:
    payload = _payload(event)
    evidence = {
        "event_id": event.id,
        "event_type": event.event_type,
        "timestamp": _to_iso(event.timestamp),
        "goal_id": event.goal_id,
        "task_id": event.task_id,
        "note_id": event.note_id,
        "material_id": event.material_id,
    }
    if include_payload_title and payload.get("title"):
        evidence["title"] = _safe_title(payload.get("title"))
    return {key: value for key, value in evidence.items() if value is not None}


async def get_learning_checkpoint(db: AsyncSession, user_id: int) -> dict[str, Any]:
    result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.memory_key == CHECKPOINT_KEY)
    )
    row = result.scalar_one_or_none()
    if not row:
        return {"last_event_id": 0, "last_event_at": None}
    payload = _json_loads(row.memory_value, {})
    return {
        "last_event_id": int(payload.get("last_event_id") or 0),
        "last_event_at": payload.get("last_event_at"),
    }


async def _set_learning_checkpoint(
    db: AsyncSession,
    user_id: int,
    *,
    last_event_id: int,
    last_event_at: str | None,
) -> UserMemory:
    payload = {
        "last_event_id": int(last_event_id or 0),
        "last_event_at": last_event_at,
        "updated_at": _now().isoformat(),
    }
    return await upsert_agent_memory(
        db,
        user_id,
        memory_key=CHECKPOINT_KEY,
        memory_value=_json_dumps(payload),
        category="system",
        confidence=1.0,
        review_status=CONFIRMED,
        status="ignored",
        source_type="agent_memory_learning",
        source_id=CHECKPOINT_KEY,
        evidence=[{"kind": "checkpoint"}],
        memory_type="semantic",
        lock=True,
        respect_lock=False,
    )


async def _events_since_checkpoint(db: AsyncSession, user_id: int, last_event_id: int) -> list[LearningEvent]:
    result = await db.execute(
        select(LearningEvent)
        .where(LearningEvent.user_id == user_id, LearningEvent.id > last_event_id)
        .order_by(LearningEvent.id.asc())
        .limit(500)
    )
    return list(result.scalars().all())


def _aggregate_candidates(events: list[LearningEvent]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    type_counts = Counter(event.event_type for event in events)
    category_counts = Counter(event.event_category for event in events if event.event_category)

    if events:
        top_type, top_count = type_counts.most_common(1)[0]
        candidates.append(
            {
                "memory_key": "agent_recent_learning_activity",
                "memory_value": f"最近新增 {len(events)} 条学习事件，最常见事件是 {top_type}（{top_count} 次）。",
                "category": "pattern",
                "confidence": 0.72,
                "review_status": CONFIRMED,
                "source_type": "learning_event_aggregate",
                "source_id": f"events:{events[0].id}-{events[-1].id}:activity",
                "evidence": [{"kind": "aggregate", "event_count": len(events), "top_event_type": top_type}],
            }
        )

    if category_counts:
        top_category, top_count = category_counts.most_common(1)[0]
        candidates.append(
            {
                "memory_key": "agent_dominant_learning_category",
                "memory_value": f"近期学习行为以 {top_category} 类为主（{top_count}/{len(events)}）。",
                "category": "pattern",
                "confidence": 0.7,
                "review_status": CONFIRMED,
                "source_type": "learning_event_aggregate",
                "source_id": f"events:{events[0].id}-{events[-1].id}:category",
                "evidence": [{"kind": "aggregate", "category": top_category, "count": top_count}],
            }
        )

    duration_by_type: defaultdict[str, int] = defaultdict(int)
    for event in events:
        if event.duration:
            duration_by_type[event.event_type] += int(event.duration or 0)
    if duration_by_type:
        top_duration_type, seconds = max(duration_by_type.items(), key=lambda item: (item[1], item[0]))
        minutes = max(1, round(seconds / 60))
        candidates.append(
            {
                "memory_key": "agent_time_investment_pattern",
                "memory_value": f"近期时间投入最多的是 {top_duration_type}，约 {minutes} 分钟。",
                "category": "pattern",
                "confidence": 0.74,
                "review_status": CONFIRMED,
                "source_type": "learning_event_aggregate",
                "source_id": f"events:{events[0].id}-{events[-1].id}:duration",
                "evidence": [{"kind": "aggregate", "event_type": top_duration_type, "duration_seconds": seconds}],
            }
        )

    return candidates


def _subjective_or_raw_candidates(events: list[LearningEvent]) -> list[dict[str, Any]]:
    candidates: list[dict[str, Any]] = []
    for event in events:
        payload = _payload(event)
        event_type = event.event_type or ""

        if event_type.startswith("note."):
            title = _safe_title(payload.get("title") or f"笔记 {event.note_id or event.id}")
            candidates.append(
                {
                    "memory_key": f"agent_note_signal_{event.id}",
                    "memory_value": f"用户新增或更新了笔记：{title}。内容需人工确认后再沉淀为长期偏好或知识状态。",
                    "category": "note_signal",
                    "confidence": 0.55,
                    "review_status": STAGED,
                    "source_type": "learning_event",
                    "source_id": str(event.id),
                    "evidence": [_event_to_evidence(event, include_payload_title=True)],
                }
            )

        if event_type in {"agent.action_feedback", "agent.feedback"}:
            outcome = _safe_title(payload.get("outcome"), 40)
            reason = _safe_title(payload.get("reason_code"), 40)
            value = "用户对 Agent 建议给出了反馈"
            if outcome:
                value += f"：{outcome}"
            if reason:
                value += f"（{reason}）"
            value += "。是否代表稳定偏好需人工确认。"
            candidates.append(
                {
                    "memory_key": f"agent_feedback_signal_{event.id}",
                    "memory_value": value,
                    "category": "agent_feedback",
                    "confidence": 0.6,
                    "review_status": STAGED,
                    "source_type": "learning_event",
                    "source_id": str(event.id),
                    "evidence": [_event_to_evidence(event, include_payload_title=False)],
                }
            )

        if event_type in {"goal.created", "goal.updated"} and payload.get("title"):
            title = _safe_title(payload.get("title"))
            candidates.append(
                {
                    "memory_key": f"agent_goal_signal_{event.goal_id or event.id}",
                    "memory_value": f"用户近期关注目标：{title}。",
                    "category": "goal",
                    "confidence": 0.65,
                    "review_status": STAGED,
                    "source_type": "learning_event",
                    "source_id": str(event.id),
                    "evidence": [_event_to_evidence(event, include_payload_title=True)],
                }
            )

    return candidates


async def run_agent_memory_learning(
    db: AsyncSession,
    user_id: int,
    *,
    rebuild_profile: bool = True,
) -> dict[str, Any]:
    """Learn from new events since checkpoint.

    Low-risk aggregate memories are auto-confirmed. Subjective or raw-note-derived
    signals are staged for review. Running with no events is a no-op that still
    ensures the checkpoint row exists.
    """

    checkpoint = await get_learning_checkpoint(db, user_id)
    last_event_id = int(checkpoint.get("last_event_id") or 0)
    events = await _events_since_checkpoint(db, user_id, last_event_id)

    if not events:
        checkpoint_row = await _set_learning_checkpoint(
            db,
            user_id,
            last_event_id=last_event_id,
            last_event_at=checkpoint.get("last_event_at"),
        )
        profile = await rebuild_core_profile(db, user_id) if rebuild_profile else None
        return {
            "ok": True,
            "processed_event_count": 0,
            "scanned_events": 0,
            "auto_confirmed_count": 0,
            "confirmed": 0,
            "staged_count": 0,
            "staged": 0,
            "created": 0,
            "candidate_count": 0,
            "checkpoint": _json_loads(checkpoint_row.memory_value, {}),
            "core_profile": profile,
        }

    candidates = _aggregate_candidates(events) + _subjective_or_raw_candidates(events)
    auto_confirmed = 0
    staged = 0
    written_ids: list[int] = []
    for candidate in candidates:
        row = await upsert_agent_memory(
            db,
            user_id,
            memory_key=candidate["memory_key"],
            memory_value=candidate["memory_value"],
            category=candidate["category"],
            confidence=candidate["confidence"],
            review_status=candidate["review_status"],
            status="active" if candidate["review_status"] == CONFIRMED else "staged",
            source_type=candidate.get("source_type"),
            source_id=candidate.get("source_id"),
            evidence=candidate.get("evidence") or [],
            memory_type="semantic",
        )
        written_ids.append(int(row.id))
        if candidate["review_status"] == CONFIRMED:
            auto_confirmed += 1
        else:
            staged += 1

    newest = events[-1]
    checkpoint_row = await _set_learning_checkpoint(
        db,
        user_id,
        last_event_id=int(newest.id or 0),
        last_event_at=_to_iso(newest.timestamp),
    )
    profile = await rebuild_core_profile(db, user_id) if rebuild_profile else None
    return {
        "ok": True,
        "processed_event_count": len(events),
        "scanned_events": len(events),
        "auto_confirmed_count": auto_confirmed,
        "confirmed": auto_confirmed,
        "staged_count": staged,
        "staged": staged,
        "created": len(written_ids),
        "candidate_count": len(written_ids),
        "memory_ids": written_ids,
        "checkpoint": _json_loads(checkpoint_row.memory_value, {}),
        "core_profile": profile,
    }


async def run_agent_memory_learning_if_due(
    db: AsyncSession,
    user_id: int,
    *,
    now: datetime | None = None,
    interval_hours: int = 6,
) -> dict[str, Any] | None:
    """Run the deterministic learner when the checkpoint is older than interval."""

    current = now or _now()
    checkpoint = await get_learning_checkpoint(db, user_id)
    updated_at = _json_loads(str(checkpoint.get("updated_at") or ""), None)
    # Backward compatibility: older checkpoints did not expose updated_at via get_learning_checkpoint.
    result = await db.execute(
        select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.memory_key == CHECKPOINT_KEY)
    )
    row = result.scalar_one_or_none()
    if row:
        payload = _json_loads(row.memory_value, {})
        updated_at = payload.get("updated_at") or updated_at
        try:
            last_run = datetime.fromisoformat(str(updated_at))
            if current - last_run < timedelta(hours=max(1, interval_hours)):
                return None
        except Exception:
            pass
    return await run_agent_memory_learning(db, user_id)
