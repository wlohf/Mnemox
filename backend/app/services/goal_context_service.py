"""Goal-centered context builder for the Agent cockpit."""
from __future__ import annotations

import json
import logging
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import func, or_, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal import Goal, Task
from app.models.learning_event import LearningEvent
from app.models.material import Chapter, Material
from app.models.memory import UserMemory
from app.models.note import Note
from app.models.question import Question, ReviewSchedule, WrongQuestion
from app.services.learning_snapshot_service import build_learning_snapshot
from app.services.note_retriever import NoteRetriever
from app.services.agent_long_memory_service import get_core_profile
from app.services.agent_memory_learning_service import run_agent_memory_learning_if_due

logger = logging.getLogger(__name__)
CONFIRMED_REVIEW_STATUS = "confirmed"


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)


def _safe_tags(raw: str | None) -> list[str]:
    if not raw:
        return []
    try:
        value = json.loads(raw)
        if isinstance(value, list):
            return [str(item).strip() for item in value if str(item).strip()][:8]
    except Exception:
        return []
    return []


def _task_item(task: Task, goal_title: str | None = None) -> dict[str, Any]:
    return {
        "id": task.id,
        "goal_id": task.goal_id,
        "goal_title": goal_title,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "planned_date": _to_iso(task.planned_date),
        "status": task.status,
        "completed_at": _to_iso(task.completed_at),
        "route": "/goals",
    }


def _note_item(note: Note, score: float = 0.0, reason: str | None = None) -> dict[str, Any]:
    content = note.content or ""
    return {
        "id": note.id,
        "title": note.title,
        "note_type": note.note_type,
        "tags": _safe_tags(note.tags),
        "material_id": note.material_id,
        "chapter_id": note.chapter_id,
        "updated_at": _to_iso(note.updated_at or note.created_at),
        "excerpt": content[:180],
        "score": round(score, 3),
        "reason": reason,
        "route": "/notes",
    }


async def _get_explicit_goal(db: AsyncSession, user_id: int, goal_id: int) -> Goal | None:
    result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id, Goal.status == "active"))
    return result.scalar_one_or_none()


async def _load_active_goals(db: AsyncSession, user_id: int) -> list[Goal]:
    result = await db.execute(
        select(Goal)
        .where(Goal.user_id == user_id, Goal.status == "active")
        .order_by(Goal.deadline.is_(None), Goal.deadline, Goal.updated_at.desc(), Goal.id)
        .limit(50)
    )
    return list(result.scalars().all())


async def _goal_task_stats(db: AsyncSession, goal_ids: list[int], today: date) -> dict[int, dict[str, Any]]:
    if not goal_ids:
        return {}
    result = await db.execute(select(Task).where(Task.goal_id.in_(goal_ids)))
    stats: dict[int, dict[str, Any]] = {
        goal_id: {
            "tasks": [],
            "pending_task_count": 0,
            "completed_today_count": 0,
            "overdue_task_count": 0,
            "today_task_count": 0,
            "unscheduled_task_count": 0,
            "next_pending_task": None,
        }
        for goal_id in goal_ids
    }
    for task in result.scalars().all():
        bucket = stats.setdefault(task.goal_id, {"tasks": []})
        bucket.setdefault("tasks", []).append(task)
        if task.completed_at and task.completed_at.date() == today:
            bucket["completed_today_count"] = int(bucket.get("completed_today_count") or 0) + 1
        if task.status == "completed":
            continue
        bucket["pending_task_count"] = int(bucket.get("pending_task_count") or 0) + 1
        if task.planned_date is None:
            bucket["unscheduled_task_count"] = int(bucket.get("unscheduled_task_count") or 0) + 1
        elif task.planned_date < today:
            bucket["overdue_task_count"] = int(bucket.get("overdue_task_count") or 0) + 1
        elif task.planned_date == today:
            bucket["today_task_count"] = int(bucket.get("today_task_count") or 0) + 1

    for bucket in stats.values():
        pending = [task for task in bucket.get("tasks", []) if task.status != "completed"]
        pending.sort(
            key=lambda task: (
                task.planned_date is None,
                task.planned_date or date.max,
                task.id,
            )
        )
        bucket["next_pending_task"] = pending[0] if pending else None
    return stats


async def _recent_activity_scores(db: AsyncSession, user_id: int, goal_ids: list[int], now: datetime) -> dict[int, float]:
    if not goal_ids:
        return {}
    cutoff = now - timedelta(days=14)
    result = await db.execute(
        select(LearningEvent.goal_id, func.count(LearningEvent.id))
        .where(
            LearningEvent.user_id == user_id,
            LearningEvent.goal_id.in_(goal_ids),
            LearningEvent.timestamp >= cutoff,
        )
        .group_by(LearningEvent.goal_id)
    )
    return {int(goal_id): min(float(count or 0), 5.0) for goal_id, count in result.all() if goal_id is not None}


