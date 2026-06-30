"""Helpers for building personalized motivation prompts and fallbacks."""
from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import date

from sqlalchemy import case, func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.goal import Goal, Task
from app.models.note import Note
from app.models.pomodoro import Pomodoro
from app.utils.prompt_safety import wrap_untrusted_context

_GENERIC_NOTE_TITLES = {"", "新笔记", "学习摘录", "无标题", "私有笔记"}
_NOTE_SIGNAL_KEYWORDS = (
    "坚持",
    "行动",
    "专注",
    "复习",
    "方法",
    "习惯",
    "输出",
    "复盘",
    "不要",
    "先",
    "理解",
)


@dataclass(slots=True)
class NoteHighlight:
    title: str
    excerpt: str


@dataclass(slots=True)
class MotivationSnapshot:
    user_id: int
    target_date: date
    goals: list[str]
    task_total: int
    task_completed: int
    pomodoro_count: int
    pomodoro_minutes: int
    note_highlights: list[NoteHighlight]


def _compact_text(text: str, limit: int) -> str:
    clean = re.sub(r"\s+", " ", (text or "").strip())
    if len(clean) <= limit:
        return clean
    return clean[: limit - 1].rstrip() + "…"


def _clean_markdown_line(line: str) -> str:
    text = line.strip()
    text = re.sub(r"^#{1,6}\s*", "", text)
    text = re.sub(r"^\s*[-*+]\s*", "", text)
    text = re.sub(r"^\s*\d+[.)]\s*", "", text)
    text = re.sub(r"`([^`]*)`", r"\1", text)
    text = re.sub(r"\[(.*?)\]\((.*?)\)", r"\1", text)
    return re.sub(r"\s+", " ", text).strip(" >\t")


def _extract_note_excerpt(content: str, limit: int = 96) -> str:
    if not content:
        return ""
    text = re.sub(r"```.*?```", " ", content, flags=re.S)
    candidates: list[str] = []
    for raw_line in text.splitlines():
        clean = _clean_markdown_line(raw_line)
        if len(clean) < 10:
            continue
        candidates.append(clean)
        if len(candidates) >= 8:
            break
    if not candidates:
        return ""
    for item in candidates:
        if any(keyword in item for keyword in _NOTE_SIGNAL_KEYWORDS):
            return _compact_text(item, limit)
    return _compact_text(candidates[0], limit)


def _normalize_note_title(title: str) -> str:
    clean = _compact_text(title or "", 40)
    return clean or "未命名笔记"


def _should_reference_title(title: str) -> bool:
    return (title or "").strip() not in _GENERIC_NOTE_TITLES


async def _collect_recent_note_highlights(
    db: AsyncSession,
    user_id: int,
    limit: int = 3,
) -> list[NoteHighlight]:
    result = await db.execute(
        select(Note)
        .where(Note.user_id == user_id)
        .order_by(Note.updated_at.desc(), Note.id.desc())
        .limit(8)
    )
    highlights: list[NoteHighlight] = []
    seen: set[str] = set()
    for note in result.scalars().all():
        excerpt = _extract_note_excerpt(str(getattr(note, "content", "") or ""))
        if not excerpt:
            continue
        normalized = excerpt.lower()
        if normalized in seen:
            continue
        seen.add(normalized)
        highlights.append(
            NoteHighlight(
                title=_normalize_note_title(str(getattr(note, "title", "") or "")),
                excerpt=excerpt,
            )
        )
        if len(highlights) >= limit:
            break
    return highlights


