"""AI 主动干预（每日学习报告/推送建议）路由"""
from __future__ import annotations

from datetime import date, datetime, timedelta
from typing import List, Literal

from fastapi import APIRouter, Depends, Query
from pydantic import BaseModel
from sqlalchemy import func, select, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.goal import Goal, Task
from app.models.pomodoro import Pomodoro
from app.models.question import ReviewSchedule
from app.models.user import User
from app.ai.factory import AIProviderFactory

router = APIRouter()


class DailyInterventionReport(BaseModel):
    date: str
    risk_level: Literal["low", "medium", "high"]
    should_push: bool
    summary: str
    push_title: str
    push_body: str
    highlights: List[str]
    suggestions: List[str]
    stats: dict


def _risk_level(today_minutes: float, pending_count: int, due_review_count: int, completion_rate: float) -> str:
    risk_score = 0
    if today_minutes < 30:
        risk_score += 2
    elif today_minutes < 60:
        risk_score += 1
    if pending_count >= 8:
        risk_score += 2
    elif pending_count >= 4:
        risk_score += 1
    if due_review_count >= 6:
        risk_score += 2
    elif due_review_count >= 3:
        risk_score += 1
    if completion_rate < 0.3:
        risk_score += 1

    if risk_score >= 5:
        return "high"
    if risk_score >= 3:
        return "medium"
    return "low"


def _build_template_report(
    *,
    target_date: date,
    today_minutes: float,
    pomodoro_count: int,
    total_tasks: int,
    completed_tasks: int,
    pending_tasks: int,
    due_review_count: int,
    risk_level: str,
) -> DailyInterventionReport:
    completion_rate = (completed_tasks / total_tasks) if total_tasks > 0 else 0.0
    highlights = [
        f"今日学习时长：{today_minutes:.1f} 分钟（番茄钟 {pomodoro_count} 个）",
        f"任务完成：{completed_tasks}/{total_tasks}（完成率 {completion_rate * 100:.1f}%）",
        f"待处理复习：{due_review_count} 条",
    ]

    suggestions: List[str] = []
    if today_minutes < 30:
        suggestions.append("先做一个 25 分钟专注块，立刻降低拖延成本。")
    elif today_minutes < 90:
        suggestions.append("再补一个 25~45 分钟专注块，巩固今天节奏。")

    if due_review_count > 0:
        suggestions.append("优先清空到期复习（先做最旧的 3 条），避免遗忘曲线继续下滑。")

    if pending_tasks >= 4:
        suggestions.append("从待办里只挑 1 个“最小可完成任务”，先拿到一次完成反馈。")

    if not suggestions:
        suggestions.append("今天状态不错，保持当前节奏，明天继续同一时段开工。")

    if risk_level == "high":
        title = "学习预警：建议立即做一个25分钟专注块"
        body = "今天进度偏慢，先完成 1 个最小任务 + 3 条复习，避免积压。"
        summary = "系统检测到你今天有明显的学习积压风险，建议立即进行一次短时专注并优先清理复习。"
    elif risk_level == "medium":
        title = "进度提醒：再完成一个专注块会更稳"
        body = "你已启动学习，建议补 1 个专注块并处理到期复习。"
        summary = "今天进度中等，若补一次专注并清理关键复习，整体节奏会明显改善。"
    else:
        title = "状态不错：保持节奏继续前进"
        body = "你今天完成情况良好，继续当前节奏即可。"
        summary = "今天整体学习状态稳定，建议延续当前节奏并做一次轻量复盘。"

    return DailyInterventionReport(
        date=target_date.isoformat(),
        risk_level=risk_level,  # type: ignore[arg-type]
        should_push=risk_level != "low",
        summary=summary,
        push_title=title,
        push_body=body,
        highlights=highlights,
        suggestions=suggestions,
        stats={
            "today_minutes": round(today_minutes, 1),
            "pomodoro_count": pomodoro_count,
            "total_tasks": total_tasks,
            "completed_tasks": completed_tasks,
            "pending_tasks": pending_tasks,
            "due_review_count": due_review_count,
            "completion_rate": round(completion_rate, 4),
        },
    )


