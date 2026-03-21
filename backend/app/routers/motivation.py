"""今日激励语录路由"""
from datetime import datetime, date
import hashlib
from typing import Optional, List, Literal

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field
from sqlalchemy import select, func, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.database import get_db
from app.models.motivation import MotivationQuote, MotivationSettings
from app.models.goal import Goal, Task
from app.models.pomodoro import Pomodoro
from app.ai.factory import AIProviderFactory
from app.auth import get_current_user
from app.models.user import User

router = APIRouter()

DEFAULT_ROTATION_SECONDS = 3 * 3600
MIN_ROTATION_SECONDS = 30 * 60
MAX_ROTATION_SECONDS = 7 * 24 * 3600

SORT_MODES = {
    "created_desc",
    "created_asc",
    "source_priority",
    "author_asc",
    "content_asc",
}

SOURCE_PRIORITY = {
    "custom": 0,
    "ai": 1,
    "preset": 2,
}

PRESET_QUOTES = [
    {"content": "不要因为走得太慢而停下脚步。", "author": "孔子"},
    {"content": "今天的努力，是明天的底气。", "author": "佚名"},
    {"content": "你比想象中更接近答案。", "author": "佚名"},
    {"content": "慢一点没关系，停下才会错过。", "author": "佚名"},
    {"content": "学习不是为了证明，而是为了成长。", "author": "佚名"},
    {"content": "每一次专注，都是在为未来加码。", "author": "佚名"},
    {"content": "不怕慢，就怕站。", "author": "中国谚语"},
    {"content": "Small steps every day lead to big results.", "author": "Anonymous"},
    {"content": "Discipline is the bridge between goals and accomplishment.", "author": "Jim Rohn"},
    {"content": "You are one study session away from better understanding.", "author": "Anonymous"},
    {"content": "Focus on progress, not perfection.", "author": "Anonymous"},
    {"content": "The best time to learn was yesterday. The next best is now.", "author": "Anonymous"},
    {"content": "让今天的自己，领先昨天的自己。", "author": "佚名"},
    {"content": "每次复习，都是一次提升。", "author": "佚名"},
    {"content": "知识会在坚持里发光。", "author": "佚名"},
    {"content": "学习的尽头是更自由的你。", "author": "佚名"},
    {"content": "Keep showing up; the results will follow.", "author": "Anonymous"},
    {"content": "行动会消除焦虑。", "author": "佚名"},
    {"content": "专注当下，就是在雕刻未来。", "author": "佚名"},
    {"content": "你正在积累一个更强的自己。", "author": "佚名"},
]


class QuoteOut(BaseModel):
    id: int
    content: str
    author: Optional[str] = None
    source_type: str
    created_at: Optional[str] = None


class QuoteCreate(BaseModel):
    content: str
    author: Optional[str] = None


class QuoteSettingsOut(BaseModel):
    display_mode: Literal["auto", "manual"]
    selected_quote_id: Optional[int] = None
    sort_mode: str
    rotation_seconds: int


class QuoteSettingsUpdate(BaseModel):
    display_mode: Optional[Literal["auto", "manual"]] = None
    selected_quote_id: Optional[int] = Field(default=None)
    sort_mode: Optional[str] = None
    rotation_seconds: Optional[int] = Field(default=None, ge=MIN_ROTATION_SECONDS, le=MAX_ROTATION_SECONDS)


def _to_quote(q: MotivationQuote) -> QuoteOut:
    created_at = getattr(q, "created_at", None)
    return QuoteOut(
        id=int(getattr(q, "id", 0)),
        content=str(getattr(q, "content", "")),
        author=(str(getattr(q, "author")) if getattr(q, "author", None) is not None else None),
        source_type=str(getattr(q, "source_type", "preset")),
        created_at=created_at.isoformat() if created_at else None,
    )


def _to_settings_out(s: MotivationSettings) -> QuoteSettingsOut:
    mode_raw = str(getattr(s, "display_mode", "auto") or "auto")
    mode: Literal["auto", "manual"] = "manual" if mode_raw == "manual" else "auto"
    return QuoteSettingsOut(
        display_mode=mode,
        selected_quote_id=(int(getattr(s, "selected_quote_id")) if getattr(s, "selected_quote_id", None) is not None else None),
        sort_mode=(str(getattr(s, "sort_mode", "created_desc") or "created_desc")),
        rotation_seconds=max(MIN_ROTATION_SECONDS, int(getattr(s, "rotation_seconds", DEFAULT_ROTATION_SECONDS) or DEFAULT_ROTATION_SECONDS)),
    )


def _uid(current_user: User) -> int:
    return int(getattr(current_user, "id", 0))