async def _agent_feedback_scores(db: AsyncSession, user_id: int, goal_ids: list[int]) -> dict[int, float]:
    if not goal_ids:
        return {}
    goal_titles_result = await db.execute(select(Goal.id, Goal.title).where(Goal.id.in_(goal_ids), Goal.user_id == user_id))
    titles = {int(goal_id): str(title or "") for goal_id, title in goal_titles_result.all()}
    if not titles:
        return {}
    result = await db.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.review_status == CONFIRMED_REVIEW_STATUS,
            UserMemory.category == "agent_feedback",
        )
        .order_by(UserMemory.last_seen_at.desc(), UserMemory.id.desc())
        .limit(30)
    )
    scores = {goal_id: 0.0 for goal_id in goal_ids}
    for memory in result.scalars().all():
        text = f"{memory.memory_key}\n{memory.memory_value or ''}"
        for goal_id, title in titles.items():
            if title and title in text:
                scores[goal_id] += 0.5
    return scores


async def _select_goal(db: AsyncSession, user_id: int, goal_id: int | None, now: datetime) -> tuple[Goal | None, dict[int, dict[str, Any]]]:
    today = now.date()
    if goal_id is not None:
        goal = await _get_explicit_goal(db, user_id, goal_id)
        stats = await _goal_task_stats(db, [goal.id], today) if goal else {}
        return goal, stats

    goals = await _load_active_goals(db, user_id)
    if not goals:
        return None, {}
    goal_ids = [int(goal.id) for goal in goals]
    stats = await _goal_task_stats(db, goal_ids, today)
    activity_scores = await _recent_activity_scores(db, user_id, goal_ids, now)
    feedback_scores = await _agent_feedback_scores(db, user_id, goal_ids)

    def score(goal: Goal) -> tuple[float, int]:
        bucket = stats.get(int(goal.id), {})
        value = 0.0
        value += float(bucket.get("overdue_task_count") or 0) * 12
        value += float(bucket.get("today_task_count") or 0) * 10
        value += float(bucket.get("unscheduled_task_count") or 0) * 2
        value += min(float(bucket.get("pending_task_count") or 0), 8.0)
        if goal.deadline:
            days_left = (goal.deadline - today).days
            if days_left < 0:
                value += 14
            elif days_left <= 3:
                value += 10
            elif days_left <= 7:
                value += 6
            elif days_left <= 14:
                value += 3
        value += activity_scores.get(int(goal.id), 0.0)
        value += feedback_scores.get(int(goal.id), 0.0)
        return value, -int(goal.id)

    return max(goals, key=score), stats


async def _supporting_notes(db: AsyncSession, user_id: int, goal: Goal, task_ids: list[int], limit: int = 6) -> list[dict[str, Any]]:
    task_text = ""
    if task_ids:
        result = await db.execute(select(Task.title, Task.description).where(Task.id.in_(task_ids)))
        task_text = " ".join(f"{title or ''} {description or ''}" for title, description in result.all())
    return await NoteRetriever.retrieve_notes(
        db,
        user_id,
        query=f"{goal.title or ''} {goal.description or ''} {task_text}",
        goal_id=int(goal.id),
        material_id=goal.material_id,
        limit=limit,
    )


async def _supporting_materials(db: AsyncSession, user_id: int, goal: Goal) -> list[dict[str, Any]]:
    if not goal.material_id:
        return []
    result = await db.execute(select(Material).where(Material.id == goal.material_id, Material.user_id == user_id))
    material = result.scalar_one_or_none()
    if not material:
        return []
    return [
        {
            "id": material.id,
            "title": material.title,
            "file_type": material.file_type,
            "content_status": material.content_status,
            "updated_at": _to_iso(material.updated_at or material.created_at),
            "route": "/materials",
        }
    ]


