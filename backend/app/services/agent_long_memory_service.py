"""Durable Agent long-memory helpers.

This layer stores reviewable Agent memory candidates in UserMemory while keeping
all operations explicitly user-scoped.
"""
from __future__ import annotations

import json
import re
from datetime import datetime
from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.memory import UserMemory

CORE_PROFILE_KEY = "agent_core_profile"
CORE_PROFILE_CATEGORY = "system"
CORE_PROFILE_TYPE = "profile"

CONFIRMED = "confirmed"
STAGED = "staged"
IGNORED = "ignored"
INACCURATE = "inaccurate"

SENSITIVE_PATTERNS = [
    r"sk-[A-Za-z0-9_-]{12,}",
    r"AKIA[0-9A-Z]{16}",
    r"(?i)(password|passwd|secret|token|api[_-]?key)\s*[:=]",
]


def _now() -> datetime:
    return datetime.now()


def _clamp_confidence(value: Any, default: float = 0.75) -> float:
    try:
        parsed = float(value)
    except (TypeError, ValueError):
        parsed = default
    return max(0.0, min(1.0, parsed))


def _compact_text(value: Any, limit: int = 500) -> str:
    return re.sub(r"\s+", " ", str(value or "")).strip()[:limit]


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True)


def _stable_key(text: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9\u4e00-\u9fff]+", "_", text.lower()).strip("_")
    if not normalized:
        normalized = "agent_memory"
    return normalized[:72]


def _sanitize_profile_value(value: Any, limit: int = 160) -> str:
    text = _compact_text(value, limit)
    for pattern in SENSITIVE_PATTERNS:
        text = re.sub(pattern, "[redacted]", text)
    return text


def _json_object(value: str | None) -> dict[str, Any] | None:
    parsed = _json_loads(value, None)
    return parsed if isinstance(parsed, dict) else None


def _profile_values_from_memory(memory: UserMemory) -> list[str]:
    """Extract concise profile-safe values without dumping internal JSON blobs."""

    key = memory.memory_key or ""
    category = memory.category or "preference"
    payload = _json_object(memory.memory_value)
    values: list[str] = []

    if key == "agent_learning_profile" and payload:
        for item in (payload.get("summary") or [])[:3]:
            if isinstance(item, str):
                values.append(f"画像摘要：{item}")
        for item in (payload.get("learned_preferences") or [])[:3]:
            if isinstance(item, str):
                values.append(f"偏好：{item}")
        for trait in (payload.get("traits") or [])[:3]:
            if isinstance(trait, dict) and trait.get("text"):
                values.append(f"画像特征：{trait.get('text')}")
        return [_sanitize_profile_value(value) for value in values if _sanitize_profile_value(value)]

    if category in {"agent_feedback", "coach_feedback"} and payload:
        outcome = payload.get("outcome")
        reason = payload.get("reason_code") or payload.get("reason_label")
        action_type = payload.get("action_type")
        topic = payload.get("topic") or payload.get("knowledge_point") or payload.get("skill_id")
        parts = []
        if topic:
            parts.append(str(topic))
        if action_type:
            parts.append(str(action_type))
        if outcome:
            parts.append(f"反馈 {outcome}")
        if reason:
            parts.append(f"原因 {reason}")
        compact = "，".join(parts)
        return [_sanitize_profile_value(compact)] if compact else []

    if payload:
        # Unknown structured memory values are internal implementation details;
        # avoid leaking raw JSON into the core profile.
        return []

    value = _sanitize_profile_value(memory.memory_value)
    return [value] if value and value != "[redacted]" else []


def memory_to_dict(memory: UserMemory) -> dict[str, Any]:
    return {
        "id": memory.id,
        "user_id": memory.user_id,
        "memory_key": memory.memory_key,
        "memory_value": memory.memory_value,
        "category": memory.category,
        "confidence": memory.confidence,
        "status": memory.status,
        "is_locked": int(getattr(memory, "is_locked", 0) or 0),
        "source_conversation_id": memory.source_conversation_id,
        "source_type": getattr(memory, "source_type", None),
        "source_id": getattr(memory, "source_id", None),
        "evidence": _json_loads(getattr(memory, "evidence", None), []),
        "expires_at": memory.expires_at.isoformat() if getattr(memory, "expires_at", None) else None,
        "review_status": getattr(memory, "review_status", None) or CONFIRMED,
        "material_id": getattr(memory, "material_id", None),
        "memory_type": getattr(memory, "memory_type", "semantic") or "semantic",
        "last_seen_at": memory.last_seen_at.isoformat() if memory.last_seen_at else None,
        "created_at": memory.created_at.isoformat() if memory.created_at else None,
        "updated_at": memory.updated_at.isoformat() if memory.updated_at else None,
    }


