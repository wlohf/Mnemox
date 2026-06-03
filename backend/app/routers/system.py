"""系统相关路由：版本与更新检查"""
from __future__ import annotations

from datetime import date, datetime, timedelta, timezone
from typing import Any, Optional
import hashlib
import json

import httpx
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.config import settings
from app.database import get_db
from app.models.anki import AnkiCard
from app.models.chat import ChatConversation, ChatMessage, ChatProject, ChatProjectMaterial
from app.models.daily_plan import DailyPlan
from app.models.goal import Goal, Task
from app.models.learning_event import LearningEvent
from app.models.material import Chapter, Material
from app.models.memory import UserMemory
from app.models.motivation import MotivationQuote
from app.models.note import Note
from app.models.pomodoro import Pomodoro
from app.models.question import Question, ReviewSchedule, WrongQuestion
from app.models.user import User

router = APIRouter()


class VersionInfoOut(BaseModel):
    app_name: str
    current_version: str
    checked_at: str


class UpdateInfoOut(BaseModel):
    has_update: bool
    current_version: str
    latest_version: Optional[str] = None
    release_notes: Optional[str] = None
    release_page: Optional[str] = None
    download_url: Optional[str] = None
    published_at: Optional[str] = None
    checked_at: str


class OnboardingStatusOut(BaseModel):
    has_content: bool
    demo_seeded: bool
    auto_show_seen: bool
    counts: dict[str, int]
    suggested_next_steps: list[str]
    stage: str
    stage_label: str
    completed_steps: list[str]


class DemoSeedOut(BaseModel):
    ok: bool
    already_seeded: bool
    message: str
    created: dict[str, int]


_DEMO_MARKER_KEY = "demo_mnemox_seeded"
_ONBOARDING_AUTO_SHOWN_KEY = "onboarding_auto_shown"
_DEMO_MATERIAL_TITLE = "Demo：主动学习与记忆方法速览"


async def _count_for_user(db: AsyncSession, model: Any, user_id: int) -> int:
    result = await db.execute(select(func.count()).select_from(model).where(model.user_id == user_id))
    return int(result.scalar() or 0)


async def _get_onboarding_counts(db: AsyncSession, user_id: int) -> dict[str, int]:
    return {
        "materials": await _count_for_user(db, Material, user_id),
        "goals": await _count_for_user(db, Goal, user_id),
        "notes": await _count_for_user(db, Note, user_id),
        "pomodoros": await _count_for_user(db, Pomodoro, user_id),
        "wrong_questions": await _count_for_user(db, WrongQuestion, user_id),
        "anki_cards": await _count_for_user(db, AnkiCard, user_id),
        "memories": await _count_for_user(db, UserMemory, user_id),
    }


async def _is_demo_seeded(db: AsyncSession, user_id: int) -> bool:
    result = await db.execute(
        select(UserMemory.id).where(UserMemory.user_id == user_id, UserMemory.memory_key == _DEMO_MARKER_KEY)
    )
    if result.scalar_one_or_none() is not None:
        return True
    material_result = await db.execute(
        select(Material.id).where(Material.user_id == user_id, Material.title == _DEMO_MATERIAL_TITLE)
    )
    return material_result.scalar_one_or_none() is not None


async def _has_system_memory(db: AsyncSession, user_id: int, key: str) -> bool:
    result = await db.execute(
        select(UserMemory.id).where(UserMemory.user_id == user_id, UserMemory.memory_key == key)
    )
    return result.scalar_one_or_none() is not None


async def _mark_system_memory(db: AsyncSession, user_id: int, key: str, value: str | None = None) -> None:
    if await _has_system_memory(db, user_id, key):
        return
    now = datetime.now(timezone.utc)
    db.add(
        UserMemory(
            user_id=user_id,
            memory_key=key,
            memory_value=value or now.isoformat(),
            category="system",
            confidence=1.0,
            status="ignored",
            memory_type="semantic",
            last_seen_at=now,
            is_locked=1,
        )
    )