def _apply_sort(quotes: List[MotivationQuote], sort_mode: str) -> List[MotivationQuote]:
    mode = sort_mode if sort_mode in SORT_MODES else "created_desc"
    items = list(quotes)

    if mode == "created_asc":
        items.sort(key=lambda q: (q.created_at or datetime.min, q.id))
        return items

    if mode == "source_priority":
        items.sort(
            key=lambda q: (
                SOURCE_PRIORITY.get(str(getattr(q, "source_type", "preset") or "preset"), 99),
                q.created_at or datetime.min,
                q.id,
            ),
            reverse=False,
        )
        return items

    if mode == "author_asc":
        items.sort(key=lambda q: ((q.author or "").lower(), q.created_at or datetime.min, q.id))
        return items

    if mode == "content_asc":
        items.sort(key=lambda q: ((q.content or "").lower(), q.created_at or datetime.min, q.id))
        return items

    items.sort(key=lambda q: (q.created_at or datetime.min, q.id), reverse=True)
    return items


async def _ensure_presets(db: AsyncSession, user_id: int) -> None:
    result = await db.execute(
        select(func.count()).select_from(MotivationQuote)
        .where(MotivationQuote.user_id == user_id)
    )
    count = result.scalar() or 0
    if count > 0:
        return

    presets = [
        MotivationQuote(
            user_id=user_id,
            content=quote["content"],
            author=quote.get("author"),
            source_type="preset",
        )
        for quote in PRESET_QUOTES
    ]
    db.add_all(presets)
    await db.flush()


async def _get_or_create_settings(db: AsyncSession, user_id: int) -> MotivationSettings:
    result = await db.execute(
        select(MotivationSettings).where(MotivationSettings.user_id == user_id)
    )
    settings = result.scalar_one_or_none()
    if settings is not None:
        return settings

    settings = MotivationSettings(
        user_id=user_id,
        display_mode="auto",
        selected_quote_id=None,
        sort_mode="created_desc",
        rotation_seconds=DEFAULT_ROTATION_SECONDS,
    )
    db.add(settings)
    await db.flush()
    await db.refresh(settings)
    return settings


async def _find_quote_for_user(db: AsyncSession, user_id: int, quote_id: int) -> Optional[MotivationQuote]:
    result = await db.execute(
        select(MotivationQuote).where(
            MotivationQuote.id == quote_id,
            MotivationQuote.user_id == user_id,
        )
    )
    return result.scalar_one_or_none()


