"""Readable weekly review drafts built from existing user-owned evidence."""
from __future__ import annotations

from datetime import datetime
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession

from app.services.learning_snapshot_service import build_learning_snapshot
from app.services.north_star_metrics_service import build_north_star_metrics


def _as_number(value: Any) -> float | int | None:
    if value is None:
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


async def build_weekly_learning_report(
    db: AsyncSession,
    user_id: int,
    *,
    time_zone: str = "UTC",
    now: datetime | None = None,
) -> dict[str, Any]:
    """Return a deterministic, non-writing review draft for the Agent page."""

    snapshot = await build_learning_snapshot(
        db,
        user_id,
        include_recent_notes=False,
        include_memories=False,
    )
    metrics = await build_north_star_metrics(
        db,
        user_id,
        days=28,
        time_zone=time_zone,
        now=now,
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
    return {
        "generated_at": (now or datetime.now()).isoformat(),
        "time_zone": time_zone,
        "headline": headline,
        "wins": wins[:3],
        "attention": attention[:3],
        "next_steps": next_steps[:3],
        "metrics": metric_values,
        "coverage": metrics.get("coverage") or {},
        "disclaimer": "这是基于你的学习记录生成的复盘草案；不会自动修改计划或创建任务。",
    }
