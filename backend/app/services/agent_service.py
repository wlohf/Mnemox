"""自主学习 Agent 简报服务。

把画像、记忆、任务、复习、错题与番茄钟状态整理成主动建议，并提供可注入聊天 prompt 的片段。
当前版本优先使用规则引擎兜底，后续可在此基础上叠加 LLM planner。
"""
from __future__ import annotations

import asyncio
import json
import logging
import re
from datetime import date, datetime, timedelta
from typing import Any

from sqlalchemy import desc, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.agent import AgentExecutionLog
from app.models.daily_plan import DailyPlan
from app.models.goal import Goal, Task
from app.models.material import Material
from app.models.memory import UserMemory
from app.models.note import Note
from app.models.pomodoro import Pomodoro
from app.models.question import Question, ReviewSchedule, WrongQuestion
from app.services.memory_service import get_relevant_memories
from app.services.profile_service import get_or_compute_profile
from app.config import settings
from app.utils.prompt_safety import wrap_untrusted_context

logger = logging.getLogger(__name__)

NEGATIVE_FEEDBACK_REASON_LABELS = {
    "too_long": "太长",
    "too_late": "太晚",
    "too_easy": "太简单",
    "too_hard": "太难",
    "too_disruptive": "太打扰",
    "irrelevant_to_goal": "和当前目标无关",
    "already_known": "已经掌握",
    "other": "其他原因",
}

PROFILE_CONTROL_LABELS = {
    "ignore": "不再使用",
    "inaccurate": "标记不准确",
    "lock": "锁定",
    "unlock": "取消锁定",
    "restore": "恢复",
}


def _clamp(value: float, low: float = 0.0, high: float = 100.0) -> float:
    return max(low, min(high, value))


def _to_iso(value: Any) -> str | None:
    if value is None:
        return None
    if hasattr(value, "isoformat"):
        return value.isoformat()
    return str(value)



def _safe_json_loads(text: str, fallback: Any) -> Any:
    try:
        return json.loads(text)
    except Exception:
        return fallback


def _extract_json_object(raw: str) -> dict[str, Any] | None:
    text = (raw or "").strip()
    if not text:
        return None
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?", "", text, flags=re.IGNORECASE).strip()
        if text.endswith("```"):
            text = text[:-3].strip()
    data = _safe_json_loads(text, None)
    if isinstance(data, dict):
        return data
    start = text.find("{")
    end = text.rfind("}")
    if start >= 0 and end > start:
        data = _safe_json_loads(text[start : end + 1], None)
        if isinstance(data, dict):
            return data
    return None


def _compact_text(value: Any, limit: int = 200) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip()
    return text[:limit]


def _normalize_match_text(value: Any) -> str:
    return re.sub(r"\s+", "", str(value or "").strip().lower())


def _similar_text(a: Any, b: Any) -> bool:
    """Small dependency-free fuzzy match for duplicate detection."""
    left = _normalize_match_text(a)
    right = _normalize_match_text(b)
    if not left or not right:
        return False
    if left == right or left in right or right in left:
        return True
    left_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", str(a or "").lower()))
    right_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", str(b or "").lower()))
    if not left_tokens or not right_tokens:
        return False
    overlap = len(left_tokens & right_tokens) / max(1, min(len(left_tokens), len(right_tokens)))
    return overlap >= 0.72


def _classify_note(content: str, source_text: str = "") -> tuple[str, list[str]]:
    text = f"{source_text}\n{content}".strip()
    rules = [
        ("idea", "灵感", ["灵感", "想法", "创意", "idea", "突然想到", "可以试试", "点子"]),
        ("method", "学习方法", ["学习方法", "方法", "技巧", "策略", "怎么学", "复盘法", "记忆法", "费曼", "番茄钟"]),
        ("summary", "总结", ["总结", "小结", "复盘", "归纳", "整理一下"]),
        ("question", "问题", ["问题", "疑问", "不理解", "为什么", "怎么回事", "困惑"]),
        ("resource", "资料", ["资料", "书", "文章", "链接", "课程", "视频", "论文"]),
    ]
    tags: list[str] = []
    for note_type, tag, keywords in rules:
        if any(k.lower() in text.lower() for k in keywords):
            tags.append(tag)
            return note_type, tags
    return "general", ["对话记录"]


def _clean_note_content(text: str) -> str:
    content = text.strip()
    patterns = [
        r"^(?:记个|记一个|记一条)?(?:笔记|灵感|想法)[:：]?",
        r"^(?:记录一下|写入笔记|存到笔记|保存到笔记|记到笔记|记进笔记)[:：]?",
        r"^(?:突然|临时)?(?:有个|有一个|想到一个)?(?:想法|灵感)[:：]?",
        r"^(?:我有个|我有一个)(?:想法|灵感)[:：]?",
    ]
    for pattern in patterns:
        content = re.sub(pattern, "", content, flags=re.IGNORECASE).strip()
    for sep in ["：", ":", "\n"]:
        if sep in content and len(content.split(sep, 1)[0]) <= 24:
            head, tail = content.split(sep, 1)
            if any(k in head for k in ["笔记", "灵感", "想法", "记录", "保存"]):
                content = tail.strip()
                break
    return content or text.strip()


def _extract_plan_items(text: str, today: date) -> list[dict[str, Any]]:
    cleaned = text.strip()
    cleaned = re.sub(r"^(?:帮我|请帮我|麻烦)?(?:把|将)?", "", cleaned).strip()
    cleaned = re.sub(r"^(?:今天|今日|明天|明日|后天)?(?:的)?(?:任务|计划|待办)(?:是|：|:)?", "", cleaned).strip()
    cleaned = re.sub(r"^(?:加入|加到|写到|安排到)(?:今天|今日|明天|明日|后天)(?:计划|待办)?(?:里|中)?(?:是|：|:)?", "", cleaned).strip()
    planned_date = today
    if any(k in text for k in ["明天", "明日"]):
        planned_date = today + timedelta(days=1)
    elif "后天" in text:
        planned_date = today + timedelta(days=2)
    parts = [p.strip(" -[]☐✅") for p in re.split(r"[，,。；;、\n]+", cleaned) if p.strip(" -[]☐✅")]
    if not parts:
        parts = [cleaned or text]
    stop_words = {"今天的任务是", "今天任务是", "今日任务是", "今天计划是", "今日计划是", "任务是"}
    items = []
    for part in parts[:12]:
        title = _compact_text(part, 100)
        if not title or title in stop_words:
            continue
        task_type = "review" if "复习" in title else "practice" if any(k in title for k in ["练习", "刷题", "训练"]) else "summarize" if any(k in title for k in ["总结", "整理", "复盘"]) else "learn"
        items.append({
            "title": title,
            "description": "由对话 Agent 根据你的自然语言计划加入每日计划。",
            "task_type": task_type,
            "planned_date": planned_date.isoformat(),
        })
    return items


def _parse_agent_date(value: Any, default: date) -> date:
    text = str(value or "").strip()
    if not text:
        return default
    if text in {"今天", "今日"}:
        return default
    if text in {"明天", "明日"}:
        return default + timedelta(days=1)
    if text in {"后天"}:
        return default + timedelta(days=2)
    try:
        return date.fromisoformat(text[:10])
    except Exception:
        return default


def _normalize_priority(value: Any) -> str:
    text = str(value or "medium").lower()
    if text in {"high", "medium", "low"}:
        return text
    return "medium"


def _normalize_route(value: Any, action_type: str) -> str:
    route = str(value or "").strip()
    allowed = {"/review", "/goals", "/plans", "/wrong-questions", "/pomodoro", "/eda", "/agent"}
    if route in allowed:
        return route
    defaults = {
        "review": "/review",
        "task": "/goals",
        "plan": "/plans",
        "practice": "/wrong-questions",
        "focus": "/pomodoro",
        "intervention": "/pomodoro",
        "reflect": "/eda",
    }
    return defaults.get(action_type, "/agent")


async def _collect_task_state(db: AsyncSession, user_id: int, today: date) -> dict[str, Any]:
    result = await db.execute(
        select(Task, Goal.title.label("goal_title"))
        .join(Goal, Goal.id == Task.goal_id)
        .where(Goal.user_id == user_id, Goal.status == "active", Task.status != "completed")
        .order_by(Task.planned_date.is_(None), Task.planned_date, Task.id)
        .limit(50)
    )
    today_tasks: list[dict[str, Any]] = []
    overdue_tasks: list[dict[str, Any]] = []
    unscheduled_tasks: list[dict[str, Any]] = []
    upcoming_tasks: list[dict[str, Any]] = []

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
        "pending_task_count": len(today_tasks) + len(overdue_tasks) + len(unscheduled_tasks) + len(upcoming_tasks),
        "today_task_count": len(today_tasks),
        "overdue_task_count": len(overdue_tasks),
        "unscheduled_task_count": len(unscheduled_tasks),
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
        wrong_map = {w.id: w for w in wrongs}
        question_ids = [w.question_id for w in wrongs]
        if question_ids:
            question_result = await db.execute(select(Question).where(Question.id.in_(question_ids), Question.user_id == user_id))
            question_map = {q.id: q for q in question_result.scalars().all()}

    items = []
    for item in due_items:
        title = "章节复习" if item.item_type == "chapter" else "错题复习"
        knowledge_point = None
        if item.item_type == "question":
            wrong = wrong_map.get(item.item_id)
            if wrong:
                knowledge_point = wrong.knowledge_point
                q = question_map.get(wrong.question_id)
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