def _build_onboarding_stage(counts: dict[str, int]) -> tuple[str, str, list[str], list[str]]:
    completed_steps: list[str] = []
    if counts.get("materials", 0) > 0:
        completed_steps.append("已有学习资料")
    if counts.get("goals", 0) > 0:
        completed_steps.append("已有目标或任务")
    if counts.get("pomodoros", 0) > 0:
        completed_steps.append("完成过专注记录")
    if counts.get("wrong_questions", 0) > 0 or counts.get("anki_cards", 0) > 0:
        completed_steps.append("已有复习材料")
    if counts.get("notes", 0) > 0:
        completed_steps.append("已有笔记或复盘")

    if counts.get("materials", 0) == 0:
        return (
            "import_material",
            "第 1 步：先放入一份学习资料",
            completed_steps,
            [
                "导入 Demo 数据，先体验完整学习闭环。",
                "或上传一份自己的资料，让 AI 生成目标与任务。",
                "不要先配置系统，先给自己一个真实学习对象。",
            ],
        )
    if counts.get("goals", 0) == 0:
        return (
            "create_plan",
            "第 2 步：把资料变成今日任务",
            completed_steps,
            [
                "在资料列表点“学习”，生成目标和任务。",
                "进入今日概览，只执行系统给出的唯一任务。",
                "任务太大时，把它拆成 10-25 分钟可以完成的小块。",
            ],
        )
    if counts.get("pomodoros", 0) == 0:
        return (
            "start_focus",
            "第 3 步：先完成一次专注",
            completed_steps,
            [
                "打开今日概览，按唯一任务开始。",
                "先做一个 10-25 分钟番茄钟，不要继续规划。",
                "中断时如实记录原因，系统会用它调整建议。",
            ],
        )
    if counts.get("wrong_questions", 0) == 0 and counts.get("anki_cards", 0) == 0:
        return (
            "add_recall",
            "第 4 步：留下可复习的东西",
            completed_steps,
            [
                "把讲不顺的知识点变成错题或 Anki 卡片。",
                "复习时先尝试回忆，再看答案。",
                "优先处理到期复习，不要只继续学新内容。",
            ],
        )
    if counts.get("notes", 0) == 0:
        return (
            "write_reflection",
            "第 5 步：写一次费曼复盘",
            completed_steps,
            [
                "晚上打开学习计划，用自己的话写 3 句话复盘。",
                "把讲不顺的地方交给明镜追问。",
                "明天只补一个最小缺口。",
            ],
        )
    return (
        "loop_ready",
        "学习闭环已跑通",
        completed_steps,
        [
            "进入今日概览查看唯一任务。",
            "按复习、任务、专注、复盘的顺序推进。",
            "高级功能需要时再打开，不要让配置代替学习。",
        ],
    )


async def _upsert_today_demo_plan(db: AsyncSession, user_id: int, task_ids: list[int]) -> int:
    today = date.today().isoformat()
    content = f"""# {today} 学习计划

> Demo 引导：今天不需要切换什么“模式”，直接按学习流程走，Mnemox 会在对话、计划和复盘中自然使用苏格拉底追问与费曼复述。

## 今日最小闭环
- [ ] 📚 阅读 Demo 资料：主动学习与记忆方法速览
- [ ] ⏱ 开一个 25 分钟番茄钟，完成一个最小任务
- [ ] 🧠 清理 1 条到期复习或错题

## 晚间费曼复盘
请用自己的话写 3-5 句话回答：
1. 我今天真正理解了什么？
2. 如果要讲给一个完全没学过的人，我会怎么解释？
3. 哪一步还讲不顺？明天要补哪一个最小缺口？

## 明日衔接
- [ ] 把“讲不顺”的地方交给「明镜追问」，让 AI 以小白听众视角继续追问。
"""
    result = await db.execute(select(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.date == today))
    row = result.scalar_one_or_none()
    if row is None:
        row = DailyPlan(user_id=user_id, date=today, content=content, task_ids=json.dumps(task_ids, ensure_ascii=False))
        db.add(row)
        return 1
    if "Demo 引导" not in (row.content or ""):
        row.content = f"{row.content.rstrip()}\n\n---\n\n{content}" if row.content else content
        row.task_ids = json.dumps(task_ids, ensure_ascii=False)
        return 1
    return 0



