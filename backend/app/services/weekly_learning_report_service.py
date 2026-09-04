"""Readable weekly review and knowledge-consolidation drafts.

The service is intentionally read-only.  It gathers a bounded set of
user-owned evidence and returns Markdown that the learner may copy after
reviewing it; it never writes a Note or changes an Obsidian-backed source.
"""
from __future__ import annotations

from datetime import datetime, time, timedelta
from hashlib import sha256
import json
from typing import Any
from zoneinfo import ZoneInfo

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.note import Note
from app.models.question import ReviewSchedule, WrongQuestion
from app.services.coach_time_service import normalize_coach_time_zone
from app.services.learning_snapshot_service import build_learning_snapshot
from app.services.north_star_metrics_service import build_north_star_metrics
from app.utils.utc import UTC, to_db_utc, to_utc_iso, utc_now_db


CONSOLIDATION_VERSION = 1
SOURCE_LIMIT_PER_KIND = 8


def _as_number(value: Any) -> float | int | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


def _utc_iso(value: datetime | None) -> str | None:
    return to_utc_iso(value) if value is not None else None


def _compact_text(value: Any, limit: int = 160) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return f"{text[: max(0, limit - 1)].rstrip()}…"


def _markdown_text(value: Any, limit: int = 160) -> str:
    return _compact_text(value, limit).replace("[", "\\[").replace("]", "\\]")


def _weekly_bounds(now: datetime, time_zone: str) -> dict[str, Any]:
    clean_time_zone = normalize_coach_time_zone(time_zone)
    zone = ZoneInfo(clean_time_zone)
    current_utc = to_db_utc(now)
    local_now = current_utc.replace(tzinfo=UTC).astimezone(zone)
    local_start_date = local_now.date() - timedelta(days=local_now.weekday())
    local_end_date = local_start_date + timedelta(days=7)
    local_start = datetime.combine(local_start_date, time.min, tzinfo=zone)
    local_end = datetime.combine(local_end_date, time.min, tzinfo=zone)
    start_utc = to_db_utc(local_start)
    end_utc = to_db_utc(local_end)
    return {
        "time_zone": clean_time_zone,
        "local_start": local_start_date,
        "local_end": local_end_date,
        "start_utc": start_utc,
        "end_utc": end_utc,
        "scan_end_utc": min(current_utc, end_utc),
        "current_utc": current_utc,
    }


def _note_ownership(note: Note) -> str:
    if note.source_sync_state == "conflict":
        return "obsidian_conflict"
    if note.source_path or note.source_vault_id or note.source_file_id:
        return "obsidian_read_only"
    return "mnemox"


