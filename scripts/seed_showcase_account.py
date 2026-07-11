"""Seed a fixed showcase account for local demos.

Usage:
    python scripts/seed_showcase_account.py
    python scripts/seed_showcase_account.py --reset-demo
"""
from __future__ import annotations

import argparse
import asyncio
import json
import os
from datetime import date, datetime, timedelta
from pathlib import Path
import sys
from typing import Any

from sqlalchemy import delete, select
from sqlalchemy.ext.asyncio import AsyncSession

ROOT = Path(__file__).resolve().parents[1]
BACKEND = ROOT / "backend"
if str(BACKEND) not in sys.path:
    sys.path.insert(0, str(BACKEND))
os.chdir(BACKEND)

import app.models  # noqa: F401,E402
from app.auth import hash_password  # noqa: E402
from app.database import async_session_maker, close_db, init_db  # noqa: E402
from app.models.agent import AgentExecutionLog, AgentJob  # noqa: E402
from app.models.anki import AnkiCard  # noqa: E402
from app.models.chat import ChatConversation, ChatMessage, ChatProject, ChatProjectMaterial  # noqa: E402
from app.models.coach import CoachEvent, CoachNudge, CoachPreference, CoachSkillStats, CoachWorkflow  # noqa: E402
from app.models.daily_plan import DailyPlan  # noqa: E402
from app.models.goal import Goal, Task  # noqa: E402
from app.models.learning_event import LearningEvent  # noqa: E402
from app.models.material import Chapter, Material  # noqa: E402
from app.models.memory import ConversationSummary, UserMemory  # noqa: E402
from app.models.motivation import MotivationQuote, MotivationSettings  # noqa: E402
from app.models.note import Note, NoteLink  # noqa: E402
from app.models.pomodoro import Pomodoro  # noqa: E402
from app.models.progress import MaterialProfile, OutputEvaluation  # noqa: E402
from app.models.question import Question, QuizRecord, ReviewSchedule, WrongQuestion  # noqa: E402
from app.models.session import Conversation, StudySession  # noqa: E402
from app.models.user import User  # noqa: E402
from app.models.user_profile import UserProfile  # noqa: E402
from app.routers.system import seed_demo_workspace  # noqa: E402
from app.services.agent_long_memory_service import rebuild_core_profile, upsert_agent_memory  # noqa: E402
from app.services.agent_memory_learning_service import run_agent_memory_learning  # noqa: E402
from app.services.coach_action_service import create_coach_nudge  # noqa: E402
from app.services.coach_context_retriever import retrieve_coach_context  # noqa: E402
from app.services.coach_event_service import record_coach_event  # noqa: E402
from app.services.coach_learning_service import record_skill_feedback, record_skill_shown  # noqa: E402
from app.services.coach_policy_engine import evaluate_coach_policy  # noqa: E402
from app.services.coach_preference_service import update_coach_preferences  # noqa: E402
from app.services.coach_skills.base import CoachSkillContext  # noqa: E402
from app.services.coach_skills.registry import coach_skill_registry  # noqa: E402
from app.services.learning_event_service import record_learning_event  # noqa: E402
from app.services.learning_snapshot_service import build_learning_snapshot  # noqa: E402


SHOWCASE_MARKER_KEY = "showcase_account_seeded_v1"


def _parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Seed the local Mnemox showcase account.")
    parser.add_argument("--username", default="test", help="Showcase username.")
    parser.add_argument("--password", default="123456", help="Showcase password.")
    parser.add_argument("--email", default="test@example.com", help="Showcase email.")
    parser.add_argument(
        "--reset-demo",
        action="store_true",
        help="Delete existing workspace data for this user before reseeding.",
    )
    return parser.parse_args()