def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize_version(version: str) -> list[int]:
    if not version:
        return [0, 0, 0]
    v = version.strip().lower()
    if v.startswith("v"):
        v = v[1:]
    parts = []
    for seg in v.split("."):
        digits = "".join(ch for ch in seg if ch.isdigit())
        parts.append(int(digits) if digits else 0)
    while len(parts) < 3:
        parts.append(0)
    return parts[:3]


def _is_newer(latest: str, current: str) -> bool:
    return _normalize_version(latest) > _normalize_version(current)


def _pick_download_url(platform_links: object) -> Optional[str]:
    if isinstance(platform_links, dict):
        for key in ("windows", "win", "mac", "darwin", "linux", "universal"):
            value = platform_links.get(key)
            if isinstance(value, str) and value.strip():
                return value.strip()
    if isinstance(platform_links, str) and platform_links.strip():
        return platform_links.strip()
    return None


def _parse_manifest(payload: Any) -> dict:
    if not isinstance(payload, dict):
        raise HTTPException(status_code=502, detail="更新源响应格式错误，应为 JSON 对象")
    return payload



@router.get("/onboarding-status", response_model=OnboardingStatusOut)
async def get_onboarding_status(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """返回首次引导所需的用户工作区状态。"""
    user_id = int(current_user.id)
    counts = await _get_onboarding_counts(db, user_id)
    demo_seeded = await _is_demo_seeded(db, user_id)
    auto_show_seen = await _has_system_memory(db, user_id, _ONBOARDING_AUTO_SHOWN_KEY)
    has_content = any(counts[key] > 0 for key in ("materials", "goals", "notes", "pomodoros", "wrong_questions", "anki_cards"))
    stage, stage_label, completed_steps, steps = _build_onboarding_stage(counts)

    return OnboardingStatusOut(
        has_content=has_content,
        demo_seeded=demo_seeded,
        auto_show_seen=auto_show_seen,
        counts=counts,
        suggested_next_steps=steps,
        stage=stage,
        stage_label=stage_label,
        completed_steps=completed_steps,
    )


@router.post("/onboarding-dismissed")
async def dismiss_onboarding(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """记录当前安装/用户已看过自动新手引导，避免每次启动都弹出。"""
    await _mark_system_memory(db, int(current_user.id), _ONBOARDING_AUTO_SHOWN_KEY)
    await db.commit()
    return {"ok": True}


@router.post("/demo-seed", response_model=DemoSeedOut)
async def seed_demo_workspace(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """为当前用户创建一组可体验完整学习闭环的 Demo 数据，幂等执行。"""
    user_id = int(current_user.id)
    if await _is_demo_seeded(db, user_id):
        counts = await _get_onboarding_counts(db, user_id)
        return DemoSeedOut(ok=True, already_seeded=True, message="Demo 数据已经存在", created=counts)

    now = datetime.now()
    today = date.today()
    created = {
        "materials": 0,
        "chapters": 0,
        "projects": 0,
        "conversations": 0,
        "goals": 0,
        "tasks": 0,
        "daily_plans": 0,
        "pomodoros": 0,
        "questions": 0,
        "wrong_questions": 0,
        "review_tasks": 0,
        "notes": 0,
        "anki_cards": 0,
        "memories": 0,
        "learning_events": 0,
        "quotes": 0,
    }

    demo_content = """# 主动学习与记忆方法速览

## 1. 为什么只看懂不等于学会
看懂是识别，学会是能在没有提示时重新组织和输出。真正掌握一个概念，至少要能做到：用自己的话解释、举出例子、指出易错点，并能把它和旧知识连接起来。

## 2. 费曼复盘：把知识讲给初学者
每天学习结束后，不要只写“今天学了 X”。更有效的方式是：假设你要讲给一个完全没学过的人，用 3-5 句话复述。讲不顺的地方，就是明天的最小补缺口。

## 3. 苏格拉底式追问：让问题推动理解
当你问 AI“这是什么”时，Mnemox 不应该只给结论，还应该适度追问：你目前怎么理解？这个概念和上一个概念有什么关系？如果换一个例子还成立吗？这些追问会帮助你暴露模糊点。

## 4. 间隔复习与主动回忆
复习不是重读，而是先尝试回忆，再看答案校准。错题、Anki 卡片和复习任务都服务于同一个目标：在遗忘发生前，用最小成本把知识重新激活。
"""
    content_hash = hashlib.sha256(demo_content.encode("utf-8")).hexdigest()
    material = Material(
        user_id=user_id,
        title=_DEMO_MATERIAL_TITLE,
        file_type="md",
        content=demo_content,
        content_status="extracted",
        content_hash=content_hash,
    )
    db.add(material)
    await db.flush()
    created["materials"] += 1

    chapters = [
        Chapter(material_id=material.id, title="看懂与学会的区别", content="识别不等于可输出，输出可以暴露理解漏洞。", order_index=1, mastery_level=65),
        Chapter(material_id=material.id, title="费曼复盘", content="用自己的话讲给初学者，讲不顺就是补缺口。", order_index=2, mastery_level=45),
        Chapter(material_id=material.id, title="苏格拉底式追问", content="通过问题推动理解，而不是让答案替代思考。", order_index=3, mastery_level=50),
    ]
    db.add_all(chapters)
    await db.flush()
    created["chapters"] += len(chapters)

    project = ChatProject(
        user_id=user_id,
        name="Demo 学习项目",
        description="体验资料问答、任务计划、复盘和记忆卡片的完整闭环。",
        default_instructions="围绕主动学习方法给出简洁解释，并适度用追问帮助用户形成自己的理解。",
        color="#6366f1",
    )
    db.add(project)
    await db.flush()
    db.add(ChatProjectMaterial(project_id=project.id, material_id=material.id))
    created["projects"] += 1

    conversation = ChatConversation(user_id=user_id, project_id=project.id, title="Demo：怎样开始主动学习？", is_pinned=True)
    db.add(conversation)
    await db.flush()
    db.add_all([
        ChatMessage(conversation_id=conversation.id, role="user", content="我刚开始用 Mnemox，应该怎么体验主动学习闭环？"),
        ChatMessage(
            conversation_id=conversation.id,
            role="assistant",
            content="可以先读左侧 Demo 资料，再生成今日计划。晚上复盘时，请试着用自己的话解释“看懂”和“学会”的区别；如果卡住，我会用问题帮你拆开。",
        ),
    ])
    created["conversations"] += 1

    goal = Goal(
        user_id=user_id,
        material_id=material.id,
        title="7 天建立主动学习闭环",
        description="用 Demo 资料体验：资料理解 → 任务执行 → 番茄钟 → 费曼复盘 → 间隔复习。",
        target_level="能用自己的话解释并稳定执行",
        deadline=today + timedelta(days=7),
        status="active",
        plan_total_days=7,
        plan_study_days_per_week=5,
        plan_start_date=today,
    )
    db.add(goal)
    await db.flush()
    created["goals"] += 1

    tasks = [
        Task(goal_id=goal.id, chapter_id=chapters[0].id, title="阅读 Demo 资料并划出 3 个关键词", description="先建立整体概念。", task_type="learn", planned_date=today, status="completed", completed_at=now - timedelta(hours=2)),
        Task(goal_id=goal.id, chapter_id=chapters[1].id, title="用费曼法复述：看懂和学会有什么区别", description="写 3-5 句话，不追求完美，重点是暴露讲不顺的地方。", task_type="summarize", planned_date=today, status="pending"),
        Task(goal_id=goal.id, chapter_id=chapters[2].id, title="向 AI 提一个关联性问题，让它追问你", description="例如：费曼复盘和错题复习有什么关系？", task_type="practice", planned_date=today + timedelta(days=1), status="pending"),
        Task(goal_id=goal.id, chapter_id=chapters[1].id, title="把讲不顺的点做成 Anki 卡片", description="用主动回忆巩固今天的薄弱点。", task_type="review", planned_date=today + timedelta(days=2), status="pending"),
    ]
    db.add_all(tasks)
    await db.flush()
    created["tasks"] += len(tasks)
    created["daily_plans"] += await _upsert_today_demo_plan(db, user_id, [int(t.id) for t in tasks])

    for idx, minutes in enumerate([25, 25, 18, 25]):
        started = now - timedelta(days=3 - idx, hours=idx + 1)
        db.add(Pomodoro(
            user_id=user_id,
            task_id=tasks[min(idx, len(tasks) - 1)].id,
            chapter_id=chapters[min(idx, len(chapters) - 1)].id,
            task_name=tasks[min(idx, len(tasks) - 1)].title,
            duration=minutes,
            completed=idx != 2,
            stop_reason=None if idx != 2 else "distracted",
            started_at=started,
            ended_at=started + timedelta(minutes=minutes),
            note="Demo 专注记录",
        ))
    created["pomodoros"] += 4

    question = Question(
        user_id=user_id,
        chapter_id=chapters[1].id,
        question_type="short_answer",
        content="为什么费曼复盘强调‘用自己的话讲给初学者’？",
        answer="因为这能检验你是否真的重组了知识，而不是只是在识别熟悉文本。讲不顺的地方会暴露理解缺口。",
        explanation="主动输出会迫使大脑重建概念结构，是发现薄弱点的高效方式。",
        difficulty=2,
    )
    db.add(question)
    await db.flush()
    created["questions"] += 1

    wrong = WrongQuestion(
        user_id=user_id,
        question_id=question.id,
        first_wrong_at=now - timedelta(days=1),
        last_wrong_at=now - timedelta(days=1),
        wrong_count=1,
        mastery_status="partial",
        next_review_at=now - timedelta(minutes=10),
        review_count=0,
        knowledge_point="费曼复盘",
        recall_difficulty="hard",
        mastery_score=42,
    )
    db.add(wrong)
    await db.flush()
    created["wrong_questions"] += 1

    db.add_all([
        ReviewSchedule(user_id=user_id, item_type="question", item_id=wrong.id, scheduled_date=now - timedelta(minutes=5), interval_days=1, ease_factor=250, repetitions=0, status="pending"),
        ReviewSchedule(user_id=user_id, item_type="chapter", item_id=chapters[2].id, scheduled_date=now + timedelta(days=1), interval_days=1, ease_factor=250, repetitions=0, status="pending"),
    ])
    created["review_tasks"] += 2

    db.add(Note(
        user_id=user_id,
        material_id=material.id,
        chapter_id=chapters[1].id,
        title="Demo 笔记：费曼复盘模板",
        note_type="summary",
        tags=json.dumps(["Demo", "费曼复盘", "主动学习"], ensure_ascii=False),
        content="""## 费曼复盘模板

- 今天我真正理解的是：
- 如果讲给初学者，我会这样说：
- 我讲不顺的地方是：
- 明天最小补缺口：

> 不需要切换模式；在每日计划里直接写，AI 会根据你的复述继续追问。""",
    ))
    created["notes"] += 1

    db.add_all([
        AnkiCard(user_id=user_id, front="看懂和学会的核心区别是什么？", back="看懂是识别熟悉信息；学会是能脱离提示重新组织、解释、应用。", source="ai", tags="Demo,主动学习", due_at=now),
        AnkiCard(user_id=user_id, front="费曼复盘中‘讲不顺’代表什么？", back="代表理解结构中仍有缺口，可以转成明天的最小补缺任务。", source="ai", tags="Demo,费曼复盘", due_at=now + timedelta(days=1)),
    ])
    created["anki_cards"] += 2

    memories = [
        UserMemory(user_id=user_id, memory_key="demo_learning_goal", memory_value="正在体验 Mnemox 的主动学习闭环：资料、计划、番茄钟、复盘、复习。", category="goal", confidence=0.9, memory_type="semantic", last_seen_at=now),
        UserMemory(user_id=user_id, memory_key="demo_preferred_coaching", memory_value="希望苏格拉底式追问自然融入普通对话，而不是作为孤立模式切换。", category="style", confidence=0.95, memory_type="semantic", last_seen_at=now, is_locked=1),
        UserMemory(user_id=user_id, memory_key=_DEMO_MARKER_KEY, memory_value=now.isoformat(), category="system", confidence=1.0, status="ignored", memory_type="semantic", last_seen_at=now, is_locked=1),
    ]
    db.add_all(memories)
    created["memories"] += len(memories)

    db.add(MotivationQuote(user_id=user_id, content="把讲不顺的地方留下来，它就是明天最好的学习入口。", author="Mnemox Demo", source_type="preset"))
    created["quotes"] += 1

    events = [
        LearningEvent(user_id=user_id, event_type="material_uploaded", event_category="study", event_data={"demo": True, "material_id": material.id}, timestamp=now - timedelta(days=3), material_id=material.id),
        LearningEvent(user_id=user_id, event_type="pomodoro_complete", event_category="practice", event_data={"demo": True, "duration_minutes": 25}, timestamp=now - timedelta(days=2), duration=1500, material_id=material.id, chapter_id=chapters[0].id),
        LearningEvent(user_id=user_id, event_type="note_created", event_category="study", event_data={"demo": True, "note_type": "summary"}, timestamp=now - timedelta(hours=3), material_id=material.id, chapter_id=chapters[1].id),
    ]
    db.add_all(events)
    created["learning_events"] += len(events)

    await db.commit()

    if settings.RAG_ENABLED:
        try:
            from app.ai.rag_service import get_rag_service
            rag = get_rag_service()
            await rag.initialize()
            await rag.index_material(material.id, material.title, material.content or "", file_type="md", project_ids=[project.id], user_id=user_id)
        except Exception:
            pass

    try:
        from app.services.profile_service import compute_and_save_profile
        await compute_and_save_profile(db, user_id)
        await db.commit()
    except Exception:
        pass

    return DemoSeedOut(ok=True, already_seeded=False, message="Demo 数据已导入，可以开始体验学习闭环", created=created)


@router.get("/version", response_model=VersionInfoOut)
async def get_version(_current_user: User = Depends(get_current_user)):
    """返回当前应用版本"""
    return VersionInfoOut(
        app_name="Mnemox",
        current_version=settings.APP_VERSION,
        checked_at=_now_iso(),
    )


@router.get("/update-check", response_model=UpdateInfoOut)
async def check_update(_current_user: User = Depends(get_current_user)):
    """
    检查是否有新版本。
    需要配置 APP_UPDATE_MANIFEST_URL 指向 JSON 清单，例如：
    {
      "latest_version": "1.0.1",
      "release_notes": "修复若干问题",
      "release_page": "https://example.com/releases/1.0.1",
      "published_at": "2026-04-24T10:00:00Z",
      "downloads": {"windows": "https://example.com/app-1.0.1.exe"}
    }
    """
    checked_at = _now_iso()
    manifest_url = (settings.APP_UPDATE_MANIFEST_URL or "").strip()
    if not manifest_url:
        return UpdateInfoOut(
            has_update=False,
            current_version=settings.APP_VERSION,
            latest_version=settings.APP_VERSION,
            checked_at=checked_at,
            release_notes="未配置更新源（APP_UPDATE_MANIFEST_URL）",
        )

    try:
        async with httpx.AsyncClient(timeout=10.0) as client:
            response = await client.get(manifest_url)
            response.raise_for_status()
            payload = _parse_manifest(response.json())
    except httpx.HTTPError as exc:
        raise HTTPException(status_code=502, detail=f"更新源访问失败: {exc}")
    except ValueError:
        raise HTTPException(status_code=502, detail="更新源响应不是合法 JSON")

    latest_version = str(payload.get("latest_version") or "").strip()
    if not latest_version:
        raise HTTPException(status_code=502, detail="更新源缺少 latest_version 字段")

    release_notes = payload.get("release_notes")
    release_page = payload.get("release_page")
    published_at = payload.get("published_at")
    download_url = _pick_download_url(payload.get("downloads")) or _pick_download_url(
        payload.get("download_url")
    )
    has_update = _is_newer(latest_version, settings.APP_VERSION)

    return UpdateInfoOut(
        has_update=has_update,
        current_version=settings.APP_VERSION,
        latest_version=latest_version,
        release_notes=str(release_notes) if isinstance(release_notes, str) else None,
        release_page=str(release_page) if isinstance(release_page, str) else None,
        download_url=download_url,
        published_at=str(published_at) if isinstance(published_at, str) else None,
        checked_at=checked_at,
    )