async def _collect_consolidation_sources(
    db: AsyncSession,
    user_id: int,
    *,
    start_utc: datetime,
    end_utc: datetime,
) -> tuple[list[dict[str, Any]], dict[str, int], dict[str, bool]]:
    note_observed_at = func.coalesce(Note.updated_at, Note.created_at)
    note_result = await db.execute(
        select(Note)
        .where(
            Note.user_id == user_id,
            note_observed_at >= start_utc,
            note_observed_at <= end_utc,
            or_(Note.source_sync_state.is_(None), Note.source_sync_state != "missing"),
        )
        .order_by(note_observed_at.desc(), Note.id.desc())
        .limit(SOURCE_LIMIT_PER_KIND + 1)
    )
    notes = note_result.scalars().all()

    review_result = await db.execute(
        select(ReviewSchedule)
        .where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.status == "completed",
            ReviewSchedule.is_archived.is_(False),
            ReviewSchedule.completed_at >= start_utc,
            ReviewSchedule.completed_at <= end_utc,
        )
        .order_by(ReviewSchedule.completed_at.desc(), ReviewSchedule.id.desc())
        .limit(SOURCE_LIMIT_PER_KIND + 1)
    )
    reviews = review_result.scalars().all()

    wrong_observed_at = func.coalesce(WrongQuestion.last_wrong_at, WrongQuestion.created_at)
    wrong_result = await db.execute(
        select(WrongQuestion)
        .where(
            WrongQuestion.user_id == user_id,
            wrong_observed_at >= start_utc,
            wrong_observed_at <= end_utc,
        )
        .order_by(wrong_observed_at.desc(), WrongQuestion.id.desc())
        .limit(SOURCE_LIMIT_PER_KIND + 1)
    )
    wrong_questions = wrong_result.scalars().all()

    truncated = {
        "notes": len(notes) > SOURCE_LIMIT_PER_KIND,
        "reviews": len(reviews) > SOURCE_LIMIT_PER_KIND,
        "wrong_questions": len(wrong_questions) > SOURCE_LIMIT_PER_KIND,
    }
    notes = notes[:SOURCE_LIMIT_PER_KIND]
    reviews = reviews[:SOURCE_LIMIT_PER_KIND]
    wrong_questions = wrong_questions[:SOURCE_LIMIT_PER_KIND]

    sources: list[dict[str, Any]] = []
    for note in notes:
        observed_at = note.updated_at or note.created_at
        content_fingerprint = sha256(
            f"{note.title or ''}\0{note.content or ''}".encode("utf-8")
        ).hexdigest()[:16]
        sources.append({
            "kind": "note",
            "id": int(note.id),
            "title": _compact_text(note.title or f"笔记 #{note.id}", 80),
            "excerpt": _compact_text(note.content, 160),
            "route": "/notes",
            "observed_at": _utc_iso(observed_at),
            "ownership": _note_ownership(note),
            "source_ref": f"note:{note.id}:{_utc_iso(observed_at)}:{content_fingerprint}",
        })

    for review in reviews:
        completed_at = review.completed_at
        sources.append({
            "kind": "review",
            "id": int(review.id),
            "title": f"已完成复习：{review.item_type or 'item'} #{review.item_id}",
            "excerpt": f"间隔 {int(review.interval_days or 0)} 天 · 质量 {review.last_quality if review.last_quality is not None else '未记录'}",
            "route": "/review",
            "observed_at": _utc_iso(completed_at),
            "ownership": "mnemox",
            "source_ref": (
                f"review:{review.id}:{_utc_iso(completed_at)}:"
                f"{review.item_type}:{review.item_id}:{review.last_quality}"
            ),
        })

    for wrong in wrong_questions:
        observed_at = wrong.last_wrong_at or wrong.created_at
        title = wrong.knowledge_point or f"错题 #{wrong.id}"
        wrong_fingerprint = sha256(
            json.dumps(
                {
                    "knowledge_point": _compact_text(wrong.knowledge_point, 80),
                    "wrong_count": int(wrong.wrong_count or 0),
                    "mastery_status": wrong.mastery_status,
                },
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
            ).encode("utf-8")
        ).hexdigest()[:16]
        sources.append({
            "kind": "wrong_question",
            "id": int(wrong.id),
            "title": _compact_text(title, 80),
            "excerpt": f"累计错误 {int(wrong.wrong_count or 0)} 次 · 掌握状态 {wrong.mastery_status or '未记录'}",
            "route": "/review",
            "observed_at": _utc_iso(observed_at),
            "ownership": "mnemox",
            "source_ref": (
                f"wrong-question:{wrong.id}:{_utc_iso(observed_at)}:{wrong_fingerprint}"
            ),
        })

    sources.sort(key=lambda item: (str(item.get("observed_at") or ""), item["kind"], item["id"]), reverse=True)
    counts = {
        "notes": len(notes),
        "reviews": len(reviews),
        "wrong_questions": len(wrong_questions),
        "total": len(sources),
    }
    return sources, counts, truncated