async def _ensure_user(db: AsyncSession, username: str, password: str, email: str) -> User:
    result = await db.execute(select(User).where(User.username == username))
    user = result.scalar_one_or_none()
    password_hash = hash_password(password)
    if user is None:
        user = User(
            username=username,
            email=email,
            hashed_password=password_hash,
            is_active=True,
        )
        db.add(user)
        await db.flush()
        await db.refresh(user)
        return user

    user.hashed_password = password_hash
    user.is_active = True
    if user.email != email:
        existing = await db.execute(select(User.id).where(User.email == email, User.id != user.id))
        if existing.scalar_one_or_none() is None:
            user.email = email
    await db.flush()
    await db.refresh(user)
    return user


async def _scalar_ids(db: AsyncSession, query: Any) -> list[int]:
    result = await db.execute(query)
    return [int(item) for item in result.scalars().all()]


async def _reset_user_workspace(db: AsyncSession, user_id: int) -> None:
    material_ids = await _scalar_ids(db, select(Material.id).where(Material.user_id == user_id))
    goal_ids = await _scalar_ids(db, select(Goal.id).where(Goal.user_id == user_id))
    task_ids = await _scalar_ids(db, select(Task.id).where(Task.goal_id.in_(goal_ids))) if goal_ids else []
    note_ids = await _scalar_ids(db, select(Note.id).where(Note.user_id == user_id))
    question_ids = await _scalar_ids(db, select(Question.id).where(Question.user_id == user_id))
    project_ids = await _scalar_ids(db, select(ChatProject.id).where(ChatProject.user_id == user_id))
    conversation_ids = await _scalar_ids(db, select(ChatConversation.id).where(ChatConversation.user_id == user_id))
    session_ids = await _scalar_ids(db, select(StudySession.id).where(StudySession.user_id == user_id))

    for model in (CoachWorkflow, CoachNudge, CoachEvent, CoachPreference, CoachSkillStats):
        await db.execute(delete(model).where(model.user_id == user_id))
    for model in (AgentExecutionLog, AgentJob, LearningEvent, ConversationSummary, UserMemory):
        await db.execute(delete(model).where(model.user_id == user_id))
    for model in (AnkiCard, MotivationSettings, MotivationQuote, DailyPlan, Pomodoro, ReviewSchedule, WrongQuestion):
        await db.execute(delete(model).where(model.user_id == user_id))
    if question_ids:
        await db.execute(delete(QuizRecord).where(QuizRecord.question_id.in_(question_ids)))
    if session_ids:
        await db.execute(delete(Conversation).where(Conversation.session_id.in_(session_ids)))
        await db.execute(delete(QuizRecord).where(QuizRecord.session_id.in_(session_ids)))
    if note_ids:
        await db.execute(delete(NoteLink).where(NoteLink.note_id.in_(note_ids)))
    if conversation_ids:
        await db.execute(delete(ChatMessage).where(ChatMessage.conversation_id.in_(conversation_ids)))
    if project_ids:
        await db.execute(delete(ChatProjectMaterial).where(ChatProjectMaterial.project_id.in_(project_ids)))
    if task_ids or material_ids:
        filters = []
        if task_ids:
            filters.append(OutputEvaluation.task_id.in_(task_ids))
        if material_ids:
            filters.append(OutputEvaluation.material_id.in_(material_ids))
        for condition in filters:
            await db.execute(delete(OutputEvaluation).where(condition))
    if goal_ids:
        await db.execute(delete(Task).where(Task.goal_id.in_(goal_ids)))
    if material_ids:
        await db.execute(delete(MaterialProfile).where(MaterialProfile.material_id.in_(material_ids)))
        await db.execute(delete(Chapter).where(Chapter.material_id.in_(material_ids)))

    for model in (Question, Note, ChatConversation, ChatProject, StudySession, Goal, Material, UserProfile):
        if hasattr(model, "user_id"):
            await db.execute(delete(model).where(model.user_id == user_id))


async def _one_or_none(db: AsyncSession, query: Any) -> Any | None:
    result = await db.execute(query)
    return result.scalars().first()