async def _collect_daily_stats(db: AsyncSession, user_id: int, target_date: date) -> dict:
    today_str = target_date.isoformat()

    pomodoro_result = await db.execute(
        select(
            func.coalesce(func.sum(Pomodoro.duration), 0.0),
            func.count(Pomodoro.id),
        ).where(
            Pomodoro.user_id == user_id,
            func.date(Pomodoro.started_at) == today_str,
        )
    )
    today_minutes, pomodoro_count = pomodoro_result.one()

    task_result = await db.execute(
        select(
            func.count(Task.id),
            func.coalesce(func.sum(case((Task.status == "completed", 1), else_=0)), 0),
        )
        .select_from(Task)
        .join(Goal, Goal.id == Task.goal_id)
        .where(
            Goal.user_id == user_id,
            Task.planned_date == target_date,
        )
    )
    total_tasks, completed_tasks = task_result.one()
    pending_tasks = max(0, int(total_tasks or 0) - int(completed_tasks or 0))

    now = datetime.now()
    due_result = await db.execute(
        select(func.count(ReviewSchedule.id)).where(
            and_(
                ReviewSchedule.user_id == user_id,
                ReviewSchedule.status == "pending",
                ReviewSchedule.scheduled_date <= now,
                ReviewSchedule.is_archived == False,
            )
        )
    )
    due_review_count = int(due_result.scalar() or 0)

    return {
        "today_minutes": float(today_minutes or 0.0),
        "pomodoro_count": int(pomodoro_count or 0),
        "total_tasks": int(total_tasks or 0),
        "completed_tasks": int(completed_tasks or 0),
        "pending_tasks": pending_tasks,
        "due_review_count": due_review_count,
    }


@router.get("/daily", response_model=DailyInterventionReport)
async def get_daily_intervention(
    days_offset: int = Query(0, ge=-30, le=30, description="相对今天的偏移天数"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_date = date.today() + timedelta(days=days_offset)
    user_id = int(current_user.id)
    stats = await _collect_daily_stats(db, user_id, target_date)

    total_tasks = stats["total_tasks"]
    completed_tasks = stats["completed_tasks"]
    completion_rate = (completed_tasks / total_tasks) if total_tasks > 0 else 0.0
    risk = _risk_level(
        stats["today_minutes"],
        stats["pending_tasks"],
        stats["due_review_count"],
        completion_rate,
    )

    return _build_template_report(
        target_date=target_date,
        today_minutes=stats["today_minutes"],
        pomodoro_count=stats["pomodoro_count"],
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=stats["pending_tasks"],
        due_review_count=stats["due_review_count"],
        risk_level=risk,
    )


@router.post("/daily/generate", response_model=DailyInterventionReport)
async def generate_daily_intervention(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    target_date = date.today()
    user_id = int(current_user.id)
    stats = await _collect_daily_stats(db, user_id, target_date)

    total_tasks = stats["total_tasks"]
    completed_tasks = stats["completed_tasks"]
    completion_rate = (completed_tasks / total_tasks) if total_tasks > 0 else 0.0
    risk = _risk_level(
        stats["today_minutes"],
        stats["pending_tasks"],
        stats["due_review_count"],
        completion_rate,
    )

    base_report = _build_template_report(
        target_date=target_date,
        today_minutes=stats["today_minutes"],
        pomodoro_count=stats["pomodoro_count"],
        total_tasks=total_tasks,
        completed_tasks=completed_tasks,
        pending_tasks=stats["pending_tasks"],
        due_review_count=stats["due_review_count"],
        risk_level=risk,
    )

    ai_prompt = (
        "你是学习教练，请基于以下数据生成『主动干预推送』。\n"
        f"日期: {target_date.isoformat()}\n"
        f"学习时长(分钟): {stats['today_minutes']:.1f}\n"
        f"番茄钟个数: {stats['pomodoro_count']}\n"
        f"任务完成: {completed_tasks}/{total_tasks}\n"
        f"待办任务: {stats['pending_tasks']}\n"
        f"到期复习: {stats['due_review_count']}\n"
        f"风险等级: {risk}\n\n"
        "请输出三段内容，每段单独一行：\n"
        "1) 推送标题（20字以内）\n"
        "2) 推送正文（40字以内）\n"
        "3) 一句总结建议（60字以内）"
    )

    try:
        provider = await AIProviderFactory.create_provider(
            db=db,
            scenario="motivation",
            user_id=current_user.id,
        )
        reply = await provider.chat(
            messages=[{"role": "user", "content": ai_prompt}],
            system_prompt="你是严格但温暖的学习教练，输出简洁直接。",
            temperature=0.5,
        )
        lines = [ln.strip(" -\t\"“”") for ln in (reply or "").splitlines() if ln.strip()]
        if len(lines) >= 3:
            base_report.push_title = lines[0][:40]
            base_report.push_body = lines[1][:80]
            base_report.summary = lines[2][:120]
    except Exception:
        # AI 失败时保留模板兜底，确保接口稳定
        pass

    return base_report