def _build_markdown(
    *,
    draft_key: str,
    week_start: str,
    week_end: str,
    time_zone: str,
    headline: str,
    wins: list[str],
    attention: list[str],
    next_steps: list[dict[str, Any]],
    sources: list[dict[str, Any]],
) -> str:
    lines = [
        f"# Mnemox 周度知识巩固 · {week_start}",
        "",
        f"> 范围：{week_start} 至 {week_end}（{time_zone}，结束日期不含）",
        f"> 草案键：`{draft_key}`",
        "> 只读草案：复制前请审阅；不会自动创建笔记或回写 Obsidian。",
        "",
        "## 本周结论",
        "",
        headline,
        "",
        "## 已形成的进展",
        "",
    ]
    lines.extend(f"- {_markdown_text(item)}" for item in wins)
    lines.extend(["", "## 需要继续巩固", ""])
    lines.extend(f"- {_markdown_text(item)}" for item in attention)
    if not attention:
        lines.append("- 当前证据中没有明显积压，继续保持小步节奏。")
    lines.extend(["", "## 下周最小行动", ""])
    for item in next_steps:
        lines.append(
            f"- [ ] {_markdown_text(item.get('title'), 100)}"
            f"（约 {int(item.get('estimated_minutes') or 0)} 分钟）— "
            f"{_markdown_text(item.get('reason'), 180)}"
        )
    lines.extend(["", "## 来源摘录", ""])
    if not sources:
        lines.append("- 本周暂未扫描到笔记、已完成复习或错题线索。")
    for source in sources:
        ownership = {
            "mnemox": "Mnemox",
            "obsidian_read_only": "Obsidian 只读来源",
            "obsidian_conflict": "Obsidian 冲突来源（只读）",
        }.get(str(source.get("ownership")), "只读来源")
        lines.append(
            f"- [{_markdown_text(source.get('kind'), 30)}] "
            f"{_markdown_text(source.get('title'), 100)} · {ownership} · "
            f"`{source.get('source_ref')}`"
        )
        if source.get("excerpt"):
            lines.append(f"  - 摘录：{_markdown_text(source['excerpt'], 180)}")
    lines.extend(["", "---", "由 Mnemox 生成的可复制草案；原始来源未被修改。", ""])
    return "\n".join(lines)


