"""Shared user-scoped learning snapshot for agent, interventions, and coach policy."""
from __future__ import annotations

import json
from datetime import date, datetime, time, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.coach import CoachNudge
from app.models.daily_plan import DailyPlan
from app.models.goal import Goal, Task
from app.models.memory import UserMemory
from app.models.note import Note
from app.models.pomodoro import Pomodoro
from app.models.question import Question, ReviewSchedule, WrongQuestion
from app.services.memory_service import get_relevant_memories

CONFIRMED_REVIEW_STATUS = "confirmed"
from app.services.profile_service import get_or_compute_profile


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


async def _collect_profile(db: AsyncSession, user_id: int) -> dict[str, Any]:
    profile_obj = await get_or_compute_profile(db, user_id)
    if not profile_obj:
        return {}
    return {
        "total_study_days": int(profile_obj.total_study_days or 0),
        "total_study_hours": float(profile_obj.total_study_hours or 0),
        "total_pomodoros": int(profile_obj.total_pomodoros or 0),
        "focus_score": float(profile_obj.focus_score or 0),
        "consistency_score": float(profile_obj.consistency_score or 0),
        "planning_score": float(profile_obj.planning_score or 0),
        "optimal_hours": profile_obj.optimal_hours,
        "weak_points": profile_obj.weak_points or [],
        "recent_performance": profile_obj.recent_performance or {},
    }


async def _collect_task_state(db: AsyncSession, user_id: int, today: date) -> dict[str, Any]:
    result = await db.execute(
        select(Task, Goal.title.label("goal_title"))
        .join(Goal, Goal.id == Task.goal_id)
        .where(Goal.user_id == user_id, Goal.status == "active")
        .order_by(Task.planned_date.is_(None), Task.planned_date, Task.id)
        .limit(120)
    )
    today_tasks: list[dict[str, Any]] = []
    overdue_tasks: list[dict[str, Any]] = []
    unscheduled_tasks: list[dict[str, Any]] = []
    upcoming_tasks: list[dict[str, Any]] = []
    completed_today: list[dict[str, Any]] = []

    for task, goal_title in result.all():
        item = {
            "id": task.id,
            "goal_id": task.goal_id,
            "goal_title": goal_title,
            "title": task.title,
            "task_type": task.task_type,
            "planned_date": _to_iso(task.planned_date),
            "status": task.status,
            "route": "/goals",
        }
        if task.completed_at and task.completed_at.date() == today:
            completed_today.append(item)
        if task.status == "completed":
            continue
        if task.planned_date is None:
            unscheduled_tasks.append(item)
        elif task.planned_date < today:
            overdue_tasks.append(item)
        elif task.planned_date == today:
            today_tasks.append(item)
        else:
            upcoming_tasks.append(item)

    goals_result = await db.execute(
        select(Goal)
        .where(Goal.user_id == user_id, Goal.status == "active")
        .order_by(Goal.deadline.is_(None), Goal.deadline, Goal.id)
        .limit(10)
    )
    goals = [
        {
            "id": g.id,
            "title": g.title,
            "deadline": _to_iso(g.deadline),
            "target_level": g.target_level,
            "route": "/goals",
        }
        for g in goals_result.scalars().all()
    ]

    return {
        "active_goals": goals,
        "today_tasks": today_tasks,
        "overdue_tasks": overdue_tasks,
        "unscheduled_tasks": unscheduled_tasks,
        "upcoming_tasks": upcoming_tasks,
        "completed_today_tasks": completed_today,
        "pending_task_count": len(today_tasks) + len(overdue_tasks) + len(unscheduled_tasks) + len(upcoming_tasks),
        "today_task_count": len(today_tasks),
        "today_completed_task_count": len(completed_today),
        "today_total_task_count": len(today_tasks) + len(completed_today),
        "today_pending_task_count": len(today_tasks),
        "overdue_task_count": len(overdue_tasks),
        "unscheduled_task_count": len(unscheduled_tasks),
    }


async def _collect_daily_plan_state(db: AsyncSession, user_id: int, today: date) -> dict[str, Any]:
    today_str = today.isoformat()
    result = await db.execute(select(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.date == today_str))
    row = result.scalar_one_or_none()
    content = row.content if row else ""
    checklist_count = sum(1 for line in content.splitlines() if "[ ]" in line or "[x]" in line.lower())
    checked_count = sum(1 for line in content.splitlines() if "[x]" in line.lower())
    task_ids = _json_loads(row.task_ids if row else None, [])
    return {
        "date": today_str,
        "exists": row is not None,
        "plan_id": row.id if row else None,
        "has_content": bool(content.strip()),
        "checklist_count": checklist_count,
        "checked_count": checked_count,
        "task_ids": task_ids if isinstance(task_ids, list) else [],
        "route": "/plans",
    }