@router.get("/quotes", response_model=List[QuoteOut])
async def list_quotes(
    source_type: Optional[str] = Query(None),
    sort_mode: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = _uid(current_user)
    await _ensure_presets(db, user_id)
    query = select(MotivationQuote).where(MotivationQuote.user_id == user_id)
    if source_type:
        query = query.where(MotivationQuote.source_type == source_type)
    result = await db.execute(query)
    quotes = list(result.scalars().all())
    mode = sort_mode if sort_mode in SORT_MODES else "created_desc"
    quotes = _apply_sort(quotes, mode)
    return [_to_quote(q) for q in quotes]


@router.post("/quotes", response_model=QuoteOut)
async def add_quote(
    body: QuoteCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = _uid(current_user)
    content = (body.content or "").strip()
    if not content:
        raise HTTPException(status_code=400, detail="语录内容不能为空")

    quote = MotivationQuote(
        user_id=user_id,
        content=content,
        author=(body.author or "").strip() or None,
        source_type="custom",
    )
    db.add(quote)
    await db.flush()
    await db.refresh(quote)
    return _to_quote(quote)


@router.delete("/quotes/{quote_id}")
async def delete_quote(
    quote_id: int,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = _uid(current_user)
    result = await db.execute(
        select(MotivationQuote).where(MotivationQuote.id == quote_id, MotivationQuote.user_id == user_id)
    )
    quote = result.scalar_one_or_none()
    if quote is None:
        raise HTTPException(status_code=404, detail="语录不存在")
    settings = await _get_or_create_settings(db, user_id)
    if getattr(settings, "selected_quote_id", None) == getattr(quote, "id", None):
        setattr(settings, "selected_quote_id", None)
        setattr(settings, "display_mode", "auto")

    await db.delete(quote)
    return {"ok": True}


@router.get("/settings", response_model=QuoteSettingsOut)
async def get_quote_settings(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = _uid(current_user)
    await _ensure_presets(db, user_id)
    settings = await _get_or_create_settings(db, user_id)
    sort_mode = str(getattr(settings, "sort_mode", "created_desc") or "created_desc")
    if sort_mode not in SORT_MODES:
        setattr(settings, "sort_mode", "created_desc")
    rotation_seconds = int(getattr(settings, "rotation_seconds", DEFAULT_ROTATION_SECONDS) or DEFAULT_ROTATION_SECONDS)
    if rotation_seconds < MIN_ROTATION_SECONDS:
        setattr(settings, "rotation_seconds", DEFAULT_ROTATION_SECONDS)
    return _to_settings_out(settings)


@router.put("/settings", response_model=QuoteSettingsOut)
async def update_quote_settings(
    body: QuoteSettingsUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = _uid(current_user)
    await _ensure_presets(db, user_id)
    settings = await _get_or_create_settings(db, user_id)

    if body.sort_mode is not None:
        if body.sort_mode not in SORT_MODES:
            raise HTTPException(status_code=400, detail="不支持的排序方式")
        setattr(settings, "sort_mode", body.sort_mode)

    if body.rotation_seconds is not None:
        setattr(settings, "rotation_seconds", int(body.rotation_seconds))

    if body.selected_quote_id is not None:
        target = await _find_quote_for_user(db, user_id, body.selected_quote_id)
        if not target:
            raise HTTPException(status_code=404, detail="指定语录不存在")
        setattr(settings, "selected_quote_id", int(getattr(target, "id", 0)))

    if body.display_mode is not None:
        selected_quote_id = getattr(settings, "selected_quote_id", None)
        if body.display_mode == "manual" and selected_quote_id is None:
            raise HTTPException(status_code=400, detail="手动模式需要先选择一条语录")
        setattr(settings, "display_mode", body.display_mode)

    await db.flush()
    await db.refresh(settings)
    return _to_settings_out(settings)


@router.get("/current", response_model=Optional[QuoteOut])
async def get_current_quote(
    refresh: Optional[int] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = _uid(current_user)
    await _ensure_presets(db, user_id)
    settings = await _get_or_create_settings(db, user_id)

    result = await db.execute(
        select(MotivationQuote)
        .where(MotivationQuote.user_id == user_id)
    )
    quotes = list(result.scalars().all())
    if not quotes:
        return None

    display_mode = str(getattr(settings, "display_mode", "auto") or "auto")
    selected_quote_id = getattr(settings, "selected_quote_id", None)
    if display_mode == "manual" and selected_quote_id is not None:
        selected = next((q for q in quotes if int(getattr(q, "id", 0)) == int(selected_quote_id)), None)
        if selected is not None:
            return _to_quote(selected)

    sort_mode = str(getattr(settings, "sort_mode", "created_desc") or "created_desc")
    ordered = _apply_sort(quotes, sort_mode)
    if not ordered:
        return None

    rotation_seconds = int(getattr(settings, "rotation_seconds", DEFAULT_ROTATION_SECONDS) or DEFAULT_ROTATION_SECONDS)
    rotation_seconds = max(MIN_ROTATION_SECONDS, min(MAX_ROTATION_SECONDS, rotation_seconds))

    epoch_slot = int(datetime.now().timestamp()) // rotation_seconds
    if refresh:
        epoch_slot += int(refresh)
    seed = f"{user_id}-{epoch_slot}-{sort_mode}"
    index = int(hashlib.md5(seed.encode()).hexdigest(), 16) % len(ordered)
    return _to_quote(ordered[index])


@router.post("/generate", response_model=QuoteOut)
async def generate_quote(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    user_id = _uid(current_user)
    await _ensure_presets(db, user_id)

    today = date.today()
    today_str = today.isoformat()

    goal_result = await db.execute(
        select(Goal.title)
        .where(Goal.user_id == user_id, Goal.status == "active")
        .order_by(Goal.created_at.desc())
        .limit(4)
    )
    goals = [row[0] for row in goal_result.all()]

    task_stats_result = await db.execute(
        select(
            func.count(Task.id),
            func.coalesce(func.sum(case((Task.status == "completed", 1), else_=0)), 0),
        )
        .select_from(Task)
        .join(Goal, Task.goal_id == Goal.id)
        .where(Goal.user_id == user_id, Task.planned_date == today)
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

    goals_text = ", ".join(goals) if goals else "暂无明确目标"
    task_completed_value = int(task_completed or 0)
    task_total_value = int(task_total or 0)
    pomodoro_count_value = int(pomodoro_count or 0)
    pomodoro_minutes_value = int(pomodoro_minutes or 0)

    prompt = (
        "以下是一位学习者的今日学习情况：\n"
        f"当前学习目标: {goals_text}\n"
        f"今日完成任务: {task_completed_value}/{task_total_value}\n"
        f"今日专注时长: {pomodoro_minutes_value} 分钟\n"
        f"今日番茄钟: {pomodoro_count_value} 个\n\n"
        "请生成一句个性化的激励语录。简短、真诚、有力量。\n"
        "只输出语录本身。"
    )

    try:
        provider = await AIProviderFactory.create_provider(db=db, scenario="motivation")
        reply = await provider.chat(
            messages=[{"role": "user", "content": prompt}],
            system_prompt="你是贴心的学习教练。",
            temperature=0.8,
        )
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"生成激励失败: {str(e)}")

    text = (reply or "").strip().strip("\"“”")
    if not text:
        raise HTTPException(status_code=500, detail="生成激励失败")

    quote = MotivationQuote(
        user_id=user_id,
        content=text,
        author="AI",
        source_type="ai",
    )
    db.add(quote)
    await db.flush()
    await db.refresh(quote)
    return _to_quote(quote)