async def build_weekly_learning_report(
    db: AsyncSession,
    user_id: int,
    *,
    time_zone: str = "UTC",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a deterministic, non-writing review and consolidation draft."""

    observed_now = now if now is not None else utc_now_db()
    bounds = _weekly_bounds(observed_now, time_zone)
    clean_time_zone = str(bounds["time_zone"])
    snapshot = await build_learning_snapshot(
        db,
        user_id,
        now=bounds["current_utc"],
        include_profile=False,
        include_recent_notes=False,
        include_memories=False,
        time_zone=clean_time_zone,
    )
    metrics = await build_north_star_metrics(
        db,
        user_id,
        days=28,
        time_zone=clean_time_zone,
        now=bounds["current_utc"],
    )
    metric_values = metrics.get("metrics") or {}
    effective_sessions = int(
        ((metric_values.get("weekly_effective_study_sessions") or {}).get("value")) or 0
    )
    due_review_count = int((snapshot.get("review") or {}).get("due_review_count") or 0)
    overdue_task_count = int((snapshot.get("tasks") or {}).get("overdue_task_count") or 0)
    today_minutes = float((snapshot.get("learning") or {}).get("today_minutes") or 0)
    no_daily_plan = bool((snapshot.get("risk_flags") or {}).get("no_daily_plan"))
    suggestion_rate = _as_number((metric_values.get("suggestion_execution_rate") or {}).get("value"))

    wins: list[str] = []
    attention: list[str] = []
    next_steps: list[dict[str, Any]] = []
    if effective_sessions > 0:
        wins.append(f"本周已完成 {effective_sessions} 个至少 15 分钟的有效学习时段。")
    if today_minutes > 0:
        wins.append(f"今天已累计专注 {round(today_minutes)} 分钟，节奏已经启动。")
    if suggestion_rate is not None:
        wins.append(f"已成熟样本中的建议确认执行率为 {round(float(suggestion_rate))}%。")

    if due_review_count > 0:
        attention.append(f"还有 {due_review_count} 条到期复习；先清最旧的一条即可。")
        next_steps.append({
            "title": "完成最旧的 1 条到期复习",
            "reason": f"当前有 {due_review_count} 条到期复习，先降低积压而不是一次清空。",
            "route": "/review",
            "estimated_minutes": 10,
        })
    if overdue_task_count > 0:
        attention.append(f"有 {overdue_task_count} 个过期任务，建议只挑一个缩小到 10 分钟。")
        next_steps.append({
            "title": "为一个过期任务开 10 分钟番茄钟",
            "reason": "先恢复启动感，不补做整份待办清单。",
            "route": "/pomodoro",
            "estimated_minutes": 10,
        })
    if no_daily_plan:
        attention.append("今天还没有明确计划，下一步可以先确认一个最小计划草案。")
        next_steps.append({
            "title": "确认今天的最小计划",
            "reason": "只保留复习和一个核心任务，避免把计划排满。",
            "route": "/plans",
            "estimated_minutes": 5,
        })
    if not next_steps:
        next_steps.append({
            "title": "安排一次 15 分钟专注学习",
            "reason": "当前没有需要紧急处理的积压，保持一个小而稳定的学习节奏。",
            "route": "/pomodoro",
            "estimated_minutes": 15,
        })
    if not wins:
        wins.append("目前可用于复盘的数据还不多；完成一次 15 分钟学习后，报告会更具体。")

    headline = (
        "先清理最旧复习，再决定是否加量。"
        if due_review_count >= 6
        else "本周保持小而稳定的学习节奏。"
    )
    sources, source_counts, truncated = await _collect_consolidation_sources(
        db,
        user_id,
        start_utc=bounds["start_utc"],
        end_utc=bounds["scan_end_utc"],
    )
    week_start = bounds["local_start"].isoformat()
    week_end = bounds["local_end"].isoformat()
    digest_payload = {
        "version": CONSOLIDATION_VERSION,
        "user_id": user_id,
        "week_start": week_start,
        "week_end": week_end,
        "time_zone": clean_time_zone,
        "headline": headline,
        "wins": wins[:3],
        "attention": attention[:3],
        "next_steps": next_steps[:3],
        "sources": [source["source_ref"] for source in sources],
    }
    content_hash = sha256(
        json.dumps(digest_payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode("utf-8")
    ).hexdigest()
    draft_key = f"weekly-consolidation:{week_start}:{content_hash[:20]}"
    markdown = _build_markdown(
        draft_key=draft_key,
        week_start=week_start,
        week_end=week_end,
        time_zone=clean_time_zone,
        headline=headline,
        wins=wins[:3],
        attention=attention[:3],
        next_steps=next_steps[:3],
        sources=sources,
    )
    imported_source_count = sum(
        1 for source in sources if str(source.get("ownership", "")).startswith("obsidian_")
    )
    return {
        "generated_at": _utc_iso(bounds["current_utc"]),
        "time_zone": clean_time_zone,
        "headline": headline,
        "wins": wins[:3],
        "attention": attention[:3],
        "next_steps": next_steps[:3],
        "metrics": metric_values,
        "coverage": metrics.get("coverage") or {},
        "consolidation": {
            "version": CONSOLIDATION_VERSION,
            "draft_key": draft_key,
            "content_hash": content_hash,
            "week_start": week_start,
            "week_end_exclusive": week_end,
            "scan_start_utc": _utc_iso(bounds["start_utc"]),
            "scan_end_utc": _utc_iso(bounds["scan_end_utc"]),
            "scan_end_inclusive": True,
            "source_counts": source_counts,
            "source_limit_per_kind": SOURCE_LIMIT_PER_KIND,
            "truncated": truncated,
            "sources": sources,
            "markdown": markdown,
            "write_policy": {
                "mode": "copy_only",
                "automatic_write": False,
                "obsidian_write_allowed": False,
                "imported_source_count": imported_source_count,
                "rollback": "本次生成没有产生持久化写入；关闭或丢弃草案即可。",
            },
        },
        "disclaimer": "这是基于你的学习记录生成的只读复盘草案；不会自动修改计划或创建任务，也不会回写 Obsidian。",
    }