async def _collect_review_state(db: AsyncSession, user_id: int, now: datetime) -> dict[str, Any]:
    count_result = await db.execute(
        select(func.count(ReviewSchedule.id)).where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.status == "pending",
            ReviewSchedule.scheduled_date <= now,
            ReviewSchedule.is_archived == False,
        )
    )
    due_count = int(count_result.scalar() or 0)

    due_result = await db.execute(
        select(ReviewSchedule)
        .where(
            ReviewSchedule.user_id == user_id,
            ReviewSchedule.status == "pending",
            ReviewSchedule.scheduled_date <= now,
            ReviewSchedule.is_archived == False,
        )
        .order_by(ReviewSchedule.scheduled_date, ReviewSchedule.id)
        .limit(8)
    )
    due_items = due_result.scalars().all()

    wrong_ids = [item.item_id for item in due_items if item.item_type == "question"]
    wrong_map: dict[int, WrongQuestion] = {}
    question_map: dict[int, Question] = {}
    if wrong_ids:
        wrong_result = await db.execute(
            select(WrongQuestion).where(WrongQuestion.id.in_(wrong_ids), WrongQuestion.user_id == user_id)
        )
        wrongs = wrong_result.scalars().all()
        wrong_map = {int(w.id): w for w in wrongs}
        question_ids = [w.question_id for w in wrongs]
        if question_ids:
            question_result = await db.execute(
                select(Question).where(Question.id.in_(question_ids), Question.user_id == user_id)
            )
            question_map = {int(q.id): q for q in question_result.scalars().all()}

    items = []
    for item in due_items:
        title = "章节复习" if item.item_type == "chapter" else "错题复习"
        knowledge_point = None
        if item.item_type == "question":
            wrong = wrong_map.get(int(item.item_id))
            if wrong:
                knowledge_point = wrong.knowledge_point
                q = question_map.get(int(wrong.question_id))
                if q and q.content:
                    title = q.content[:60]
                elif wrong.knowledge_point:
                    title = f"复习错题：{wrong.knowledge_point}"
        items.append(
            {
                "task_id": item.id,
                "item_type": item.item_type,
                "title": title,
                "knowledge_point": knowledge_point,
                "scheduled_date": _to_iso(item.scheduled_date),
                "route": "/review",
            }
        )

    return {"due_review_count": due_count, "due_review_items": items}


async def _collect_pomodoro_state(db: AsyncSession, user_id: int, today: date, now: datetime) -> dict[str, Any]:
    today_start = datetime.combine(today, time.min)
    today_end = datetime.combine(today, time.max)
    today_result = await db.execute(
        select(Pomodoro).where(
            Pomodoro.user_id == user_id,
            Pomodoro.started_at >= today_start,
            Pomodoro.started_at <= today_end,
        )
    )
    today_pomodoros = today_result.scalars().all()
    today_minutes = sum(float(p.duration or 0) for p in today_pomodoros if p.completed)
    completed_today = len([p for p in today_pomodoros if p.completed])

    recent_result = await db.execute(
        select(Pomodoro).where(Pomodoro.user_id == user_id, Pomodoro.started_at >= now - timedelta(days=7))
    )
    recent = recent_result.scalars().all()
    distracted_count = len([p for p in recent if p.stop_reason == "distracted"])
    interrupted_count = len([p for p in recent if p.stop_reason == "interrupted"])
    recent_attempts = len(recent)
    recent_interruptions = [
        {
            "id": p.id,
            "task_name": p.task_name,
            "duration": float(p.duration or 0),
            "stop_reason": p.stop_reason,
            "started_at": _to_iso(p.started_at),
            "route": "/pomodoro",
        }
        for p in recent
        if p.stop_reason in {"interrupted", "distracted"}
    ][:6]

    return {
        "today_minutes": round(today_minutes, 1),
        "today_pomodoro_count": len(today_pomodoros),
        "today_completed_pomodoros": completed_today,
        "recent_distracted_count": distracted_count,
        "recent_interrupted_count": interrupted_count,
        "recent_interrupted_or_distracted": recent_interruptions,
        "recent_attempts": recent_attempts,
        "recent_distracted_rate": round(distracted_count / recent_attempts, 4) if recent_attempts else 0.0,
    }