async def _collect_learning_state(db: AsyncSession, user_id: int, today: date, now: datetime) -> dict[str, Any]:
    today_result = await db.execute(
        select(Pomodoro).where(Pomodoro.user_id == user_id, func.date(Pomodoro.started_at) == today.isoformat())
    )
    today_pomodoros = today_result.scalars().all()
    today_minutes = sum(float(p.duration or 0) for p in today_pomodoros)
    completed_today = len([p for p in today_pomodoros if p.completed])

    recent_result = await db.execute(
        select(Pomodoro).where(Pomodoro.user_id == user_id, Pomodoro.started_at >= now - timedelta(days=7))
    )
    recent = recent_result.scalars().all()
    distracted_count = len([p for p in recent if p.stop_reason == "distracted"])
    interrupted_count = len([p for p in recent if p.stop_reason == "interrupted"])
    recent_attempts = len(recent)

    return {
        "today_minutes": round(today_minutes, 1),
        "today_pomodoro_count": len(today_pomodoros),
        "today_completed_pomodoros": completed_today,
        "recent_distracted_count": distracted_count,
        "recent_interrupted_count": interrupted_count,
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


async def _collect_memory_state(db: AsyncSession, user_id: int) -> dict[str, Any]:
    memories = await get_relevant_memories(
        db,
        topic="学习 目标 薄弱 偏好 风格 计划 复习 agent 反馈",
        limit=8,
        user_id=user_id,
    )
    count_result = await db.execute(
        select(func.count(UserMemory.id)).where(UserMemory.user_id == user_id, UserMemory.status == "active")
    )
    return {"memories": memories, "active_memory_count": int(count_result.scalar() or 0)}


def _parse_memory_json(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except Exception:
        return fallback


def _feedback_label(outcome: str) -> str:
    labels = {
        "accepted": "已接受",
        "completed": "已完成",
        "helpful": "有帮助",
        "dismissed": "已拒绝",
        "rejected": "已拒绝",
        "later": "稍后再说",
        "snoozed": "稍后再说",
        "useless": "无用",
        "failed": "执行失败",
        "adjusted": "已调整",
        "navigated": "已跳转",
    }
    return labels.get(outcome, outcome or "未知")


def _reason_label(reason_code: str | None) -> str:
    return NEGATIVE_FEEDBACK_REASON_LABELS.get(reason_code or "", reason_code or "")


def _profile_control_label(operation: str | None) -> str:
    return PROFILE_CONTROL_LABELS.get(operation or "", operation or "")


def _audit_log_to_dict(log: AgentExecutionLog) -> dict[str, Any]:
    metadata = log.extra_metadata or {}
    operation = str(metadata.get("operation") or log.status or "")
    return {
        "id": log.id,
        "agent": log.agent,
        "status": log.status,
        "operation": operation,
        "operation_label": _profile_control_label(operation),
        "item_id": metadata.get("item_id"),
        "item_text": metadata.get("item_text"),
        "message": log.message,
        "created_at": _to_iso(log.created_at),
    }


async def collect_agent_profile_control_logs(db: AsyncSession, user_id: int, limit: int = 8) -> list[dict[str, Any]]:
    result = await db.execute(
        select(AgentExecutionLog)
        .where(AgentExecutionLog.user_id == user_id, AgentExecutionLog.agent == "profile_control")
        .order_by(AgentExecutionLog.created_at.desc(), AgentExecutionLog.id.desc())
        .limit(limit)
    )
    return [_audit_log_to_dict(log) for log in result.scalars().all()]


async def _collect_agent_personalization(db: AsyncSession, user_id: int, context: dict[str, Any]) -> dict[str, Any]:
    feedback_result = await db.execute(
        select(UserMemory)
        .where(
            UserMemory.user_id == user_id,
            UserMemory.status == "active",
            UserMemory.category == "agent_feedback",
        )
        .order_by(UserMemory.last_seen_at.desc(), UserMemory.updated_at.desc())
        .limit(30)
    )
    feedback_rows = feedback_result.scalars().all()
    recent_feedback: list[dict[str, Any]] = []
    outcome_counts: dict[str, int] = {}
    action_feedback: dict[str, dict[str, Any]] = {}
    action_type_stats: dict[str, dict[str, int]] = {}
    topic_stats: dict[str, dict[str, int]] = {}
    reason_counts: dict[str, int] = {}
    reason_action_type_counts: dict[str, dict[str, int]] = {}
    reason_topic_counts: dict[str, dict[str, int]] = {}
    negative_outcomes = {"dismissed", "rejected", "later", "snoozed", "useless", "failed"}
    positive_outcomes = {"accepted", "completed", "helpful", "adjusted", "navigated"}

    for row in feedback_rows:
        data = _parse_memory_json(row.memory_value, {})
        if not isinstance(data, dict):
            continue
        action_id = str(data.get("action_id") or "")
        outcome = str(data.get("outcome") or "")
        action_type = str(data.get("action_type") or "")
        topic = str(data.get("knowledge_point") or data.get("topic") or "")
        source_signal = str(data.get("source_signal") or "")
        reason_code = str(data.get("reason_code") or "")
        item = {
            "action_id": action_id,
            "action_type": action_type,
            "knowledge_point": topic,
            "topic": topic,
            "source_signal": source_signal,
            "reason_code": reason_code,
            "reason_label": _reason_label(reason_code),
            "outcome": outcome,
            "outcome_label": _feedback_label(outcome),
            "notes": str(data.get("notes") or "")[:200],
            "reason": str(data.get("reason") or "")[:240],
            "effectiveness": data.get("effectiveness"),
            "recorded_at": data.get("recorded_at") or _to_iso(row.last_seen_at),
        }
        recent_feedback.append(item)
        if outcome:
            outcome_counts[outcome] = outcome_counts.get(outcome, 0) + 1
        if action_id and action_id not in action_feedback:
            action_feedback[action_id] = item
        if action_type:
            stats = action_type_stats.setdefault(action_type, {"positive": 0, "negative": 0})
            stats["negative" if outcome in negative_outcomes else "positive"] += 1
        if topic:
            stats = topic_stats.setdefault(topic, {"positive": 0, "negative": 0})
            stats["negative" if outcome in negative_outcomes else "positive"] += 1
        if reason_code and outcome in negative_outcomes:
            reason_counts[reason_code] = reason_counts.get(reason_code, 0) + 1
            if action_type:
                reason_action_type_counts.setdefault(reason_code, {})[action_type] = reason_action_type_counts.setdefault(reason_code, {}).get(action_type, 0) + 1
            if topic:
                reason_topic_counts.setdefault(reason_code, {})[topic] = reason_topic_counts.setdefault(reason_code, {}).get(topic, 0) + 1

    accepted = sum(outcome_counts.get(k, 0) for k in positive_outcomes)
    rejected = sum(outcome_counts.get(k, 0) for k in negative_outcomes)
    feedback_total = accepted + rejected
    accepted_rate = round(accepted / feedback_total, 3) if feedback_total else None

    existing_profile = await _get_agent_learning_profile(db, user_id)
    controls = existing_profile.get("controls", {}) if isinstance(existing_profile, dict) else {}
    ignored_items = set(controls.get("ignored_items") or [])
    inaccurate_items = set(controls.get("inaccurate_items") or [])
    locked_items = set(controls.get("locked_items") or [])
    locked_values = existing_profile.get("locked_values", {}) if isinstance(existing_profile.get("locked_values"), dict) else {}

    weak_points = context.get("weaknesses", {}).get("weak_points_ranked", [])[:3]
    tasks = context.get("tasks", {})
    learning = context.get("learning", {})
    profile = context.get("profile", {})

    material_result = await db.execute(
        select(Material.file_type, func.count(Material.id).label("cnt"))
        .where(Material.user_id == user_id)
        .group_by(Material.file_type)
        .order_by(desc("cnt"))
        .limit(3)
    )
    material_sources = [
        {"file_type": file_type or "unknown", "count": int(cnt)}
        for file_type, cnt in material_result.all()
    ]

    summary_items: list[dict[str, Any]] = []
    preference_items: list[dict[str, Any]] = []

    def add_item(bucket: list[dict[str, Any]], item_id: str, text: str, source: str, confidence: float = 0.7) -> None:
        locked = item_id in locked_items
        ignored = item_id in ignored_items
        inaccurate = item_id in inaccurate_items
        final_text = str(locked_values.get(item_id) or text) if locked else text
        bucket.append({
            "id": item_id,
            "text": final_text,
            "source": source,
            "confidence": confidence,
            "locked": locked,
            "ignored": ignored,
            "inaccurate": inaccurate,
        })

    if weak_points:
        names = "、".join(str(w.get("name")) for w in weak_points if w.get("name"))
        add_item(summary_items, "weak_points", f"常见薄弱点：{names}", "wrong_questions", 0.78)
    if profile.get("optimal_hours"):
        add_item(summary_items, "optimal_hours", f"高效学习时段倾向：{profile['optimal_hours']}", "profile", 0.72)
    if material_sources:
        add_item(summary_items, "material_sources", "常用资料来源：" + "、".join(f"{m['file_type']}×{m['count']}" for m in material_sources), "materials", 0.68)
    if learning.get("recent_distracted_rate", 0) >= 0.25:
        add_item(summary_items, "short_focus", "近期更适合短专注块，避免一次性安排过长任务", "pomodoro", 0.74)
        add_item(preference_items, "pref_short_low_pressure", "更适合短时、低压力的专注建议", "pomodoro", 0.74)
    elif learning.get("today_completed_pomodoros", 0) >= 2:
        add_item(preference_items, "pref_pomodoro_rhythm", "能承接连续番茄钟式学习节奏", "pomodoro", 0.7)
    if tasks.get("overdue_task_count", 0) > 0:
        add_item(preference_items, "pref_minimum_rescue", "过期任务需要最小补救切片，而不是一次性补完", "tasks", 0.76)
    if accepted_rate is not None:
        add_item(summary_items, "agent_acceptance_rate", f"Agent 建议接受率约 {round(accepted_rate * 100)}%（基于最近 {feedback_total} 条反馈）", "agent_feedback", 0.8)
    if rejected >= 2:
        add_item(preference_items, "pref_reduce_repetition", "近期对部分建议反馈较低，Agent 应减少重复打扰并优先解释原因", "agent_feedback", 0.82)

    feedback_impacts: list[dict[str, Any]] = []
    for action_type, stats in action_type_stats.items():
        if stats["negative"]:
            feedback_impacts.append({"dimension": "action_type", "key": action_type, "effect": "deprioritize", "message": f"最近对 {action_type} 类建议有 {stats['negative']} 条负反馈，降低重复提醒频率。"})
        elif stats["positive"]:
            feedback_impacts.append({"dimension": "action_type", "key": action_type, "effect": "boost", "message": f"最近对 {action_type} 类建议反馈较好，可适度优先。"})
    for topic, stats in topic_stats.items():
        if stats["negative"]:
            feedback_impacts.append({"dimension": "topic", "key": topic, "effect": "deprioritize", "message": f"主题「{topic}」相关建议近期反馈偏低，后续会减少直接打扰。"})
    for reason_code, count in reason_counts.items():
        action_types = reason_action_type_counts.get(reason_code) or {}
        top_action_type = max(action_types.items(), key=lambda item: item[1])[0] if action_types else "这类"
        feedback_impacts.append({
            "dimension": "reason_code",
            "key": reason_code,
            "effect": "deprioritize",
            "message": f"最近你 {count} 次认为 {top_action_type} 建议「{_reason_label(reason_code)}」，Agent 会减少类似打扰并优先解释原因。",
        })

    audit_events = await collect_agent_profile_control_logs(db, user_id, limit=8)

    avoid_action_ids: list[str] = []
    avoid_action_types: list[str] = []
    avoid_topics: list[str] = []
    for action_id, item in action_feedback.items():
        if item.get("outcome") in {"dismissed", "rejected", "later", "snoozed", "useless"}:
            avoid_action_ids.append(action_id)
            if item.get("action_type"):
                avoid_action_types.append(item["action_type"])
            if item.get("topic"):
                avoid_topics.append(item["topic"])

    visible_summary_items = [i for i in summary_items if not i["ignored"] and not i["inaccurate"]]
    visible_preference_items = [i for i in preference_items if not i["ignored"] and not i["inaccurate"]]
    trait_payload = _build_agent_traits(
        profile=profile,
        memories=context.get("memory", {}).get("memories", []),
        learning=learning,
        accepted_rate=accepted_rate,
        feedback_total=feedback_total,
        reason_counts=reason_counts,
        action_type_stats=action_type_stats,
        existing_profile=existing_profile,
    )

    profile_payload = {
        "summary": [i["text"] for i in visible_summary_items[:6]],
        "summary_items": summary_items[:8],
        "learned_preferences": [i["text"] for i in visible_preference_items[:6]],
        "preference_items": preference_items[:8],
        "feedback_stats": {
            "accepted": accepted,
            "rejected_or_delayed": rejected,
            "accepted_rate": accepted_rate,
            "outcome_counts": outcome_counts,
            "by_action_type": action_type_stats,
            "by_topic": topic_stats,
            "by_reason_code": reason_counts,
            "by_reason_action_type": reason_action_type_counts,
            "by_reason_topic": reason_topic_counts,
        },
        "traits": trait_payload["traits"],
        "trait_items": trait_payload["all_trait_items"],
        "do_more": trait_payload["do_more"],
        "avoid": trait_payload["avoid"],
        "trait_controls": trait_payload["trait_controls"],
        "locked_trait_values": trait_payload["locked_trait_values"],
        "feedback_impacts": feedback_impacts[:10],
        "profile_control_logs": audit_events,
        "recent_feedback": recent_feedback[:8],
        "avoid_action_ids": avoid_action_ids[:10],
        "avoid_action_types": sorted(set(avoid_action_types))[:10],
        "avoid_topics": sorted(set(avoid_topics))[:10],
        "material_sources": material_sources,
        "controls": {"ignored_items": sorted(ignored_items), "inaccurate_items": sorted(inaccurate_items), "locked_items": sorted(locked_items)},
        "locked_values": locked_values,
        "updated_at": datetime.now().isoformat(),
    }
    await _upsert_agent_learning_profile(db, user_id, profile_payload)
    return profile_payload


def _build_agent_traits(
    *,
    profile: dict[str, Any],
    memories: list[dict[str, Any]],
    learning: dict[str, Any],
    accepted_rate: float | None,
    feedback_total: int,
    reason_counts: dict[str, int],
    action_type_stats: dict[str, dict[str, int]],
    existing_profile: dict[str, Any],
) -> dict[str, Any]:
    """把行为数据和反馈压缩为可展示、可控的学习风格画像。"""
    existing_controls = existing_profile.get("trait_controls", {}) if isinstance(existing_profile, dict) else {}
    ignored = set(existing_controls.get("ignored") or [])
    inaccurate = set(existing_controls.get("inaccurate") or [])
    locked = set(existing_controls.get("locked") or [])
    locked_values = existing_profile.get("locked_trait_values", {}) if isinstance(existing_profile.get("locked_trait_values"), dict) else {}
    traits: list[dict[str, Any]] = []

    def add_trait(trait_id: str, text: str, evidence: list[str], confidence: float, category: str = "learning_style") -> None:
        final_text = str(locked_values.get(trait_id) or text) if trait_id in locked else text
        traits.append({
            "id": trait_id,
            "text": final_text,
            "category": category,
            "evidence": evidence[:4],
            "confidence": round(max(0.0, min(1.0, confidence)), 2),
            "locked": trait_id in locked,
            "ignored": trait_id in ignored,
            "inaccurate": trait_id in inaccurate,
        })

    memory_text = "\n".join(str(m.get("value") or m.get("memory_value") or m.get("value_preview") or "") for m in memories).lower()
    if "短" in memory_text or "低打扰" in memory_text or reason_counts.get("too_long"):
        add_trait("prefers_short_clear_steps", "更适合短任务、低打扰、明确下一步", ["长期记忆/反馈提到短任务或低打扰", "too_long 反馈次数：%s" % reason_counts.get("too_long", 0)], 0.82, "planning_style")
    if reason_counts.get("too_disruptive"):
        add_trait("sensitive_to_interruptions", "对打断式提醒较敏感，建议低频、集中提示", ["too_disruptive 反馈次数：%s" % reason_counts.get("too_disruptive", 0)], 0.78, "friction")
    if reason_counts.get("too_hard"):
        add_trait("needs_scaffolded_difficulty", "遇到偏难建议时更需要台阶式拆解", ["too_hard 反馈次数：%s" % reason_counts.get("too_hard", 0)], 0.76, "friction")
    if reason_counts.get("too_easy"):
        add_trait("prefers_challenging_tasks", "对过于简单的建议容忍度较低，可适当提高挑战度", ["too_easy 反馈次数：%s" % reason_counts.get("too_easy", 0)], 0.72, "motivation_style")
    if learning.get("recent_distracted_rate", 0) >= 0.25:
        add_trait("benefits_from_short_focus_blocks", "近期更适合短专注块和即时反馈", [f"近 7 天走神率约 {round(float(learning.get('recent_distracted_rate') or 0) * 100)}%"], 0.74, "focus_pattern")
    if profile.get("optimal_hours"):
        add_trait("has_preferred_study_window", f"可能在 {profile.get('optimal_hours')} 学习效率更高", ["学习画像统计出的高效时段"], 0.7, "time_preference")
    if accepted_rate is not None and feedback_total >= 3:
        if accepted_rate < 0.4:
            add_trait("needs_more_explainable_suggestions", "对 Agent 建议较谨慎，需要更强解释和确认", [f"最近 {feedback_total} 条建议接受率约 {round(accepted_rate * 100)}%"], 0.8, "interaction_style")
        elif accepted_rate >= 0.7:
            add_trait("accepts_agent_coaching", "对 Agent 学习建议接受度较高，可适度主动提醒", [f"最近 {feedback_total} 条建议接受率约 {round(accepted_rate * 100)}%"], 0.76, "interaction_style")
    for action_type, stats in action_type_stats.items():
        total = stats.get("positive", 0) + stats.get("negative", 0)
        if total >= 2 and stats.get("negative", 0) > stats.get("positive", 0):
            add_trait(f"avoid_{action_type}_overuse", f"近期对 {action_type} 类建议反馈偏低，避免高频重复", [f"负反馈 {stats.get('negative', 0)} 次，正反馈 {stats.get('positive', 0)} 次"], 0.73, "friction")

    visible = [t for t in traits if not t["ignored"] and not t["inaccurate"]]
    do_more = []
    avoid = []
    if any(t["id"] == "prefers_short_clear_steps" for t in visible):
        do_more.extend(["把任务拆成 10-25 分钟的小步", "给出明确的下一步和完成标准"])
        avoid.extend(["一次性安排过长任务", "频繁打断式提醒"])
    if any(t["id"] == "needs_more_explainable_suggestions" for t in visible):
        do_more.append("解释建议依据并先征求确认")
        avoid.append("直接替用户改计划")
    if any(t["id"] == "accepts_agent_coaching" for t in visible):
        do_more.append("在低风险场景主动给出教练式建议")
    if any(t["id"] == "benefits_from_short_focus_blocks" for t in visible):
        do_more.append("优先推荐短专注块和复盘")
    return {
        "traits": visible[:10],
        "all_trait_items": traits[:16],
        "do_more": list(dict.fromkeys(do_more))[:8],
        "avoid": list(dict.fromkeys(avoid))[:8],
        "trait_controls": {"ignored": sorted(ignored), "inaccurate": sorted(inaccurate), "locked": sorted(locked)},
        "locked_trait_values": locked_values,
    }


async def _get_agent_learning_profile(db: AsyncSession, user_id: int) -> dict[str, Any]:
    result = await db.execute(
        select(UserMemory).where(
            UserMemory.user_id == user_id,
            UserMemory.memory_key == "agent_learning_profile",
        )
    )
    row = result.scalar_one_or_none()
    if not row:
        return {}
    data = _parse_memory_json(row.memory_value, {})
    return data if isinstance(data, dict) else {}


async def _upsert_agent_learning_profile(db: AsyncSession, user_id: int, payload: dict[str, Any]) -> None:
    key = "agent_learning_profile"
    result = await db.execute(select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.memory_key == key))
    row = result.scalar_one_or_none()
    now = datetime.now()
    value = json.dumps(payload, ensure_ascii=False)
    if row:
        if row.is_locked == 1:
            return
        row.memory_value = value
        row.category = "style"
        row.confidence = max(float(row.confidence or 0.0), 0.82)
        row.status = "active"
        row.memory_type = "semantic"
        row.last_seen_at = now
    else:
        db.add(
            UserMemory(
                user_id=user_id,
                memory_key=key,
                memory_value=value,
                category="style",
                confidence=0.82,
                status="active",
                is_locked=0,
                memory_type="semantic",
                last_seen_at=now,
            )
        )


def _build_action_explanation(
    action: dict[str, Any],
    context: dict[str, Any],
    personalization: dict[str, Any],
    adjusted: bool,
    feedback: dict[str, Any] | None,
    reason_adjustments: list[str] | None = None,
) -> dict[str, Any]:
    action_type = action.get("action_type") or "plan"
    target = action.get("target") or {}
    topic = ""
    if isinstance(target, dict):
        topic = str(target.get("knowledge_point") or target.get("name") or target.get("title") or "")[:80]

    data_signals: list[str] = []
    if action.get("id") == "clear_due_review":
        data_signals.append(f"到期复习 {context['review'].get('due_review_count', 0)} 条")
    if action.get("id") == "rescue_overdue_task":
        data_signals.append(f"过期任务 {context['tasks'].get('overdue_task_count', 0)} 个")
    if action.get("id") == "start_today_focus":
        data_signals.append(f"今日任务 {context['tasks'].get('today_task_count', 0)} 个")
    if action.get("id") == "weakness_drill" and topic:
        data_signals.append(f"错题薄弱点：{topic}")
    if action.get("id") == "reduce_distraction":
        data_signals.append(f"近 7 天走神率 {round(float(context['learning'].get('recent_distracted_rate') or 0) * 100)}%")
    if not data_signals:
        data_signals.append("当前任务、复习、错题和学习节奏综合判断")

    feedback_refs: list[str] = []
    for impact in personalization.get("feedback_impacts") or []:
        if impact.get("key") in {action_type, topic}:
            feedback_refs.append(str(impact.get("message")))
    if feedback:
        feedback_refs.append(f"你最近对该建议反馈为「{feedback.get('outcome_label')}」")

    reason_adjustments = reason_adjustments or []
    natural_summary = "我主要参考了" + "、".join(data_signals[:2]) + "。"
    if reason_adjustments:
        natural_summary += "这次根据你选择的反馈原因做了调整：" + "；".join(reason_adjustments[:2]) + "。"
    elif feedback_refs:
        natural_summary += "同时结合了你最近的反馈，所以会更克制地推荐。"
    elif adjusted:
        natural_summary += "因为类似建议近期反馈偏低，这次只低频提醒。"
    else:
        natural_summary += "目前没有明显负反馈，所以按正常优先级推荐。"

    return {
        "summary": natural_summary,
        "data_signals": data_signals[:4],
        "feedback_refs": feedback_refs[:4],
        "recommendation_reason": action.get("reason", ""),
        "adjustment": "；".join(reason_adjustments[:4]) if reason_adjustments else ("因近期负反馈已降低优先级，避免重复打扰。" if adjusted else "未发现强负反馈，按当前状态正常推荐。"),
        "reason_adjustments": reason_adjustments[:4],
        "audit": {
            "action_type": action_type,
            "topic": topic,
            "source": action.get("source") or "rules",
            "write_requires_confirmation": action.get("id") in {"make_today_minimum_plan", "weakness_drill", "reduce_distraction", "maintain_rhythm"} or str(action.get("id", "")).startswith("llm_action_"),
        },
    }


def _lower_priority(priority: Any) -> str:
    if priority == "high":
        return "medium"
    return "low"


def _raise_priority(priority: Any) -> str:
    if priority == "low":
        return "medium"
    return str(priority or "medium")


def _prefix_title(action: dict[str, Any], prefix: str) -> None:
    title = str(action.get("title") or "")
    if not title.startswith(prefix):
        action["title"] = f"{prefix}{title}"[:80]


def _append_reason(action: dict[str, Any], text: str) -> None:
    reason = str(action.get("reason") or "")
    if text not in reason:
        action["reason"] = f"{reason}（{text}）"


def _personalize_actions(actions: list[dict[str, Any]], personalization: dict[str, Any], context: dict[str, Any]) -> list[dict[str, Any]]:
    avoid = set(personalization.get("avoid_action_ids") or [])
    avoid_types = set(personalization.get("avoid_action_types") or [])
    avoid_topics = set(personalization.get("avoid_topics") or [])
    raw_recent_feedback = [f for f in personalization.get("recent_feedback", []) if f.get("action_id")]
    recent_feedback = {f.get("action_id"): f for f in raw_recent_feedback}
    feedback_reason_codes_by_action: dict[str, set[str]] = {}
    for item in raw_recent_feedback:
        action_id = str(item.get("action_id") or "")
        reason_code = str(item.get("reason_code") or "")
        if action_id and reason_code:
            feedback_reason_codes_by_action.setdefault(action_id, set()).add(reason_code)
    feedback_stats = personalization.get("feedback_stats") or {}
    reason_counts: dict[str, int] = feedback_stats.get("by_reason_code") or {}
    reason_action_types: dict[str, dict[str, int]] = feedback_stats.get("by_reason_action_type") or {}
    reason_topics: dict[str, dict[str, int]] = feedback_stats.get("by_reason_topic") or {}

    def reason_applies(reason_code: str, action: dict[str, Any], feedback: dict[str, Any] | None, topic: str) -> bool:
        if not reason_counts.get(reason_code):
            return False
        action_id = str(action.get("id") or "")
        feedback_reason_codes = feedback_reason_codes_by_action.get(action_id) or set()
        if feedback_reason_codes:
            return reason_code in feedback_reason_codes
        action_type = str(action.get("action_type") or "")
        if action_type and action_type in (reason_action_types.get(reason_code) or {}):
            return True
        if topic and topic in (reason_topics.get(reason_code) or {}):
            return True
        return False

    adjusted: list[dict[str, Any]] = []
    for action in actions:
        copied = dict(action)
        feedback = recent_feedback.get(copied.get("id"))
        target = copied.get("target") or {}
        topic = ""
        if isinstance(target, dict):
            topic = str(target.get("knowledge_point") or target.get("name") or target.get("title") or "")[:80]
        action_type = str(copied.get("action_type") or "")
        should_deprioritize = (
            copied.get("id") in avoid
            or action_type in avoid_types
            or bool(topic and topic in avoid_topics)
        )
        reason_adjustments: list[str] = []

        if should_deprioritize:
            copied["priority"] = "low"
            _append_reason(copied, "近期反馈显示你可能不想频繁收到这类建议，因此仅低频提醒。")
        else:
            _append_reason(copied, "依据当前学习画像与最近反馈生成。")

        if reason_counts.get("too_long") and (
            reason_applies("too_long", copied, feedback, topic)
            or (
                int(copied.get("estimated_minutes") or 0) > 10
                and not reason_adjustments
                and not (feedback and feedback.get("reason_code") in {"too_easy", "already_known", "too_hard", "too_late", "too_disruptive"})
            )
        ):
            original_minutes = int(copied.get("estimated_minutes") or 10)
            if original_minutes > 10:
                copied["estimated_minutes"] = 10
            else:
                copied["estimated_minutes"] = max(5, original_minutes)
            _prefix_title(copied, "10 分钟切片：")
            note = "你反馈过建议太长，所以先给 5-10 分钟可完成的第一步"
            _append_reason(copied, note)
            reason_adjustments.append(note)

        if reason_counts.get("too_hard") and (
            reason_applies("too_hard", copied, feedback, topic)
            or (
                action_type in {"practice", "review", "task", "plan"}
                and not reason_adjustments
                and not (feedback and feedback.get("reason_code") in {"too_easy", "already_known"})
            )
        ):
            copied["estimated_minutes"] = min(int(copied.get("estimated_minutes") or 15), 10)
            copied["priority"] = _lower_priority(copied.get("priority")) if copied.get("priority") == "high" else copied.get("priority", "medium")
            _prefix_title(copied, "小步开始：")
            note = "你反馈过难度偏高，所以先拆成更小、更容易启动的步骤"
            _append_reason(copied, note)
            reason_adjustments.append(note)

        if reason_counts.get("too_disruptive") and (
            reason_applies("too_disruptive", copied, feedback, topic)
            or (action_type in {"review", "task", "focus", "intervention"} and not reason_adjustments)
        ):
            copied["priority"] = "low"
            _prefix_title(copied, "低噪音备选：")
            note = "你反馈过太打扰，所以这类建议只作为低噪音备选，不主动催促"
            _append_reason(copied, note)
            reason_adjustments.append(note)

        easy_codes = ["too_easy", "already_known"]
        if feedback and feedback.get("reason_code") in easy_codes:
            easy_codes = [str(feedback["reason_code"])] + [code for code in easy_codes if code != feedback.get("reason_code")]
        for easy_code in easy_codes:
            if reason_counts.get(easy_code) and reason_applies(easy_code, copied, feedback, topic) and not reason_adjustments:
                label = _reason_label(easy_code)
                if easy_code == "already_known":
                    copied["priority"] = "low"
                    note = f"你反馈过该主题{label}，所以降低同主题基础建议的优先级"
                else:
                    copied["priority"] = _raise_priority(copied.get("priority"))
                    copied["estimated_minutes"] = min(max(int(copied.get("estimated_minutes") or 15), 15), 30)
                    _prefix_title(copied, "进阶挑战：")
                    note = f"你反馈过{label}，所以改为更深入一点的下一步"
                _append_reason(copied, note)
                reason_adjustments.append(note)
                break

        if reason_counts.get("too_late") and (
            reason_applies("too_late", copied, feedback, topic)
            or (copied.get("id") in {"clear_due_review", "rescue_overdue_task"} and not reason_adjustments)
        ):
            copied["priority"] = "low"
            copied["estimated_minutes"] = min(int(copied.get("estimated_minutes") or 15), 10)
            _prefix_title(copied, "低频补救备选：")
            note = "你反馈过时机太晚，所以避免紧急催促，只保留不打断当前节奏的补救入口"
            _append_reason(copied, note)
            reason_adjustments.append(note)

        copied["explainability"] = _build_action_explanation(copied, context, personalization, should_deprioritize or bool(reason_adjustments), feedback, reason_adjustments)
        adjusted.append(copied)

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    adjusted.sort(key=lambda x: (priority_rank.get(x.get("priority"), 9), x.get("estimated_minutes", 99)))
    return adjusted[:5]


def _build_actions(context: dict[str, Any]) -> list[dict[str, Any]]:
    actions: list[dict[str, Any]] = []
    review = context["review"]
    tasks = context["tasks"]
    learning = context["learning"]
    weaknesses = context["weaknesses"].get("weak_points_ranked", [])
    profile = context.get("profile") or {}

    if review["due_review_count"] > 0:
        actions.append(
            {
                "id": "clear_due_review",
                "title": f"先清理 {min(review['due_review_count'], 3)} 条到期复习",
                "reason": "到期复习是遗忘曲线风险最高的部分，先处理能最快降低长期损失。",
                "action_type": "review",
                "priority": "high" if review["due_review_count"] >= 5 else "medium",
                "estimated_minutes": 15,
                "route": "/review",
                "target": review["due_review_items"][0] if review["due_review_items"] else None,
            }
        )

    if tasks["overdue_task_count"] > 0:
        first = tasks["overdue_tasks"][0]
        actions.append(
            {
                "id": "rescue_overdue_task",
                "title": f"补救过期任务：{first['title'][:24]}",
                "reason": "过期任务会持续制造心理负担，建议只取最小可完成切片，不要一次性补全部。",
                "action_type": "task",
                "priority": "high" if tasks["overdue_task_count"] >= 3 else "medium",
                "estimated_minutes": 25,
                "route": "/goals",
                "target": first,
            }
        )

    if tasks["today_tasks"]:
        first = tasks["today_tasks"][0]
        actions.append(
            {
                "id": "start_today_focus",
                "title": f"开启一个专注块：{first['title'][:24]}",
                "reason": "今天已有明确任务，直接进入 25 分钟执行比重新规划更有效。",
                "action_type": "focus",
                "priority": "medium",
                "estimated_minutes": 25,
                "route": "/pomodoro",
                "target": first,
            }
        )
    elif tasks["active_goals"]:
        actions.append(
            {
                "id": "make_today_minimum_plan",
                "title": "为当前目标生成今天的最小行动",
                "reason": "你有活跃目标但今天没有明确任务，Agent 建议先生成一个可完成的最小计划。",
                "action_type": "plan",
                "priority": "medium",
                "estimated_minutes": 5,
                "route": "/plans",
                "target": tasks["active_goals"][0],
            }
        )

    if weaknesses:
        wp = weaknesses[0]
        actions.append(
            {
                "id": "weakness_drill",
                "title": f"针对薄弱点专项练习：{wp['name']}",
                "reason": f"错题记录显示该知识点出现 {wp['count']} 次，是当前最值得优先修补的短板。",
                "action_type": "practice",
                "priority": "medium",
                "estimated_minutes": 20,
                "route": "/wrong-questions",
                "target": wp,
            }
        )

    if learning["recent_distracted_rate"] >= 0.25:
        actions.append(
            {
                "id": "reduce_distraction",
                "title": "降低走神率：下一轮只设 15 分钟",
                "reason": "最近走神中断比例偏高，短专注块更容易恢复掌控感。",
                "action_type": "intervention",
                "priority": "medium",
                "estimated_minutes": 15,
                "route": "/pomodoro",
                "target": {"duration": 15},
            }
        )

    if not actions:
        optimal = profile.get("optimal_hours")
        actions.append(
            {
                "id": "maintain_rhythm",
                "title": "保持节奏：完成一次轻量复盘",
                "reason": f"当前没有明显积压。{f'建议继续把难任务放在 {optimal}。' if optimal else '建议记录今天最有效的学习方式。'}",
                "action_type": "reflect",
                "priority": "low",
                "estimated_minutes": 10,
                "route": "/eda",
                "target": None,
            }
        )

    priority_rank = {"high": 0, "medium": 1, "low": 2}
    actions.sort(key=lambda x: (priority_rank.get(x["priority"], 9), x["estimated_minutes"]))
    return actions[:5]


def _sanitize_llm_actions(items: Any) -> list[dict[str, Any]]:
    if not isinstance(items, list):
        return []
    sanitized: list[dict[str, Any]] = []
    for idx, item in enumerate(items[:5]):
        if not isinstance(item, dict):
            continue
        title = str(item.get("title") or "").strip()[:80]
        reason = str(item.get("reason") or "").strip()[:180]
        if not title or not reason:
            continue
        action_type = str(item.get("action_type") or "plan").strip()[:30]
        try:
            estimated = int(item.get("estimated_minutes") or 15)
        except Exception:
            estimated = 15
        estimated = int(max(5, min(90, estimated)))
        sanitized.append(
            {
                "id": str(item.get("id") or f"llm_action_{idx + 1}")[:60],
                "title": title,
                "reason": reason,
                "action_type": action_type,
                "priority": _normalize_priority(item.get("priority")),
                "estimated_minutes": estimated,
                "route": _normalize_route(item.get("route"), action_type),
                "target": item.get("target") if isinstance(item.get("target"), dict) else None,
                "source": "llm",
            }
        )
    return sanitized


def _build_planner_prompt(context: dict[str, Any], rule_actions: list[dict[str, Any]]) -> str:
    compact_context = {
        "profile": context.get("profile", {}),
        "tasks": {
            "active_goals": context["tasks"].get("active_goals", [])[:3],
            "today_tasks": context["tasks"].get("today_tasks", [])[:5],
            "overdue_tasks": context["tasks"].get("overdue_tasks", [])[:5],
            "unscheduled_task_count": context["tasks"].get("unscheduled_task_count", 0),
        },
        "review": {
            "due_review_count": context["review"].get("due_review_count", 0),
            "due_review_items": context["review"].get("due_review_items", [])[:5],
        },
        "learning": context.get("learning", {}),
        "weaknesses": context["weaknesses"].get("weak_points_ranked", [])[:5],
        "memories": context["memory"].get("memories", [])[:5],
        "rule_actions": rule_actions[:5],
    }
    return (
        "你是自主学习 Agent 的 planner。请基于用户学习上下文生成今天最小可执行计划。"
        "只输出 JSON 对象，不要输出 Markdown 或解释。\n"
        "JSON 格式：{"
        "\"strategy\":\"一句话今日策略\","
        "\"fallback_plan\":\"状态差或时间不足时的保底方案\","
        "\"next_actions\":[{\"id\":\"...\",\"title\":\"...\",\"reason\":\"...\","
        "\"action_type\":\"review|task|plan|practice|focus|intervention|reflect\","
        "\"priority\":\"high|medium|low\",\"estimated_minutes\":15,\"route\":\"/review|/goals|/plans|/wrong-questions|/pomodoro|/eda|/agent\"}]"
        "}\n"
        "要求：1) 最多 3 个行动；2) 优先具体、短时、可执行；3) 不要要求用户一次性补完所有积压；"
        "4) 不能编造不存在的资料或任务 ID；5) 如果规则行动合理，可以沿用并改写得更像教练。\n\n"
        f"学习上下文：{json.dumps(compact_context, ensure_ascii=False, default=str)[:6000]}"
    )


async def _apply_llm_planner(
    db: AsyncSession,
    user_id: int,
    context: dict[str, Any],
    rule_actions: list[dict[str, Any]],
) -> tuple[list[dict[str, Any]], str | None, str | None, dict[str, Any]]:
    metadata: dict[str, Any] = {"source": "rules", "error": None}
    try:
        from app.ai.factory import AIProviderFactory

        provider = await AIProviderFactory.create_provider(db=db, scenario="agent_planner", user_id=user_id)
        timeout = max(1.0, float(getattr(settings, "AGENT_LLM_PLANNER_TIMEOUT_SECONDS", 12.0) or 12.0))
        raw = await asyncio.wait_for(
            provider.chat(
                messages=[{"role": "user", "content": _build_planner_prompt(context, rule_actions)}],
                system_prompt="你是结构化学习计划生成器，只输出合法 JSON。",
                temperature=0.2,
            ),
            timeout=timeout,
        )
        data = _extract_json_object(raw)
        if not data:
            metadata["error"] = "invalid_json"
            return rule_actions, None, None, metadata
        actions = _sanitize_llm_actions(data.get("next_actions"))
        strategy = str(data.get("strategy") or "").strip()[:240] or None
        fallback = str(data.get("fallback_plan") or "").strip()[:240] or None
        metadata["source"] = "llm" if actions else "rules_fallback"
        return (actions or rule_actions), strategy, fallback, metadata
    except asyncio.TimeoutError:
        metadata["source"] = "rules_fallback"
        metadata["error"] = "llm_timeout"
        logger.info("Agent LLM planner timed out; falling back to rules")
        return rule_actions, None, None, metadata
    except Exception as exc:
        metadata["source"] = "rules_fallback"
        metadata["error"] = str(exc)[:240]
        logger.info("Agent LLM planner skipped or failed: %s", exc)
        return rule_actions, None, None, metadata


def _compute_scores(context: dict[str, Any]) -> tuple[float, str, str]:
    profile = context.get("profile") or {}
    review = context["review"]
    tasks = context["tasks"]
    learning = context["learning"]
    memory_count = context["memory"].get("active_memory_count", 0)

    focus = float(profile.get("focus_score") or 50)
    consistency = float(profile.get("consistency_score") or 50)
    planning = float(profile.get("planning_score") or 50)
    score = focus * 0.35 + consistency * 0.3 + planning * 0.2 + min(memory_count * 2, 15)

    if review["due_review_count"] >= 8:
        score -= 18
    elif review["due_review_count"] >= 3:
        score -= 8
    if tasks["overdue_task_count"] >= 3:
        score -= 15
    elif tasks["overdue_task_count"] > 0:
        score -= 6
    if learning["today_minutes"] < 15 and tasks["today_task_count"] > 0:
        score -= 8
    if learning["recent_distracted_rate"] >= 0.3:
        score -= 8

    if review["due_review_count"] >= 8 or tasks["overdue_task_count"] >= 4:
        risk = "high"
    elif review["due_review_count"] >= 3 or tasks["overdue_task_count"] > 0 or learning["recent_distracted_rate"] >= 0.25:
        risk = "medium"
    else:
        risk = "low"

    study_days = int(profile.get("total_study_days") or 0)
    if study_days >= 14 and memory_count >= 8:
        autonomy = "copilot+"
    elif study_days >= 7 or memory_count >= 4:
        autonomy = "copilot"
    elif study_days >= 3 or memory_count >= 2:
        autonomy = "coach"
    else:
        autonomy = "observe"

    return round(_clamp(score), 1), risk, autonomy


def _build_summary(context: dict[str, Any], readiness: float, risk: str, autonomy: str, actions: list[dict[str, Any]]) -> str:
    profile = context.get("profile") or {}
    review = context["review"]
    tasks = context["tasks"]
    learning = context["learning"]
    weak = context["weaknesses"].get("weak_points_ranked", [])
    parts = [f"Agent 当前处于 {autonomy} 模式，准备度 {readiness:.0f}/100，风险等级 {risk}。"]
    if profile.get("optimal_hours"):
        parts.append(f"你的高效时段倾向于 {profile['optimal_hours']}。")
    if review["due_review_count"]:
        parts.append(f"现在有 {review['due_review_count']} 条到期复习。")
    if tasks["overdue_task_count"] or tasks["today_task_count"]:
        parts.append(f"今日任务 {tasks['today_task_count']} 个，过期任务 {tasks['overdue_task_count']} 个。")
    if weak:
        parts.append(f"最高优先薄弱点是 {weak[0]['name']}。")
    if learning["recent_distracted_count"]:
        parts.append(f"近 7 天有 {learning['recent_distracted_count']} 次走神中断。")
    personalization = context.get("personalization") or {}
    learned = personalization.get("learned_preferences") or []
    if learned:
        parts.append(f"我会参考：{learned[0]}。")
    if actions:
        parts.append(f"建议下一步：{actions[0]['title']}。")
    return "".join(parts)


async def build_agent_brief(db: AsyncSession, user_id: int, use_llm: bool = False) -> dict[str, Any]:
    now = datetime.now()
    today = date.today()
    profile_obj = await get_or_compute_profile(db, user_id)
    profile: dict[str, Any] = {}
    if profile_obj:
        profile = {
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

    context = {
        "profile": profile,
        "tasks": await _collect_task_state(db, user_id, today),
        "review": await _collect_review_state(db, user_id, now),
        "learning": await _collect_learning_state(db, user_id, today, now),
        "weaknesses": await _collect_weakness_state(db, user_id),
        "memory": await _collect_memory_state(db, user_id),
    }
    personalization = await _collect_agent_personalization(db, user_id, context)
    actions = _personalize_actions(_build_actions(context), personalization, context)
    context["personalization"] = personalization
    planner_strategy = None
    fallback_plan = None
    planner_source = "rules"
    planner_error = None
    if use_llm:
        planned_actions, planner_strategy, fallback_plan, planner_meta = await _apply_llm_planner(db, user_id, context, actions)
        planner_source = str(planner_meta.get("source") or "rules")
        planner_error = planner_meta.get("error")
        actions = planned_actions
    readiness, risk, autonomy = _compute_scores(context)
    summary = _build_summary(context, readiness, risk, autonomy, actions)
    if planner_strategy:
        summary = f"{summary}LLM Planner 策略：{planner_strategy}"

    watch_signals = []
    if context["review"]["due_review_count"] >= 3:
        watch_signals.append("复习积压正在升高，优先处理最旧的到期项。")
    if context["tasks"]["overdue_task_count"] > 0:
        watch_signals.append("存在过期任务，建议只保留一个最小补救动作。")
    if context["learning"]["recent_distracted_rate"] >= 0.25:
        watch_signals.append("近期走神率偏高，建议缩短下一轮专注时长。")
    if not watch_signals:
        watch_signals.append("当前没有明显高风险信号，重点是维持节奏和复盘有效方法。")

    return {
        "date": today.isoformat(),
        "generated_at": now.isoformat(),
        "autonomy_level": autonomy,
        "readiness_score": readiness,
        "risk_level": risk,
        "state_summary": summary,
        "current_focus": actions[0]["title"] if actions else "保持学习节奏",
        "next_actions": actions,
        "watch_signals": watch_signals,
        "planner": {
            "source": planner_source,
            "strategy": planner_strategy,
            "fallback_plan": fallback_plan,
            "error": planner_error,
        },
        "context": context,
    }


def _find_action(brief: dict[str, Any], action_id: str) -> dict[str, Any] | None:
    for action in brief.get("next_actions") or []:
        if action.get("id") == action_id:
            return action
    return None


def _task_draft_from_action(brief: dict[str, Any], action: dict[str, Any]) -> dict[str, Any]:
    today = date.today()
    context = brief.get("context") or {}
    tasks = context.get("tasks") or {}
    active_goals = tasks.get("active_goals") or []
    target = action.get("target") or {}
    goal_id = target.get("goal_id") or target.get("id")
    if action.get("id") in {"weakness_drill", "reduce_distraction", "maintain_rhythm"} and active_goals:
        goal_id = active_goals[0].get("id")

    title = action.get("title") or "Agent 推荐学习任务"
    task_type = "learn"
    description = action.get("reason") or "由自主学习 Agent 根据当前状态生成。"

    if action.get("id") == "make_today_minimum_plan":
        goal_title = target.get("title") or "当前目标"
        title = f"完成《{goal_title}》的今日最小行动"
        description = "Agent 发现当前目标今天没有明确任务，建议先完成一个 25 分钟以内的最小学习切片。"
    elif action.get("id") == "weakness_drill":
        point = target.get("name") or "薄弱点"
        title = f"专项练习：{point}"
        task_type = "practice"
        description = f"围绕高频错题知识点「{point}」做 2-3 道同类题，并写一句错因总结。"
    elif action.get("id") == "reduce_distraction":
        title = "15 分钟低干扰专注块"
        description = "最近走神率偏高，先用短专注块恢复掌控感：关闭干扰源，只完成一个小切片。"
    elif action.get("id") == "maintain_rhythm":
        title = "10 分钟学习复盘"
        task_type = "summarize"
        description = "记录今天最有效的学习方式、一个卡点和明天的最小行动。"
    elif action.get("id", "").startswith("llm_action_") and active_goals:
        goal_id = active_goals[0].get("id")
        if action.get("action_type") in {"learn", "review", "practice", "summarize"}:
            task_type = action["action_type"]

    return {
        "operation": "create_task" if goal_id else "navigate",
        "goal_id": goal_id,
        "title": str(title)[:200],
        "description": str(description)[:1000],
        "task_type": task_type,
        "planned_date": today.isoformat(),
        "estimated_minutes": action.get("estimated_minutes") or 15,
        "route": action.get("route") or "/agent",
    }


async def build_agent_action_draft(
    db: AsyncSession,
    user_id: int,
    action_id: str,
    use_llm: bool = False,
) -> dict[str, Any]:
    brief = await build_agent_brief(db, user_id, use_llm=use_llm)
    action = _find_action(brief, action_id)
    if not action:
        raise ValueError("行动建议已变化，请刷新 Agent 简报后重试")

    executable_ids = {"make_today_minimum_plan", "weakness_drill", "reduce_distraction", "maintain_rhythm"}
    if str(action_id).startswith("llm_action_") or action_id in executable_ids:
        draft = _task_draft_from_action(brief, action)
    else:
        draft = {"operation": "navigate", "route": action.get("route") or "/agent"}

    return {"action": action, "draft": draft, "requires_confirmation": draft.get("operation") == "create_task"}


async def execute_agent_action(
    db: AsyncSession,
    user_id: int,
    action_id: str,
    use_llm: bool = False,
) -> dict[str, Any]:
    payload = await build_agent_action_draft(db, user_id, action_id, use_llm=use_llm)
    action = payload["action"]
    draft = payload["draft"]
    if draft.get("operation") != "create_task":
        await remember_agent_feedback(db, user_id, action_id, "navigated", "用户选择跳转执行 Agent 建议", None, action)
        return {"status": "navigated", "action": action, "draft": draft, "created_task": None, "route": draft.get("route")}

    goal_id = draft.get("goal_id")
    goal_result = await db.execute(select(Goal).where(Goal.id == goal_id, Goal.user_id == user_id, Goal.status == "active"))
    if not goal_result.scalar_one_or_none():
        raise ValueError("目标不存在或已不可用，请刷新 Agent 简报后重试")

    task = Task(
        goal_id=goal_id,
        title=draft["title"],
        description=draft.get("description"),
        task_type=draft.get("task_type") or "learn",
        planned_date=date.fromisoformat(draft["planned_date"]),
        status="pending",
    )
    db.add(task)
    await db.flush()
    await db.refresh(task)
    created = {
        "id": task.id,
        "goal_id": task.goal_id,
        "title": task.title,
        "description": task.description,
        "task_type": task.task_type,
        "planned_date": task.planned_date.isoformat() if task.planned_date else None,
        "status": task.status,
        "route": "/goals",
    }
    await remember_agent_feedback(db, user_id, action_id, "accepted", f"已创建任务：{task.title}", 0.8, action)
    return {"status": "created", "action": action, "draft": draft, "created_task": created, "route": "/goals"}


def _heuristic_write_intent(message: str, today: date) -> dict[str, Any]:
    text = (message or "").strip()
    lowered = text.lower()
    note_triggers = [
        "记个笔记",
        "记一条笔记",
        "记一个笔记",
        "记个灵感",
        "记一个灵感",
        "记录一下",
        "写入笔记",
        "存到笔记",
        "保存到笔记",
        "记到笔记",
        "记进笔记",
        "突然有个想法",
        "临时有个想法",
        "有个想法",
        "有一个想法",
        "我想到",
    ]
    plan_triggers = [
        "今天的任务",
        "今天任务",
        "今日任务",
        "今天的计划",
        "今天计划",
        "今日计划",
        "今天待办",
        "今日待办",
        "加入今天计划",
        "加到今天计划",
        "写到今天计划",
        "安排到今天",
        "明天的任务",
        "明天任务",
        "明日任务",
        "明天的计划",
        "明天计划",
        "明日计划",
        "明天待办",
        "明日待办",
        "安排到明天",
        "后天的任务",
        "后天计划",
    ]
    task_triggers = [
        "创建任务",
        "添加任务",
        "加入任务",
        "安排任务",
        "制定任务",
        "拆成任务",
        "拆成子任务",
        "拆解任务",
        "生成任务",
        "做成任务",
        "目标是",
        "我的目标",
        "接下来我要",
        "接下来我的目标",
    ]

    if any(trigger in text for trigger in note_triggers):
        content = _clean_note_content(text)
        title = _compact_text(content.splitlines()[0], 48) or "对话笔记"
        note_type, tags = _classify_note(content, text)
        if "对话记录" not in tags:
            tags.append("对话记录")
        return {
            "intent": "create_note",
            "confidence": 0.78,
            "summary": f"创建{tags[0] if tags else '笔记'}「{title}」",
            "draft": {
                "title": title,
                "content": content,
                "note_type": note_type,
                "tags": tags[:6],
            },
        }

    if any(trigger in text for trigger in plan_triggers):
        tasks = _extract_plan_items(text, today)
        return {
            "intent": "add_daily_plan_items",
            "confidence": 0.82,
            "summary": f"加入 {len(tasks)} 条到当天计划",
            "draft": {
                "date": tasks[0]["planned_date"] if tasks else today.isoformat(),
                "items": tasks,
                "also_create_tasks": False,
            },
        }

    if any(trigger in text for trigger in task_triggers):
        goal_title = "学习目标"
        goal_match = re.search(r"(?:目标是|我的目标是|接下来我的目标是|接下来我要|我要)([^，。；;\n]+)", text)
        if goal_match:
            goal_title = _compact_text(goal_match.group(1), 60)
        elif "英语" in text:
            goal_title = "英语学习计划"

        def clean_task_phrase(value: str) -> str:
            cleaned = re.sub(r"^(把|将|请把|请将|帮我把|帮我将)", "", value).strip()
            cleaned = re.sub(r"(拆成|拆为|拆解成|生成|做成|转成|变成)(子)?任务$", "", cleaned).strip()
            cleaned = re.sub(r"(拆成|拆为|拆解成|生成|做成|转成|变成)(子)?任务", "", cleaned).strip()
            return _compact_text(cleaned or value, 80)

        task_phrases: list[str] = []
        for part in re.split(r"[，,。；;、\n]+", text):
            clean = clean_task_phrase(part)
            if not clean:
                continue
            if any(keyword in clean for keyword in ["精读", "精听", "阅读", "听力", "复习", "练习", "背诵", "总结"]):
                task_phrases.append(clean)

        tasks = []
        for phrase in task_phrases[:8]:
            task_type = "practice" if any(k in phrase for k in ["练习", "刷题"]) else "review" if "复习" in phrase else "summarize" if "总结" in phrase else "learn"
            tasks.append({
                "title": phrase,
                "description": "由对话 Agent 根据你的自然语言计划生成。",
                "task_type": task_type,
                "planned_date": today.isoformat(),
            })
        if not tasks:
            tasks.append({
                "title": goal_title,
                "description": "由对话 Agent 根据你的自然语言计划生成。",
                "task_type": "learn",
                "planned_date": today.isoformat(),
            })

        return {
            "intent": "create_goal_tasks",
            "confidence": 0.7,
            "summary": f"创建/复用目标「{goal_title}」，并安排 {len(tasks)} 个任务",
            "draft": {
                "goal_title": goal_title,
                "goal_description": text[:500],
                "tasks": tasks,
            },
        }

    return {"intent": "none", "confidence": 0.0, "summary": "", "draft": {}}


def _sanitize_write_intent(raw: dict[str, Any] | None, message: str, today: date) -> dict[str, Any]:
    fallback = _heuristic_write_intent(message, today)
    if not raw:
        return fallback
    intent = str(raw.get("intent") or "none").strip()
    if intent not in {"none", "create_note", "create_goal_tasks", "add_daily_plan_items"}:
        return fallback
    try:
        confidence = float(raw.get("confidence") or 0)
    except Exception:
        confidence = 0
    confidence = max(0.0, min(1.0, confidence))
    if intent == "none":
        if fallback.get("intent") != "none" and float(fallback.get("confidence") or 0) >= 0.65:
            return fallback
        return {"intent": "none", "confidence": confidence, "summary": "", "draft": {}}
    if confidence < 0.55:
        if fallback.get("intent") != "none" and float(fallback.get("confidence") or 0) >= 0.65:
            return fallback
        return {"intent": "none", "confidence": confidence, "summary": "", "draft": {}}

    if intent == "create_note":
        note = raw.get("note") if isinstance(raw.get("note"), dict) else raw.get("draft")
        if not isinstance(note, dict):
            return fallback
        content = _clean_note_content(str(note.get("content") or message).strip())[:8000]
        title = _compact_text(note.get("title") or content.splitlines()[0] or "对话笔记", 80)
        note_type, inferred_tags = _classify_note(content, message)
        tags_raw = note.get("tags") if isinstance(note.get("tags"), list) else []
        tags = [_compact_text(t, 20) for t in tags_raw if _compact_text(t, 20)]
        for tag in inferred_tags + ["对话记录"]:
            if tag and tag not in tags:
                tags.append(tag)
        return {
            "intent": "create_note",
            "confidence": confidence,
            "summary": _compact_text(raw.get("summary") or f"创建笔记「{title}」", 120),
            "draft": {
                "title": title,
                "content": content,
                "note_type": str(note.get("note_type") or note_type)[:20],
                "tags": tags[:6],
            },
        }

    if intent == "add_daily_plan_items":
        plan = raw.get("plan") if isinstance(raw.get("plan"), dict) else raw.get("draft")
        items_raw = plan.get("items") if isinstance(plan, dict) and isinstance(plan.get("items"), list) else []
        items = []
        for item in items_raw[:12]:
            if not isinstance(item, dict):
                continue
            title = _compact_text(item.get("title"), 120)
            if not title:
                continue
            planned = _parse_agent_date(item.get("planned_date") or (plan or {}).get("date"), today)
            task_type = str(item.get("task_type") or "learn").strip()
            if task_type not in {"learn", "review", "practice", "summarize"}:
                task_type = "learn"
            items.append({
                "title": title,
                "description": _compact_text(item.get("description") or "由对话 Agent 根据你的自然语言计划加入每日计划。", 800),
                "task_type": task_type,
                "planned_date": planned.isoformat(),
            })
        if not items:
            items = _extract_plan_items(message, today)
        plan_date = items[0]["planned_date"] if items else today.isoformat()
        return {
            "intent": "add_daily_plan_items",
            "confidence": confidence,
            "summary": _compact_text(raw.get("summary") or f"加入 {len(items)} 条到当天计划", 120),
            "draft": {
                "date": plan_date,
                "items": items[:12],
                "also_create_tasks": bool((plan or {}).get("also_create_tasks", False)) if isinstance(plan, dict) else False,
            },
        }

    goal = raw.get("goal") if isinstance(raw.get("goal"), dict) else raw.get("draft")
    if not isinstance(goal, dict):
        return fallback
    goal_title = _compact_text(goal.get("title") or goal.get("goal_title") or fallback.get("draft", {}).get("goal_title") or "学习目标", 80)
    goal_description = _compact_text(goal.get("description") or goal.get("goal_description") or message, 800)
    tasks_raw = goal.get("tasks") if isinstance(goal.get("tasks"), list) else []
    tasks = []
    for item in tasks_raw[:12]:
        if not isinstance(item, dict):
            continue
        title = _compact_text(item.get("title"), 120)
        if not title:
            continue
        task_type = str(item.get("task_type") or "learn").strip()
        if task_type not in {"learn", "review", "practice", "summarize"}:
            task_type = "learn"
        planned = _parse_agent_date(item.get("planned_date"), today)
        tasks.append({
            "title": title,
            "description": _compact_text(item.get("description") or "由对话 Agent 根据你的自然语言计划生成。", 800),
            "task_type": task_type,
            "planned_date": planned.isoformat(),
        })
    if not tasks:
        tasks = fallback.get("draft", {}).get("tasks") or []
    return {
        "intent": "create_goal_tasks",
        "confidence": confidence,
        "summary": _compact_text(raw.get("summary") or f"创建/复用目标「{goal_title}」，并安排 {len(tasks)} 个任务", 120),
        "draft": {
            "goal_title": goal_title,
            "goal_description": goal_description,
            "tasks": tasks[:12],
        },
    }


async def _detect_agent_write_intent(db: AsyncSession, user_id: int, message: str, today: date) -> dict[str, Any]:
    prompt = (
        "判断用户是否在请求你写入学习系统数据。只在用户明确要求记录、保存、创建、添加、安排时返回写入意图；"
        "普通提问、讨论、解释、聊天必须返回 none。\n"
        "支持三类写入：create_note（笔记/灵感/想法）、add_daily_plan_items（只加入当天/指定日期计划）、create_goal_tasks（创建目标与任务）。\n"
        "如果用户说“今天的任务/计划/待办是...”，优先返回 add_daily_plan_items，而不是 create_goal_tasks。\n"
        "note_type 只能使用 general|idea|method|summary|question|resource。\n"
        "输出严格 JSON，不要 Markdown：\n"
        "{"
        "\"intent\":\"none|create_note|add_daily_plan_items|create_goal_tasks\","
        "\"confidence\":0.0,"
        "\"summary\":\"简短中文摘要\","
        "\"note\":{\"title\":\"\",\"content\":\"\",\"note_type\":\"general|idea|method|summary|question|resource\",\"tags\":[\"\"]},"
        "\"plan\":{\"date\":\"YYYY-MM-DD|今天|明天\",\"items\":[{\"title\":\"\",\"description\":\"\",\"task_type\":\"learn|review|practice|summarize\",\"planned_date\":\"YYYY-MM-DD|今天|明天\"}],\"also_create_tasks\":false},"
        "\"goal\":{\"title\":\"\",\"description\":\"\",\"tasks\":[{\"title\":\"\",\"description\":\"\",\"task_type\":\"learn|review|practice|summarize\",\"planned_date\":\"YYYY-MM-DD|今天|明天\"}]}"
        "}\n"
        f"今天日期：{today.isoformat()}\n"
        f"用户消息：{message[:3000]}"
    )
    try:
        from app.ai.factory import AIProviderFactory

        provider = await AIProviderFactory.create_provider(db=db, scenario="agent_planner", user_id=user_id)
        raw = await asyncio.wait_for(
            provider.chat(
                messages=[{"role": "user", "content": prompt}],
                system_prompt="你是学习系统的安全工具路由器，只输出 JSON。",
                temperature=0.1,
            ),
            timeout=max(1.0, float(getattr(settings, "AGENT_LLM_PLANNER_TIMEOUT_SECONDS", 12.0) or 12.0)),
        )
        return _sanitize_write_intent(_extract_json_object(raw or ""), message, today)
    except Exception as exc:
        logger.info("Agent write intent detection fell back to heuristics: %s", exc)
        return _heuristic_write_intent(message, today)


async def _annotate_write_draft_duplicates(db: AsyncSession, user_id: int, intent: dict[str, Any]) -> dict[str, Any]:
    intent = json.loads(json.dumps(intent, ensure_ascii=False))
    draft = intent.get("draft") or {}
    duplicates: list[str] = []
    if intent.get("intent") == "create_note":
        title_key = _normalize_match_text(draft.get("title"))
        content_key = _normalize_match_text(draft.get("content"))
        result = await db.execute(select(Note).where(Note.user_id == user_id).order_by(Note.updated_at.desc()).limit(50))
        for note in result.scalars().all():
            if _normalize_match_text(note.title) == title_key or (content_key and _normalize_match_text(note.content) == content_key):
                duplicates.append(f"可能已存在同名/同内容笔记：{note.title}")
                draft["duplicate_note_id"] = note.id
                break
    elif intent.get("intent") == "add_daily_plan_items":
        plan_date = str(draft.get("date") or date.today().isoformat())[:10]
        draft["date"] = plan_date
        result = await db.execute(select(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.date == plan_date))
        row = result.scalar_one_or_none()
        existing_content = row.content if row else ""
        existing_lines = [re.sub(r"^[-*]\s*\[[ xX]\]\s*", "", line).strip() for line in existing_content.splitlines()]
        existing_lines = [re.sub(r"^[📖📝⚠️❌✅💡\s]+", "", line).strip() for line in existing_lines if line.strip()]
        for item in draft.get("items") or []:
            if not isinstance(item, dict):
                continue
            title = _compact_text(item.get("title"), 120)
            item["title"] = title
            item["planned_date"] = str(item.get("planned_date") or plan_date)[:10]
            item["duplicate"] = any(_similar_text(title, line) for line in existing_lines)
            if item["duplicate"]:
                duplicates.append(f"跳过当天计划重复项：{title}")
        if row:
            draft["existing_plan_id"] = row.id
    elif intent.get("intent") == "create_goal_tasks":
        goal_title = str(draft.get("goal_title") or "")
        goal_key = _normalize_match_text(goal_title)
        result = await db.execute(select(Goal).where(Goal.user_id == user_id, Goal.status == "active"))
        goals = list(result.scalars().all())
        matched_goal = next((g for g in goals if _normalize_match_text(g.title) == goal_key), None)
        if matched_goal:
            draft["existing_goal_id"] = matched_goal.id
            duplicates.append(f"将复用已有目标：{matched_goal.title}")
            task_result = await db.execute(select(Task).where(Task.goal_id == matched_goal.id))
            existing_tasks = list(task_result.scalars().all())
            existing_keys = {
                (_normalize_match_text(t.title), t.planned_date.isoformat() if t.planned_date else "")
                for t in existing_tasks
            }
            for task in draft.get("tasks") or []:
                if not isinstance(task, dict):
                    continue
                key = (_normalize_match_text(task.get("title")), str(task.get("planned_date") or ""))
                task["duplicate"] = key in existing_keys
                if task["duplicate"]:
                    duplicates.append(f"跳过重复任务：{task.get('title')}")
        else:
            draft["existing_goal_id"] = None
            for task in draft.get("tasks") or []:
                if isinstance(task, dict):
                    task["duplicate"] = False
    intent["draft"] = draft
    intent["duplicate_warnings"] = duplicates
    intent["requires_confirmation"] = intent.get("intent") in {"create_note", "create_goal_tasks", "add_daily_plan_items"}
    return intent


async def build_agent_write_draft(db: AsyncSession, user_id: int, message: str) -> dict[str, Any]:
    today = date.today()
    heuristic = _heuristic_write_intent(message, today)
    if heuristic.get("intent") != "none" and float(heuristic.get("confidence") or 0) >= 0.65:
        return await _annotate_write_draft_duplicates(db, user_id, heuristic)
    detected = await _detect_agent_write_intent(db, user_id, message, today)
    return await _annotate_write_draft_duplicates(db, user_id, detected)


async def execute_agent_write_draft(db: AsyncSession, user_id: int, intent: str, draft: dict[str, Any]) -> dict[str, Any]:
    if intent == "create_note":
        duplicate_note_id = draft.get("duplicate_note_id")
        if duplicate_note_id:
            result = await db.execute(select(Note).where(Note.id == int(duplicate_note_id), Note.user_id == user_id))
            note = result.scalar_one_or_none()
            if note:
                return {"status": "skipped_duplicate", "intent": intent, "created": None, "route": "/notes", "message": f"已存在笔记：{note.title}"}
        tags = draft.get("tags") if isinstance(draft.get("tags"), list) else []
        note = Note(
            user_id=user_id,
            title=_compact_text(draft.get("title") or "对话笔记", 120),
            content=str(draft.get("content") or "").strip()[:8000],
            note_type=str(draft.get("note_type") or "general")[:20],
            tags=json.dumps([_compact_text(t, 20) for t in tags if _compact_text(t, 20)][:6], ensure_ascii=False),
        )
        db.add(note)
        await db.flush()
        await db.refresh(note)
        return {
            "status": "created",
            "intent": intent,
            "created": {"note": {"id": note.id, "title": note.title, "route": "/notes"}},
            "route": "/notes",
            "message": f"已创建笔记：{note.title}",
        }

    if intent == "add_daily_plan_items":
        plan_date = str(draft.get("date") or date.today().isoformat())[:10]
        result = await db.execute(select(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.date == plan_date))
        row = result.scalar_one_or_none()
        existing_content = row.content if row else ""
        existing_lines = [re.sub(r"^[-*]\s*\[[ xX]\]\s*", "", line).strip() for line in existing_content.splitlines()]
        existing_lines = [re.sub(r"^[📖📝⚠️❌✅💡\s]+", "", line).strip() for line in existing_lines if line.strip()]
        created_items: list[dict[str, Any]] = []
        skipped_items: list[dict[str, Any]] = []
        for item in (draft.get("items") if isinstance(draft.get("items"), list) else [])[:12]:
            if not isinstance(item, dict):
                continue
            title = _compact_text(item.get("title"), 120)
            if not title:
                continue
            if bool(item.get("duplicate")) or any(_similar_text(title, line) for line in existing_lines):
                skipped_items.append({"title": title, "reason": "duplicate"})
                continue
            task_type = str(item.get("task_type") or "learn")
            emoji = "📖" if task_type == "review" else "✍️" if task_type == "practice" else "🧠" if task_type == "summarize" else "📝"
            line = f"- [ ] {emoji} {title}"
            existing_lines.append(title)
            created_items.append({"title": title, "line": line, "task_type": task_type})
        if row is None:
            header = f"# {plan_date} 学习计划\n"
            content = header + ("\n".join(item["line"] for item in created_items) if created_items else "今日计划已存在类似内容，未新增。")
            row = DailyPlan(user_id=user_id, date=plan_date, content=content)
            db.add(row)
        elif created_items:
            suffix = "\n" if row.content and not row.content.endswith("\n") else ""
            row.content = (row.content or "") + suffix + "\n".join(item["line"] for item in created_items)
        await db.flush()
        await db.refresh(row)
        return {
            "status": "created" if created_items else "skipped_duplicate",
            "intent": intent,
            "created": {"plan": {"id": row.id, "date": row.date, "route": "/plans"}, "items": created_items, "skipped_items": skipped_items},
            "route": "/plans",
            "message": f"已加入 {len(created_items)} 条到 {plan_date} 计划，跳过 {len(skipped_items)} 条重复项。",
        }

    if intent != "create_goal_tasks":
        raise ValueError("不支持的 Agent 写入类型")

    goal_id = draft.get("existing_goal_id")
    goal: Goal | None = None
    if goal_id:
        result = await db.execute(select(Goal).where(Goal.id == int(goal_id), Goal.user_id == user_id, Goal.status == "active"))
        goal = result.scalar_one_or_none()
    if goal is None:
        goal = Goal(
            user_id=user_id,
            title=_compact_text(draft.get("goal_title") or "学习目标", 120),
            description=str(draft.get("goal_description") or "")[:1000],
            status="active",
        )
        db.add(goal)
        await db.flush()
        await db.refresh(goal)

    task_result = await db.execute(select(Task).where(Task.goal_id == goal.id))
    existing_keys = {
        (_normalize_match_text(t.title), t.planned_date.isoformat() if t.planned_date else "")
        for t in task_result.scalars().all()
    }
    created_tasks: list[dict[str, Any]] = []
    skipped_tasks: list[dict[str, Any]] = []
    today = date.today()
    for item in (draft.get("tasks") if isinstance(draft.get("tasks"), list) else [])[:12]:
        if not isinstance(item, dict):
            continue
        title = _compact_text(item.get("title"), 120)
        if not title:
            continue
        planned = _parse_agent_date(item.get("planned_date"), today)
        key = (_normalize_match_text(title), planned.isoformat())
        if key in existing_keys or bool(item.get("duplicate")):
            skipped_tasks.append({"title": title, "planned_date": planned.isoformat(), "reason": "duplicate"})
            continue
        task_type = str(item.get("task_type") or "learn")
        if task_type not in {"learn", "review", "practice", "summarize"}:
            task_type = "learn"
        task = Task(
            goal_id=goal.id,
            title=title,
            description=str(item.get("description") or "由对话 Agent 根据你的自然语言计划生成。")[:1000],
            task_type=task_type,
            planned_date=planned,
            status="pending",
        )
        db.add(task)
        await db.flush()
        await db.refresh(task)
        existing_keys.add(key)
        created_tasks.append({
            "id": task.id,
            "title": task.title,
            "task_type": task.task_type,
            "planned_date": planned.isoformat(),
            "goal_id": goal.id,
        })

    return {
        "status": "created" if created_tasks else "skipped_duplicate",
        "intent": intent,
        "created": {
            "goal": {"id": goal.id, "title": goal.title, "route": "/goals"},
            "tasks": created_tasks,
            "skipped_tasks": skipped_tasks,
        },
        "route": "/goals",
        "message": f"已创建 {len(created_tasks)} 个任务，跳过 {len(skipped_tasks)} 个重复任务。",
    }


async def remember_agent_feedback(
    db: AsyncSession,
    user_id: int,
    action_id: str,
    outcome: str,
    notes: str | None = None,
    effectiveness: float | None = None,
    action: dict[str, Any] | None = None,
    reason_code: str | None = None,
) -> dict[str, Any]:
    now = datetime.now()
    key = f"agent_feedback_{date.today().isoformat()}_{now.strftime('%H%M%S%f')}_{action_id}"[:100]
    normalized_outcome = {"snoozed": "later", "rejected": "dismissed"}.get(outcome, outcome)
    reason_code = reason_code if reason_code in NEGATIVE_FEEDBACK_REASON_LABELS else None
    action = action or {}
    target = action.get("target") if isinstance(action.get("target"), dict) else {}
    explainability = action.get("explainability") if isinstance(action.get("explainability"), dict) else {}
    audit = explainability.get("audit") if isinstance(explainability.get("audit"), dict) else {}
    topic = str(
        (target or {}).get("knowledge_point")
        or (target or {}).get("name")
        or audit.get("topic")
        or (target or {}).get("title")
        or ""
    )[:100]
    source_signal = "；".join(str(x) for x in (explainability.get("data_signals") or [])[:3])
    value = {
        "action_id": action_id,
        "action_type": action.get("action_type") or audit.get("action_type"),
        "knowledge_point": topic,
        "topic": topic,
        "reason": action.get("reason", ""),
        "source_signal": source_signal,
        "source": action.get("source") or audit.get("source") or "rules",
        "reason_code": reason_code,
        "reason_label": _reason_label(reason_code),
        "outcome": normalized_outcome,
        "notes": (notes or "")[:500],
        "effectiveness": effectiveness,
        "recorded_at": now.isoformat(),
    }
    existing = await db.execute(select(UserMemory).where(UserMemory.user_id == user_id, UserMemory.memory_key == key))
    row = existing.scalar_one_or_none()
    if row:
        row.memory_value = json.dumps(value, ensure_ascii=False)
        row.confidence = max(float(row.confidence or 0.0), 0.75)
        row.last_seen_at = now
        row.status = "active"
    else:
        row = UserMemory(
            user_id=user_id,
            memory_key=key,
            memory_value=json.dumps(value, ensure_ascii=False),
            category="agent_feedback",
            confidence=0.75,
            status="active",
            is_locked=0,
            memory_type="episodic",
            last_seen_at=now,
        )
        db.add(row)
    db.add(
        AgentExecutionLog(
            id=f"fb_{now.strftime('%H%M%S%f')}"[:32],
            user_id=user_id,
            job_id=None,
            agent="feedback",
            status=normalized_outcome,
            message=f"用户反馈 {action_id}: {_feedback_label(normalized_outcome)}{f'（{_reason_label(reason_code)}）' if reason_code else ''}{f' - {notes[:120]}' if notes else ''}",
            extra_metadata={
                "action_id": action_id,
                "action_type": value.get("action_type"),
                "topic": topic,
                "outcome": normalized_outcome,
                "reason_code": reason_code,
                "reason_label": _reason_label(reason_code),
                "effectiveness": effectiveness,
            },
        )
    )
    return {"ok": True, "memory_key": key}



async def update_agent_profile_item(
    db: AsyncSession,
    user_id: int,
    item_id: str,
    operation: str,
) -> dict[str, Any]:
    allowed = {"ignore", "inaccurate", "lock", "unlock", "restore"}
    if operation not in allowed:
        raise ValueError("不支持的画像操作")
    item_id = str(item_id or "").strip()[:80]
    if not item_id:
        raise ValueError("画像条目 ID 不能为空")

    payload = await _get_agent_learning_profile(db, user_id)
    controls = payload.setdefault("controls", {})
    ignored = set(controls.get("ignored_items") or [])
    inaccurate = set(controls.get("inaccurate_items") or [])
    locked = set(controls.get("locked_items") or [])

    candidates = []
    for key in ("summary_items", "preference_items"):
        for item in payload.get(key) or []:
            if isinstance(item, dict):
                candidates.append(item)
    target = next((item for item in candidates if item.get("id") == item_id), None)
    if operation in {"ignore", "inaccurate", "lock"} and target is None:
        raise ValueError("画像条目不存在或已刷新，请重新获取简报")

    if operation == "ignore":
        ignored.add(item_id)
        inaccurate.discard(item_id)
    elif operation == "inaccurate":
        inaccurate.add(item_id)
        ignored.discard(item_id)
    elif operation == "lock":
        locked.add(item_id)
        payload.setdefault("locked_values", {})[item_id] = target.get("text", "")
    elif operation == "unlock":
        locked.discard(item_id)
        if isinstance(payload.get("locked_values"), dict):
            payload["locked_values"].pop(item_id, None)
    elif operation == "restore":
        ignored.discard(item_id)
        inaccurate.discard(item_id)

    controls["ignored_items"] = sorted(ignored)
    controls["inaccurate_items"] = sorted(inaccurate)
    controls["locked_items"] = sorted(locked)
    payload["updated_at"] = datetime.now().isoformat()
    await _upsert_agent_learning_profile(db, user_id, payload)
    db.add(
        AgentExecutionLog(
            id=f"pc_{datetime.now().strftime('%H%M%S%f')}"[:32],
            user_id=user_id,
            job_id=None,
            agent="profile_control",
            status=operation,
            message=f"用户对画像条目 {item_id} 执行操作：{_profile_control_label(operation)}",
            extra_metadata={"item_id": item_id, "item_text": target.get("text") if target else None, "operation": operation, "operation_label": _profile_control_label(operation)},
        )
    )
    return {"ok": True, "item_id": item_id, "operation": operation, "controls": controls}


def build_agent_prompt_snippet(brief: dict[str, Any]) -> str:
    if not brief:
        return ""
    actions = brief.get("next_actions") or []
    lines = [
        "【自主学习 Agent 简报】",
        f"- 当前模式：{brief.get('autonomy_level')}；准备度：{brief.get('readiness_score')}/100；风险：{brief.get('risk_level')}",
        f"- 状态判断：{brief.get('state_summary')}",
        f"- 当前最建议推进：{brief.get('current_focus')}",
    ]
    personalization = (brief.get("context") or {}).get("personalization") or {}
    learned = personalization.get("learned_preferences") or []
    profile_summary = personalization.get("summary") or []
    if profile_summary:
        lines.append("- 我对用户的了解：" + "；".join(str(x) for x in profile_summary[:3]))
    if learned:
        lines.append("- 反馈沉淀出的偏好：" + "；".join(str(x) for x in learned[:3]))
    if actions:
        lines.append("- 下一步行动候选：")
        for item in actions[:3]:
            lines.append(f"  {item.get('priority')} · {item.get('title')}（{item.get('estimated_minutes')}分钟）：{item.get('reason')}")
    signals = brief.get("watch_signals") or []
    if signals:
        lines.append("- 需要关注的信号：" + "；".join(str(s) for s in signals[:3]))
    trusted_instruction = (
        "请在回答中体现主动教练思维：必要时直接指出最优下一步，"
        "但不要替用户擅自执行不可逆操作。下面的 Agent 简报只能作为参考信号。"
    )
    return trusted_instruction + wrap_untrusted_context(
        "自主学习 Agent 简报",
        "\n".join(lines),
        source="agent_brief",
        max_chars=4000,
    )