async def upsert_agent_memory(
    db: AsyncSession,
    user_id: int,
    *,
    memory_key: str,
    memory_value: str,
    category: str = "preference",
    confidence: float = 0.75,
    review_status: str = CONFIRMED,
    status: str = "active",
    source_type: str | None = None,
    source_id: str | None = None,
    evidence: list[dict[str, Any]] | dict[str, Any] | None = None,
    memory_type: str = "semantic",
    material_id: int | None = None,
    expires_at: datetime | None = None,
    lock: bool | None = None,
    respect_lock: bool = True,
) -> UserMemory:
    """Create or update a user-scoped Agent memory unless an existing row is locked."""

    clean_key = _compact_text(memory_key, 100) or _stable_key(memory_value)
    clean_value = _compact_text(memory_value, 2000)
    if not clean_value:
        raise ValueError("memory_value 不能为空")
    clean_review = review_status if review_status in {STAGED, CONFIRMED, IGNORED, INACCURATE} else CONFIRMED
    clean_status = status if status in {"active", "staged", "ignored"} else "active"
    if clean_review == STAGED and clean_status != "ignored":
        clean_status = "staged"
    clean_type = memory_type if memory_type in {"semantic", "episodic", "profile"} else "semantic"

    conditions = [UserMemory.user_id == user_id, UserMemory.memory_key == clean_key]
    if source_type and source_id:
        conditions = [
            UserMemory.user_id == user_id,
            UserMemory.source_type == source_type[:50],
            UserMemory.source_id == source_id[:100],
        ]

    result = await db.execute(select(UserMemory).where(*conditions).order_by(UserMemory.id.desc()).limit(1))
    row = result.scalar_one_or_none()
    now = _now()
    evidence_value = _json_dumps(evidence or [])

    if row:
        if respect_lock and int(getattr(row, "is_locked", 0) or 0) == 1:
            row.last_seen_at = now
            return row
        row.memory_key = clean_key
        row.memory_value = clean_value
        row.category = _compact_text(category, 50) or "preference"
        row.confidence = max(float(row.confidence or 0.0), _clamp_confidence(confidence))
        row.status = clean_status
        row.review_status = clean_review
        row.source_type = source_type[:50] if source_type else None
        row.source_id = source_id[:100] if source_id else None
        row.evidence = evidence_value
        row.memory_type = clean_type
        row.material_id = material_id
        row.expires_at = expires_at
        row.last_seen_at = now
        if lock is not None:
            row.is_locked = 1 if lock else 0
    else:
        row = UserMemory(
            user_id=user_id,
            memory_key=clean_key,
            memory_value=clean_value,
            category=_compact_text(category, 50) or "preference",
            confidence=_clamp_confidence(confidence),
            status=clean_status,
            is_locked=1 if lock else 0,
            source_type=source_type[:50] if source_type else None,
            source_id=source_id[:100] if source_id else None,
            evidence=evidence_value,
            expires_at=expires_at,
            review_status=clean_review,
            material_id=material_id,
            memory_type=clean_type,
            last_seen_at=now,
        )
        db.add(row)

    await db.flush()
    await db.refresh(row)
    return row


async def list_agent_memories(
    db: AsyncSession,
    user_id: int,
    *,
    review_status: str | None = None,
    include_ignored: bool = False,
    limit: int = 100,
) -> list[dict[str, Any]]:
    query = select(UserMemory).where(UserMemory.user_id == user_id)
    if review_status:
        query = query.where(UserMemory.review_status == review_status)
    if not include_ignored:
        if review_status == STAGED:
            query = query.where(UserMemory.status.in_(("active", "staged")))
        else:
            query = query.where(UserMemory.status == "active")
    result = await db.execute(
        query.order_by(UserMemory.last_seen_at.desc(), UserMemory.updated_at.desc(), UserMemory.id.desc())
        .limit(max(1, min(int(limit or 100), 200)))
    )
    return [memory_to_dict(row) for row in result.scalars().all()]


async def list_memory_candidates(db: AsyncSession, user_id: int, *, limit: int = 100) -> list[dict[str, Any]]:
    return await list_agent_memories(db, user_id, review_status=STAGED, include_ignored=False, limit=limit)


async def _get_user_memory(db: AsyncSession, user_id: int, memory_id: int) -> UserMemory:
    result = await db.execute(select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.id == memory_id))
    row = result.scalar_one_or_none()
    if not row:
        raise ValueError("记忆不存在")
    return row