async def _supporting_wrong_questions(db: AsyncSession, user_id: int, goal: Goal, limit: int = 6) -> list[dict[str, Any]]:
    filters = [WrongQuestion.user_id == user_id]
    if goal.material_id:
        chapter_ids = select(Chapter.id).where(Chapter.material_id == goal.material_id)
        question_ids = select(Question.id).where(Question.chapter_id.in_(chapter_ids), Question.user_id == user_id)
        filters.append(WrongQuestion.question_id.in_(question_ids))
    result = await db.execute(
        select(WrongQuestion, Question.content)
        .join(Question, Question.id == WrongQuestion.question_id)
        .where(*filters)
        .order_by(WrongQuestion.mastery_status != "not_mastered", WrongQuestion.wrong_count.desc(), WrongQuestion.last_wrong_at.desc())
        .limit(max(1, min(limit, 12)))
    )
    return [
        {
            "id": wrong.id,
            "question_id": wrong.question_id,
            "title": (wrong.knowledge_point or content or "错题复习")[:80],
            "knowledge_point": wrong.knowledge_point,
            "wrong_count": wrong.wrong_count,
            "mastery_status": wrong.mastery_status,
            "next_review_at": _to_iso(wrong.next_review_at),
            "route": "/wrong-questions",
        }
        for wrong, content in result.all()
    ]


async def _supporting_review_items(db: AsyncSession, user_id: int, goal: Goal, now: datetime, limit: int = 6) -> list[dict[str, Any]]:
    filters = [
        ReviewSchedule.user_id == user_id,
        ReviewSchedule.status == "pending",
        ReviewSchedule.is_archived == False,
        ReviewSchedule.scheduled_date <= now,
    ]
    if goal.material_id:
        chapter_ids = select(Chapter.id).where(Chapter.material_id == goal.material_id)
        question_ids = select(Question.id).where(Question.chapter_id.in_(chapter_ids), Question.user_id == user_id)
        wrong_ids = select(WrongQuestion.id).where(WrongQuestion.user_id == user_id, WrongQuestion.question_id.in_(question_ids))
        filters.append(
            or_(
                (ReviewSchedule.item_type == "chapter") & (ReviewSchedule.item_id.in_(chapter_ids)),
                (ReviewSchedule.item_type == "question") & (ReviewSchedule.item_id.in_(wrong_ids)),
            )
        )
    result = await db.execute(
        select(ReviewSchedule)
        .where(*filters)
        .order_by(ReviewSchedule.scheduled_date, ReviewSchedule.id)
        .limit(max(1, min(limit, 12)))
    )
    return [
        {
            "id": item.id,
            "item_type": item.item_type,
            "item_id": item.item_id,
            "scheduled_date": _to_iso(item.scheduled_date),
            "status": item.status,
            "route": "/review",
        }
        for item in result.scalars().all()
    ]


def _build_today_focus(goal: Goal | None, goal_stats: dict[str, Any], snapshot: dict[str, Any]) -> dict[str, Any]:
    if goal is None:
        return {
            "id": "create_goal",
            "action_id": "goal_context_create_goal",
            "title": "先创建一个当前学习目标",
            "reason": "当前没有活跃目标，Agent 需要一个目标才能组织任务、笔记和复习证据。",
            "estimated_minutes": 5,
            "route": "/goals",
            "target": None,
            "requires_confirmation": True,
        }

    task = goal_stats.get("next_pending_task")
    if task:
        planned = task.planned_date
        if planned and planned < date.fromisoformat(snapshot["date"]):
            action_id = "rescue_overdue_task"
            reason = "该任务已经过期，先补一个最小切片能降低拖延负担。"
        elif planned and planned == date.fromisoformat(snapshot["date"]):
            action_id = "start_today_focus"
            reason = "目标今天已有明确任务，直接进入执行比重新规划更有效。"
        else:
            action_id = "make_today_minimum_plan"
            reason = "这是当前目标下最靠前的未完成任务，可以作为今天的最小行动。"
        return {
            "id": f"task:{task.id}",
            "action_id": action_id,
            "title": task.title,
            "reason": reason,
            "estimated_minutes": 25 if action_id == "start_today_focus" else 15,
            "route": "/pomodoro",
            "target": _task_item(task, goal.title),
            "requires_confirmation": False,
        }

    if int((snapshot.get("review") or {}).get("due_review_count") or 0) > 0:
        return {
            "id": "review_due",
            "action_id": "clear_due_review",
            "title": "先清理一小组到期复习",
            "reason": "当前没有未完成任务，但存在到期复习，先处理复习能降低遗忘风险。",
            "estimated_minutes": 15,
            "route": "/review",
            "target": ((snapshot.get("review") or {}).get("due_review_items") or [None])[0],
            "requires_confirmation": False,
        }

    return {
        "id": f"goal:{goal.id}:minimum_plan",
        "action_id": "make_today_minimum_plan",
        "title": f"为「{goal.title}」生成今天的最小行动",
        "reason": "当前目标没有未完成任务，建议生成一个 25 分钟以内的学习切片。",
        "estimated_minutes": 5,
        "route": "/plans",
        "target": {"id": goal.id, "title": goal.title, "route": "/goals"},
        "requires_confirmation": True,
    }