async def _ensure_showcase_goal_depth(db: AsyncSession, user_id: int) -> dict[str, Any]:
    today = date.today()
    goal = await _one_or_none(
        db,
        select(Goal)
        .where(Goal.user_id == user_id, Goal.status == "active")
        .order_by(Goal.id.desc()),
    )
    material = await _one_or_none(
        db,
        select(Material)
        .where(Material.user_id == user_id)
        .order_by(Material.id.desc()),
    )
    if goal is None:
        goal = Goal(
            user_id=user_id,
            material_id=material.id if material else None,
            title="面试演示：用 Mnemox 跑通学习闭环",
            description="展示 Agent cockpit、双层记忆、Coach nudge、笔记证据和番茄钟闭环。",
            target_level="能向面试官解释清楚产品和技术边界",
            deadline=today + timedelta(days=3),
            status="active",
            plan_total_days=3,
            plan_study_days_per_week=3,
            plan_start_date=today,
        )
        db.add(goal)
        await db.flush()
        await db.refresh(goal)

    existing_overdue = await _one_or_none(
        db,
        select(Task).where(Task.goal_id == goal.id, Task.title == "补一段过期任务：整理 Agent 融合讲法"),
    )
    if existing_overdue is None:
        db.add(
            Task(
                goal_id=goal.id,
                title="补一段过期任务：整理 Agent 融合讲法",
                description="用于在 Agent cockpit 中展示过期任务风险和最小补救建议。",
                task_type="summarize",
                planned_date=today - timedelta(days=1),
                status="pending",
            )
        )

    existing_today = await _one_or_none(
        db,
        select(Task).where(Task.goal_id == goal.id, Task.title == "演示 Agent：自然语言生成目标和任务草案"),
    )
    if existing_today is None:
        db.add(
            Task(
                goal_id=goal.id,
                title="演示 Agent：自然语言生成目标和任务草案",
                description="在聊天框输入自然语言，让 Agent 生成草案，确认后写入。",
                task_type="practice",
                planned_date=today,
                status="pending",
            )
        )

    await db.flush()
    tasks = (
        await db.execute(select(Task).where(Task.goal_id == goal.id).order_by(Task.planned_date, Task.id))
    ).scalars().all()
    return {"goal": goal, "material": material, "tasks": list(tasks)}


async def _ensure_showcase_note(db: AsyncSession, user_id: int, material_id: int | None, goal_id: int) -> Note:
    result = await db.execute(select(Note).where(Note.user_id == user_id, Note.title == "面试演示脚本：Agent 融合闭环"))
    note = result.scalar_one_or_none()
    if note is None:
        note = Note(
            user_id=user_id,
            material_id=material_id,
            title="面试演示脚本：Agent 融合闭环",
            note_type="summary",
            tags=json.dumps(["面试", "Agent", "Demo"], ensure_ascii=False),
            content=(
                "## 30 秒讲法\n\n"
                "Mnemox 的 Agent 不是单独聊天框，而是学习操作系统的中枢："
                "读取目标、任务、笔记、资料、错题、复习和番茄钟，再输出可解释、可确认的下一步行动。\n\n"
                "## 演示顺序\n\n"
                "1. 打开 Agent cockpit 看 Current Goal、Today Focus、Evidence。\n"
                "2. 在聊天里输入自然语言计划，展示草案确认。\n"
                "3. 运行长期记忆学习，确认/锁定/忽略候选记忆。\n"
                "4. 输入“今天有点学不进去”，展示 Coach nudge。\n"
            ),
        )
        db.add(note)
        await db.flush()
        db.add(NoteLink(note_id=note.id, link_type="goal", link_id=goal_id))
        await db.flush()
        await db.refresh(note)
    return note