async def _collect_weakness_state(db: AsyncSession, user_id: int) -> dict[str, Any]:
    result = await db.execute(
        select(WrongQuestion.knowledge_point, func.count(WrongQuestion.id).label("cnt"))
        .where(WrongQuestion.user_id == user_id, WrongQuestion.knowledge_point.is_not(None))
        .group_by(WrongQuestion.knowledge_point)
        .order_by(desc("cnt"))
        .limit(6)
    )
    return {
        "weak_points_ranked": [
            {"name": str(name), "count": int(cnt), "route": "/wrong-questions"}
            for name, cnt in result.all()
            if name
        ]
    }


async def _collect_memory_state(db: AsyncSession, user_id: int, include_memories: bool) -> dict[str, Any]:
    count_result = await db.execute(
        select(func.count(UserMemory.id)).where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.review_status == CONFIRMED_REVIEW_STATUS,
        )
    )
    memories: list[dict[str, Any]] = []
    if include_memories:
        memories = await get_relevant_memories(
            db,
            topic="学习 目标 薄弱 偏好 风格 计划 复习 coach agent 反馈",
            limit=8,
            user_id=user_id,
        )
    return {"memories": memories, "active_memory_count": int(count_result.scalar() or 0)}


async def _collect_recent_notes(db: AsyncSession, user_id: int, include_recent_notes: bool) -> list[dict[str, Any]]:
    if not include_recent_notes:
        return []
    result = await db.execute(
        select(Note)
        .where(Note.user_id == user_id)
        .order_by(Note.updated_at.desc(), Note.created_at.desc())
        .limit(6)
    )
    return [
        {
            "id": note.id,
            "title": note.title,
            "note_type": note.note_type,
            "updated_at": _to_iso(note.updated_at or note.created_at),
            "route": "/notes",
        }
        for note in result.scalars().all()
    ]


async def _collect_coach_state(db: AsyncSession, user_id: int, now: datetime) -> dict[str, Any]:
    today_start = datetime.combine(now.date(), time.min)
    nudges_today_result = await db.execute(
        select(func.count(CoachNudge.id)).where(
            CoachNudge.user_id == user_id,
            CoachNudge.created_at >= today_start,
            CoachNudge.status.in_(["pending", "shown", "accepted", "completed", "snoozed"]),
        )
    )
    last_result = await db.execute(
        select(CoachNudge)
        .where(CoachNudge.user_id == user_id)
        .order_by(CoachNudge.created_at.desc())
        .limit(1)
    )
    last = last_result.scalar_one_or_none()
    return {
        "today_nudge_count": int(nudges_today_result.scalar() or 0),
        "last_nudge_at": _to_iso(last.created_at) if last else None,
        "last_nudge_skill_id": last.skill_id if last else None,
        "last_nudge_status": last.status if last else None,
    }


def _compute_risk_flags(snapshot: dict[str, Any]) -> dict[str, bool]:
    tasks = snapshot.get("tasks") or {}
    review = snapshot.get("review") or {}
    learning = snapshot.get("learning") or {}
    plan = snapshot.get("daily_plan") or {}
    return {
        "review_debt_high": int(review.get("due_review_count") or 0) >= 6,
        "overdue_tasks_high": int(tasks.get("overdue_task_count") or 0) >= 3,
        "no_daily_plan": not bool(plan.get("has_content")),
        "low_today_focus": float(learning.get("today_minutes") or 0) < 15,
        "recent_interruptions_high": int(learning.get("recent_interrupted_count") or 0) >= 2,
        "recent_distraction_high": float(learning.get("recent_distracted_rate") or 0) >= 0.25,
    }


async def build_learning_snapshot(
    db: AsyncSession,
    user_id: int,
    *,
    now: datetime | None = None,
    include_recent_notes: bool = True,
    include_memories: bool = True,
) -> dict[str, Any]:
    """Aggregate the current user's learning state into one reusable object."""

    current = now or datetime.now()
    today = current.date()
    snapshot: dict[str, Any] = {
        "user_id": user_id,
        "date": today.isoformat(),
        "generated_at": current.isoformat(),
        "profile": await _collect_profile(db, user_id),
        "tasks": await _collect_task_state(db, user_id, today),
        "daily_plan": await _collect_daily_plan_state(db, user_id, today),
        "review": await _collect_review_state(db, user_id, current),
        "learning": await _collect_pomodoro_state(db, user_id, today, current),
        "weaknesses": await _collect_weakness_state(db, user_id),
        "memory": await _collect_memory_state(db, user_id, include_memories),
        "recent_notes": await _collect_recent_notes(db, user_id, include_recent_notes),
        "coach": await _collect_coach_state(db, user_id, current),
    }
    snapshot["risk_flags"] = _compute_risk_flags(snapshot)
    return snapshot