async def build_goal_context(
    db: AsyncSession,
    user_id: int,
    *,
    goal_id: int | None = None,
    now: datetime | None = None,
) -> dict[str, Any]:
    """Build the user-scoped Agent home context around one selected goal."""

    current = now or datetime.now()
    try:
        await run_agent_memory_learning_if_due(db, user_id, now=current, interval_hours=6)
    except Exception as exc:
        logger.warning("Agent memory checkpoint failed for user_id=%s: %s", user_id, exc)
    core_profile = await get_core_profile(db, user_id)
    snapshot = await build_learning_snapshot(db, user_id, now=current, include_recent_notes=True, include_memories=True)
    goal, all_stats = await _select_goal(db, user_id, goal_id, current)
    selected_stats = all_stats.get(int(goal.id), {}) if goal else {}

    if goal is None:
        return {
            "date": current.date().isoformat(),
            "generated_at": current.isoformat(),
            "active_goal": None,
            "goal_creation": {
                "title": "创建当前主目标",
                "message": "你还没有活跃目标。可以先创建一个两周内可完成、每天能推进的小目标。",
                "route": "/goals",
                "requires_confirmation": True,
            },
            "today_focus": _build_today_focus(None, {}, snapshot),
            "supporting_context": {"notes": [], "materials": [], "wrong_questions": [], "review_items": []},
            "risk_flags": {
                "no_daily_plan": bool((snapshot.get("risk_flags") or {}).get("no_daily_plan")),
                "review_debt_high": bool((snapshot.get("risk_flags") or {}).get("review_debt_high")),
                "goal_stale": False,
            },
            "evidence": ["当前没有活跃目标"],
            "core_profile": core_profile,
            "snapshot": snapshot,
        }

    tasks = list(selected_stats.get("tasks") or [])
    task_ids = [int(task.id) for task in tasks]
    supporting_context = {
        "notes": await _supporting_notes(db, user_id, goal, task_ids),
        "materials": await _supporting_materials(db, user_id, goal),
        "wrong_questions": await _supporting_wrong_questions(db, user_id, goal),
        "review_items": await _supporting_review_items(db, user_id, goal, current),
    }
    today_focus = _build_today_focus(goal, selected_stats, snapshot)
    recent_event_result = await db.execute(
        select(func.count(LearningEvent.id)).where(
            LearningEvent.user_id == user_id,
            LearningEvent.goal_id == goal.id,
            LearningEvent.timestamp >= current - timedelta(days=7),
        )
    )
    recent_goal_events = int(recent_event_result.scalar() or 0)
    completed_today = int(selected_stats.get("completed_today_count") or 0)
    goal_stale = recent_goal_events == 0 and completed_today == 0 and bool(goal.updated_at and goal.updated_at < current - timedelta(days=14))

    evidence = []
    if selected_stats.get("today_task_count"):
        evidence.append(f"今日任务 {selected_stats.get('today_task_count')} 个")
    if selected_stats.get("overdue_task_count"):
        evidence.append(f"过期任务 {selected_stats.get('overdue_task_count')} 个")
    if completed_today:
        evidence.append(f"今天已完成 {completed_today} 个任务")
    if supporting_context["notes"]:
        evidence.append(f"找到 {len(supporting_context['notes'])} 条相关笔记")
    if supporting_context["wrong_questions"]:
        evidence.append(f"找到 {len(supporting_context['wrong_questions'])} 条相关错题")
    if not evidence:
        evidence.append("根据活跃目标、任务状态和最近学习快照综合选择")

    return {
        "date": current.date().isoformat(),
        "generated_at": current.isoformat(),
        "active_goal": {
            "id": goal.id,
            "title": goal.title,
            "description": goal.description,
            "deadline": _to_iso(goal.deadline),
            "target_level": goal.target_level,
            "material_id": goal.material_id,
            "route": "/goals",
            "progress": {
                "pending_task_count": int(selected_stats.get("pending_task_count") or 0),
                "completed_today_count": completed_today,
                "overdue_task_count": int(selected_stats.get("overdue_task_count") or 0),
                "today_task_count": int(selected_stats.get("today_task_count") or 0),
            },
        },
        "today_focus": today_focus,
        "supporting_context": supporting_context,
        "risk_flags": {
            "no_daily_plan": bool((snapshot.get("risk_flags") or {}).get("no_daily_plan")),
            "review_debt_high": bool((snapshot.get("risk_flags") or {}).get("review_debt_high")),
            "goal_stale": goal_stale,
        },
        "evidence": evidence,
        "core_profile": core_profile,
        "snapshot": snapshot,
    }