async def _ensure_agent_memory_showcase(db: AsyncSession, user_id: int, goal: Goal, note: Note, tasks: list[Task]) -> None:
    now = datetime.now()
    await upsert_agent_memory(
        db,
        user_id,
        memory_key="showcase_prefer_minimum_next_step",
        memory_value="用户准备面试演示时偏好先展示一个最小、可验证的下一步，而不是铺开复杂配置。",
        category="style",
        confidence=0.88,
        review_status="confirmed",
        status="active",
        source_type="showcase_seed",
        source_id="prefer_minimum_next_step",
        evidence=[{"kind": "demo", "source": "seed_showcase_account"}],
        memory_type="semantic",
        lock=True,
    )
    await upsert_agent_memory(
        db,
        user_id,
        memory_key="showcase_staged_agent_pitch",
        memory_value="用户可能需要把 Agent 融合讲成“感知 -> 草案 -> 确认 -> 写入 -> 学习”的闭环。",
        category="agent_feedback",
        confidence=0.66,
        review_status="staged",
        status="staged",
        source_type="showcase_seed",
        source_id="staged_agent_pitch",
        evidence=[{"kind": "demo", "note_id": int(note.id)}],
        memory_type="semantic",
    )
    await upsert_agent_memory(
        db,
        user_id,
        memory_key="showcase_staged_weakness_boundary",
        memory_value="用户在演示中可能需要强调：Agent 写入必须先生成草案并由用户确认，避免过度自主。",
        category="weakness",
        confidence=0.62,
        review_status="staged",
        status="staged",
        source_type="showcase_seed",
        source_id="staged_autonomy_boundary",
        evidence=[{"kind": "demo", "goal_id": int(goal.id)}],
        memory_type="semantic",
    )

    await record_learning_event(
        db,
        user_id,
        "goal.created",
        source="showcase_seed",
        payload={"title": goal.title, "demo": True},
        goal_id=int(goal.id),
        dedupe_key=f"showcase:goal:{goal.id}",
        occurred_at=now - timedelta(hours=4),
    )
    for task in tasks[:3]:
        await record_learning_event(
            db,
            user_id,
            "task.created",
            source="showcase_seed",
            payload={"title": task.title, "planned_date": str(task.planned_date), "demo": True},
            goal_id=int(goal.id),
            task_id=int(task.id),
            dedupe_key=f"showcase:task:{task.id}",
            occurred_at=now - timedelta(hours=3),
        )
    await record_learning_event(
        db,
        user_id,
        "note.created",
        source="showcase_seed",
        payload={"title": note.title, "demo": True},
        goal_id=int(goal.id),
        note_id=int(note.id),
        dedupe_key=f"showcase:note:{note.id}",
        occurred_at=now - timedelta(hours=2),
    )
    await record_learning_event(
        db,
        user_id,
        "agent.action_feedback",
        source="showcase_seed",
        payload={
            "action_id": "showcase_goal_context",
            "outcome": "helpful",
            "reason_code": None,
            "topic": "Agent cockpit",
            "demo": True,
        },
        goal_id=int(goal.id),
        dedupe_key="showcase:agent-feedback:goal-context",
        occurred_at=now - timedelta(hours=1),
    )
    await run_agent_memory_learning(db, user_id)
    await rebuild_core_profile(db, user_id)


async def _ensure_coach_showcase(db: AsyncSession, user_id: int) -> None:
    await update_coach_preferences(
        db,
        user_id,
        {
            "enabled": True,
            "proactive_enabled": True,
            "desktop_notifications_enabled": False,
            "allowed_channels": ["chat_inline", "in_app_nudge", "agent_panel"],
            "max_nudges_per_day": 5,
            "min_minutes_between_nudges": 15,
        },
    )

    existing = await _one_or_none(
        db,
        select(CoachNudge)
        .where(
            CoachNudge.user_id == user_id,
            CoachNudge.skill_id == "low_motivation",
            CoachNudge.status.in_(("pending", "shown", "accepted")),
        )
        .order_by(CoachNudge.created_at.desc()),
    )
    if existing is not None:
        return

    event = await record_coach_event(
        db,
        user_id,
        "chat.low_motivation_detected",
        "chat",
        {"text": "今天有点学不进去，先给我一个最小动作", "demo": True},
        "info",
        dedupe_key=f"showcase:low-motivation:{date.today().isoformat()}",
    )
    event["channel"] = "chat_inline"
    snapshot = await build_learning_snapshot(db, user_id, include_recent_notes=True, include_memories=True)
    preferences = await update_coach_preferences(db, user_id, {})
    policy = evaluate_coach_policy(event, snapshot, preferences, [], [])
    skill_id = str(policy.get("skill_id") or "low_motivation")
    skill = coach_skill_registry.get(skill_id)
    if not skill:
        return
    snapshot["coach_context"] = await retrieve_coach_context(db, user_id, event, snapshot)
    result = await skill.generate(
        CoachSkillContext(
            user_id=user_id,
            event=event,
            snapshot=snapshot,
            policy=policy,
            recent_feedback=[],
        )
    )
    nudge_dict = await create_coach_nudge(
        db,
        user_id,
        event_id=event.get("id"),
        skill_id=skill_id,
        policy=policy,
        result=result,
    )
    nudge = await _one_or_none(db, select(CoachNudge).where(CoachNudge.id == nudge_dict["id"]))
    if nudge is not None:
        await record_skill_shown(db, user_id, nudge)
        await record_skill_feedback(db, user_id, nudge, "helpful")
        nudge.status = "shown"
        nudge.updated_at = datetime.now()