async def collect_motivation_snapshot(
    db: AsyncSession,
    user_id: int,
    target_date: date,
) -> MotivationSnapshot:
    today_str = target_date.isoformat()

    goal_result = await db.execute(
        select(Goal.title)
        .where(Goal.user_id == user_id, Goal.status == "active")
        .order_by(Goal.created_at.desc())
        .limit(4)
    )
    goals = [str(row[0]) for row in goal_result.all() if row and row[0]]

    task_stats_result = await db.execute(
        select(
            func.count(Task.id),
            func.coalesce(func.sum(case((Task.status == "completed", 1), else_=0)), 0),
        )
        .select_from(Task)
        .join(Goal, Task.goal_id == Goal.id)
        .where(Goal.user_id == user_id, Task.planned_date == target_date)
    )
    task_total, task_completed = task_stats_result.one()

    pomodoro_result = await db.execute(
        select(
            func.count(Pomodoro.id),
            func.coalesce(func.sum(Pomodoro.duration), 0),
        )
        .where(Pomodoro.user_id == user_id)
        .where(Pomodoro.completed.is_(True))
        .where(func.date(Pomodoro.started_at) == today_str)
    )
    pomodoro_count, pomodoro_minutes = pomodoro_result.one()

    note_highlights = await _collect_recent_note_highlights(db, user_id)

    return MotivationSnapshot(
        user_id=user_id,
        target_date=target_date,
        goals=goals,
        task_total=int(task_total or 0),
        task_completed=int(task_completed or 0),
        pomodoro_count=int(pomodoro_count or 0),
        pomodoro_minutes=int(pomodoro_minutes or 0),
        note_highlights=note_highlights,
    )


def build_motivation_prompt(snapshot: MotivationSnapshot) -> str:
    goals_text = ", ".join(snapshot.goals) if snapshot.goals else "暂无明确目标"
    prompt = (
        "以下是一位学习者的今日学习情况：\n"
        f"当前学习目标: {goals_text}\n"
        f"今日完成任务: {snapshot.task_completed}/{snapshot.task_total}\n"
        f"今日专注时长: {snapshot.pomodoro_minutes} 分钟\n"
        f"今日番茄钟: {snapshot.pomodoro_count} 个\n\n"
        "请生成一句个性化的激励语录。\n"
        "要求：\n"
        "1. 只输出一句话，不要标题、引号或解释\n"
        "2. 优先结合用户自己写过的笔记观点，可以轻微改写，但不要大段照抄\n"
        "3. 语气要克制、真诚、具体，不要空泛鸡汤\n"
        "4. 不要编造不存在的书名、经历、原句或学习进度\n"
        "5. 最好能把鼓励落到“下一小步行动”上\n"
    )
    if snapshot.note_highlights:
        note_lines = []
        for item in snapshot.note_highlights:
            note_lines.append(f"标题：{item.title}\n摘录：{item.excerpt}")
        prompt += (
            "\n如果下面提供了用户最近笔记摘录，请优先使用其中最贴近当下状态的内容作为鼓励依据。\n"
            + wrap_untrusted_context(
                "用户最近笔记摘录",
                "\n\n".join(note_lines),
                source=f"user_notes:{snapshot.user_id}",
                max_chars=1600,
            )
        )
    return prompt


def build_fallback_motivation_quote(snapshot: MotivationSnapshot) -> str:
    remaining_tasks = max(0, snapshot.task_total - snapshot.task_completed)
    if snapshot.note_highlights:
        first = snapshot.note_highlights[0]
        excerpt = first.excerpt.rstrip("，。；;、 ")
        if _should_reference_title(first.title):
            return f"还记得你在《{first.title}》里写过：{excerpt}。现在先把下一小步做完，状态会回来。"
        return f"你最近写过：{excerpt}。现在不用一下走很远，先完成眼前这一小步。"
    if snapshot.pomodoro_minutes <= 0 and remaining_tasks > 0:
        return "先别等状态完美，先做 25 分钟，把今天重新启动。"
    if remaining_tasks > 0 and snapshot.task_total > 0:
        return f"你今天已经推进了 {snapshot.task_completed}/{snapshot.task_total}，再完成一个最小任务，节奏就会更稳。"
    if snapshot.pomodoro_count > 0:
        return "你已经开始行动了，继续把下一段专注做完，比反复犹豫更有效。"
    if snapshot.goals:
        return f"先朝“{_compact_text(snapshot.goals[0], 18)}”再推进一小步，积累感会比等待动力更可靠。"
    return "先把下一小步做完，动力通常不是开始前就出现，而是行动后才回来。"