async def _get_staged_candidate(db: AsyncSession, user_id: int, memory_id: int) -> UserMemory:
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.id == memory_id,
            UserMemory.review_status == STAGED,
            UserMemory.status.in_(("staged", "active")),
            UserMemory.category != CORE_PROFILE_CATEGORY,
            UserMemory.memory_key.notin_((CORE_PROFILE_KEY, "agent_memory_learning_checkpoint")),
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        raise ValueError("待确认记忆不存在或状态已变化")
    return row


async def confirm_memory_candidate(db: AsyncSession, user_id: int, memory_id: int, *, lock: bool = False) -> dict[str, Any]:
    row = await _get_staged_candidate(db, user_id, memory_id)
    row.review_status = CONFIRMED
    row.status = "active"
    row.last_seen_at = _now()
    if lock:
        row.is_locked = 1
    await db.flush()
    await db.refresh(row)
    return memory_to_dict(row)


async def ignore_memory_candidate(
    db: AsyncSession,
    user_id: int,
    memory_id: int,
    *,
    reason: str = IGNORED,
) -> dict[str, Any]:
    row = await _get_staged_candidate(db, user_id, memory_id)
    row.review_status = INACCURATE if reason == INACCURATE else IGNORED
    row.status = "ignored"
    row.last_seen_at = _now()
    await db.flush()
    await db.refresh(row)
    return memory_to_dict(row)


async def set_memory_lock(db: AsyncSession, user_id: int, memory_id: int, locked: bool) -> dict[str, Any]:
    row = await _get_user_memory(db, user_id, memory_id)
    row.is_locked = 1 if locked else 0
    row.last_seen_at = _now()
    await db.flush()
    await db.refresh(row)
    return memory_to_dict(row)


async def get_core_profile(db: AsyncSession, user_id: int) -> dict[str, Any]:
    result = await db.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.memory_key == CORE_PROFILE_KEY,
            UserMemory.status == "active",
            UserMemory.review_status == CONFIRMED,
            UserMemory.category == CORE_PROFILE_CATEGORY,
            UserMemory.memory_type == CORE_PROFILE_TYPE,
        )
        .order_by(UserMemory.updated_at.desc(), UserMemory.id.desc())
        .limit(1)
    )
    row = result.scalar_one_or_none()
    if not row:
        payload = {"summary": [], "updated_at": None, "source_memory_ids": []}
        return {"memory": None, "profile": payload}
    return {"memory": memory_to_dict(row), "profile": _json_loads(row.memory_value, {})}


async def rebuild_core_profile(db: AsyncSession, user_id: int) -> dict[str, Any]:
    """Build a compact, sanitized profile from confirmed active memories."""

    result = await db.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.review_status == CONFIRMED,
            UserMemory.memory_key != CORE_PROFILE_KEY,
            UserMemory.category != "system",
        )
        .order_by(UserMemory.confidence.desc(), UserMemory.last_seen_at.desc(), UserMemory.id.desc())
        .limit(80)
    )
    rows = result.scalars().all()
    groups: dict[str, list[str]] = {}
    source_ids: list[int] = []
    for row in rows:
        category = row.category or "preference"
        values = _profile_values_from_memory(row)
        if not values:
            continue
        groups.setdefault(category, [])
        for value in values:
            if value not in groups[category]:
                groups[category].append(value)
        source_ids.append(int(row.id))

    ordered_categories = ["goal", "weakness", "style", "preference", "pattern", "agent_feedback"]
    summary: list[dict[str, Any]] = []
    for category in ordered_categories + sorted(set(groups) - set(ordered_categories)):
        values = groups.get(category) or []
        if values:
            summary.append({"category": category, "items": values[:5]})

    payload = {
        "summary": summary[:12],
        "updated_at": _now().isoformat(),
        "source_memory_ids": source_ids[:80],
        "safety": "sanitized_no_raw_note_bodies_or_secrets",
    }
    memory = await upsert_agent_memory(
        db,
        user_id,
        memory_key=CORE_PROFILE_KEY,
        memory_value=_json_dumps(payload),
        category=CORE_PROFILE_CATEGORY,
        confidence=1.0,
        review_status=CONFIRMED,
        status="active",
        source_type="agent_memory",
        source_id=CORE_PROFILE_KEY,
        evidence=[{"kind": "aggregate", "source_memory_count": len(source_ids)}],
        memory_type=CORE_PROFILE_TYPE,
        lock=True,
        respect_lock=False,
    )
    return {"memory": memory_to_dict(memory), "profile": payload}