async def _mark_showcase_seeded(db: AsyncSession, user_id: int) -> None:
    await upsert_agent_memory(
        db,
        user_id,
        memory_key=SHOWCASE_MARKER_KEY,
        memory_value=datetime.now().isoformat(),
        category="system",
        confidence=1.0,
        review_status="confirmed",
        status="ignored",
        source_type="showcase_seed",
        source_id=SHOWCASE_MARKER_KEY,
        evidence=[{"kind": "script", "path": "scripts/seed_showcase_account.py"}],
        memory_type="semantic",
        lock=True,
        respect_lock=False,
    )


async def _counts(db: AsyncSession, user_id: int) -> dict[str, int]:
    items: list[tuple[str, Any]] = [
        ("materials", Material),
        ("goals", Goal),
        ("tasks", Task),
        ("daily_plans", DailyPlan),
        ("notes", Note),
        ("pomodoros", Pomodoro),
        ("wrong_questions", WrongQuestion),
        ("review_items", ReviewSchedule),
        ("anki_cards", AnkiCard),
        ("memories", UserMemory),
        ("learning_events", LearningEvent),
        ("coach_nudges", CoachNudge),
        ("coach_stats", CoachSkillStats),
    ]
    output: dict[str, int] = {}
    for label, model in items:
        if model is Task:
            goal_ids = await _scalar_ids(db, select(Goal.id).where(Goal.user_id == user_id))
            output[label] = 0 if not goal_ids else len(await _scalar_ids(db, select(Task.id).where(Task.goal_id.in_(goal_ids))))
            continue
        result = await db.execute(select(model).where(model.user_id == user_id))
        output[label] = len(result.scalars().all())
    return output


async def _run() -> int:
    args = _parse_args()
    await init_db()
    async with async_session_maker() as db:
        user = await _ensure_user(db, args.username, args.password, args.email)
        await db.commit()

        if args.reset_demo:
            await _reset_user_workspace(db, int(user.id))
            await db.commit()

        seed_result = await seed_demo_workspace(db=db, current_user=user)
        context = await _ensure_showcase_goal_depth(db, int(user.id))
        note = await _ensure_showcase_note(
            db,
            int(user.id),
            int(context["material"].id) if context.get("material") else None,
            int(context["goal"].id),
        )
        await _ensure_agent_memory_showcase(db, int(user.id), context["goal"], note, context["tasks"])
        await _ensure_coach_showcase(db, int(user.id))
        await _mark_showcase_seeded(db, int(user.id))
        await db.commit()
        counts = await _counts(db, int(user.id))

    print("Showcase account ready.")
    print(f"Login: {args.username} / {args.password}")
    print(f"Demo seed: {seed_result.message}")
    print(json.dumps(counts, ensure_ascii=False, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(_run()))
    finally:
        try:
            asyncio.run(close_db())
        except Exception:
            pass
