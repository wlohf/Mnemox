"""番茄钟路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case
from typing import List, Optional, cast
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import calendar

from ..database import get_db
from ..models.pomodoro import Pomodoro
from ..auth import get_current_user
from ..models.user import User
from ..services.event_tracker import EventTracker
from ..models.learning_event import EventType
from ..models.goal import Task, Goal


router = APIRouter()


class PomodoroCreate(BaseModel):
    """创建番茄钟请求"""
    chapter_id: Optional[int] = None
    task_id: Optional[int] = None
    task_name: Optional[str] = None
    duration: float = 25.0  # 默认25分钟


class PomodoroUpdate(BaseModel):
    """更新番茄钟请求"""
    completed: bool
    note: Optional[str] = None
    actual_duration: Optional[float] = None
    stop_reason: Optional[str] = None  # early_done / interrupted / distracted


class PomodoroResponse(BaseModel):
    """番茄钟响应"""
    id: int
    chapter_id: Optional[int]
    task_id: Optional[int]
    task_name: Optional[str]
    started_at: str
    ended_at: Optional[str]
    duration: float
    completed: bool
    note: Optional[str]
    created_at: str

    model_config = {"from_attributes": True}


class PomodoroStats(BaseModel):
    """番茄钟统计"""
    total_count: int  # 总数
    completed_count: int  # 完成数
    total_minutes: float  # 总时长（分钟）
    completion_rate: float  # 完成率
    avg_daily: float  # 日均完成数


class DailyStats(BaseModel):
    """每日统计"""
    date: str
    count: int
    completed_count: int
    total_minutes: float


@router.post("/start", response_model=PomodoroResponse)
async def start_pomodoro(
    data: PomodoroCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    开始一个番茄钟

    - **chapter_id**: 关联章节ID（可选）
    - **duration**: 时长（分钟，默认25）
    """
    if data.task_id is not None:
        task_result = await db.execute(
            select(Task)
            .join(Goal, Task.goal_id == Goal.id)
            .where(Task.id == data.task_id, Goal.user_id == current_user.id)
        )
        if not task_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="任务不存在")

    pomodoro = Pomodoro(
        user_id=current_user.id,
        chapter_id=data.chapter_id,
        task_id=data.task_id,
        task_name=data.task_name,
        started_at=datetime.now(),
        duration=data.duration,
        completed=False
    )

    db.add(pomodoro)
    await db.commit()
    await db.refresh(pomodoro)

    # 记录学习事件：番茄钟开始
    try:
        tracker = EventTracker(db, user_id=cast(int, cast(object, current_user.id)))
        await tracker.track(
            event_type=EventType.POMODORO_START,
            event_data={"pomodoro_id": pomodoro.id, "task_name": data.task_name, "duration": data.duration},
            duration=int(data.duration * 60),
        )
    except Exception:
        pass  # 事件追踪不影响主流程

    started_at = pomodoro.started_at if pomodoro.started_at is not None else pomodoro.created_at
    ended_at = pomodoro.ended_at
    return PomodoroResponse(
        id=pomodoro.id,
        chapter_id=pomodoro.chapter_id,
        task_id=pomodoro.task_id,
        task_name=pomodoro.task_name,
        started_at=started_at.isoformat(),
        ended_at=ended_at.isoformat() if ended_at is not None else None,
        duration=pomodoro.duration,
        completed=pomodoro.completed,
        note=pomodoro.note,
        created_at=pomodoro.created_at.isoformat()
    )


@router.put("/{pomodoro_id}/complete", response_model=PomodoroResponse)
async def complete_pomodoro(
    pomodoro_id: int,
    data: PomodoroUpdate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    完成或取消番茄钟

    - **pomodoro_id**: 番茄钟ID
    - **completed**: 是否完成
    - **note**: 备注（可选）
    """
    result = await db.execute(
        select(Pomodoro).where(Pomodoro.id == pomodoro_id, Pomodoro.user_id == current_user.id)
    )
    pomodoro = result.scalar_one_or_none()

    if not pomodoro:
        raise HTTPException(status_code=404, detail="番茄钟不存在")

    pomodoro.completed = data.completed
    pomodoro.ended_at = datetime.now()
    if data.note:
        pomodoro.note = data.note
    if data.actual_duration is not None:
        pomodoro.duration = max(0.1, round(float(data.actual_duration), 1))
    if data.stop_reason is not None:
        pomodoro.stop_reason = data.stop_reason
    elif data.completed:
        pomodoro.stop_reason = None  # 正常完成不设原因

    await db.commit()
    await db.refresh(pomodoro)

    # 记录学习事件：番茄钟完成或中断；完成后异步刷新用户画像
    try:
        _uid: int = cast(int, cast(object, current_user.id))
        event_type = EventType.POMODORO_COMPLETE if data.completed else EventType.POMODORO_INTERRUPT
        actual_mins = pomodoro.duration
        tracker = EventTracker(db, user_id=_uid)
        await tracker.track(
            event_type=event_type,
            event_data={
                "pomodoro_id": pomodoro.id,
                "task_name": pomodoro.task_name,
                "duration": actual_mins,
                "completed": data.completed,
                "stop_reason": data.stop_reason,  # early_done / interrupted / distracted
            },
            duration=int(actual_mins * 60),
        )
        if data.completed:
            import asyncio
            from app.services.profile_service import compute_and_save_profile
            from app.database import async_session_maker

            async def _bg_refresh(uid: int) -> None:
                async with async_session_maker() as _s:
                    try:
                        await compute_and_save_profile(_s, uid)
                        await _s.commit()
                    except Exception:
                        pass

            asyncio.ensure_future(_bg_refresh(_uid))
    except Exception:
        pass  # 事件追踪不影响主流程

    started_at = pomodoro.started_at if pomodoro.started_at is not None else pomodoro.created_at
    ended_at = pomodoro.ended_at
    ended_at_iso = ended_at.isoformat() if ended_at is not None else None
    return PomodoroResponse(
        id=pomodoro.id,
        chapter_id=pomodoro.chapter_id,
        task_id=pomodoro.task_id,
        task_name=pomodoro.task_name,
        started_at=started_at.isoformat(),
        ended_at=ended_at_iso,
        duration=pomodoro.duration,
        completed=pomodoro.completed,
        note=pomodoro.note,
        created_at=pomodoro.created_at.isoformat()
    )


@router.get("/recent", response_model=List[PomodoroResponse])
async def get_recent_pomodoros(
    limit: int = 10,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取最近的番茄钟记录

    - **limit**: 限制数量（默认10，最大50）
    """
    result = await db.execute(
        select(Pomodoro)
        .where(Pomodoro.user_id == current_user.id)
        .order_by(func.coalesce(Pomodoro.ended_at, Pomodoro.started_at, Pomodoro.created_at).desc())
        .limit(min(limit, 500))
    )
    pomodoros = result.scalars().all()

    return [
        PomodoroResponse(
            id=p.id,
            chapter_id=p.chapter_id,
            task_id=p.task_id,
            task_name=p.task_name,
            started_at=(p.started_at if p.started_at is not None else p.created_at).isoformat(),
            ended_at=p.ended_at.isoformat() if p.ended_at else None,
            duration=p.duration,
            completed=p.completed,
            note=p.note,
            created_at=p.created_at.isoformat()
        )
        for p in pomodoros
    ]


@router.get("/statistics/total", response_model=PomodoroStats)
async def get_total_statistics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取总统计数据
    """
    # 总数和完成数
    result = await db.execute(
        select(
            func.count(Pomodoro.id).label('total'),
            func.sum(case((Pomodoro.completed == True, 1), else_=0)).label('completed'),
            func.sum(Pomodoro.duration).label('total_minutes')
        ).where(Pomodoro.user_id == current_user.id)
    )
    stats = result.one()

    total_count = stats.total or 0
    completed_count = stats.completed or 0
    total_minutes = stats.total_minutes or 0

    # 计算完成率
    completion_rate = (completed_count / total_count * 100) if total_count > 0 else 0

    # 计算日均（从第一个番茄钟到现在的天数）
    first_result = await db.execute(
        select(Pomodoro.created_at)
        .where(Pomodoro.user_id == current_user.id)
        .order_by(Pomodoro.created_at.asc())
        .limit(1)
    )
    first_pomodoro = first_result.scalar_one_or_none()

    if first_pomodoro:
        days = (datetime.now() - first_pomodoro).days + 1
        avg_daily = total_count / days if days > 0 else 0
    else:
        avg_daily = 0

    return PomodoroStats(
        total_count=total_count,
        completed_count=completed_count,
        total_minutes=total_minutes,
        completion_rate=round(completion_rate, 2),
        avg_daily=round(avg_daily, 2)
    )


@router.get("/statistics/weekly", response_model=PomodoroStats)
async def get_weekly_statistics(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取本周统计数据
    """
    # 计算本周的开始时间（周一）
    today = datetime.now()
    week_start = today - timedelta(days=today.weekday())
    week_start = week_start.replace(hour=0, minute=0, second=0, microsecond=0)

    result = await db.execute(
        select(
            func.count(Pomodoro.id).label('total'),
            func.sum(case((Pomodoro.completed == True, 1), else_=0)).label('completed'),
            func.sum(Pomodoro.duration).label('total_minutes')
        ).where(Pomodoro.created_at >= week_start, Pomodoro.user_id == current_user.id)
    )
    stats = result.one()

    total_count = stats.total or 0
    completed_count = stats.completed or 0
    total_minutes = stats.total_minutes or 0

    completion_rate = (completed_count / total_count * 100) if total_count > 0 else 0

    # 本周的日均（已过去的天数）
    days_passed = (datetime.now() - week_start).days + 1
    avg_daily = total_count / days_passed if days_passed > 0 else 0

    return PomodoroStats(
        total_count=total_count,
        completed_count=completed_count,
        total_minutes=total_minutes,
        completion_rate=round(completion_rate, 2),
        avg_daily=round(avg_daily, 2)
    )


@router.get("/statistics/monthly", response_model=PomodoroStats)
async def get_monthly_statistics(
    year: Optional[int] = None,
    month: Optional[int] = None,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取月度统计数据

    - **year**: 年份（默认当前年）
    - **month**: 月份（默认当前月）
    """
    now = datetime.now()
    target_year = year or now.year
    target_month = month or now.month

    # 计算月份的开始和结束
    month_start = datetime(target_year, target_month, 1)
    days_in_month = calendar.monthrange(target_year, target_month)[1]
    month_end = datetime(target_year, target_month, days_in_month, 23, 59, 59)

    result = await db.execute(
        select(
            func.count(Pomodoro.id).label('total'),
            func.sum(case((Pomodoro.completed == True, 1), else_=0)).label('completed'),
            func.sum(Pomodoro.duration).label('total_minutes')
        ).where(
            and_(
                Pomodoro.created_at >= month_start,
                Pomodoro.created_at <= month_end,
                Pomodoro.user_id == current_user.id,
            )
        )
    )
    stats = result.one()

    total_count = stats.total or 0
    completed_count = stats.completed or 0
    total_minutes = stats.total_minutes or 0

    completion_rate = (completed_count / total_count * 100) if total_count > 0 else 0

    # 本月日均
    if target_year == now.year and target_month == now.month:
        days_passed = now.day
    else:
        days_passed = days_in_month

    avg_daily = total_count / days_passed if days_passed > 0 else 0

    return PomodoroStats(
        total_count=total_count,
        completed_count=completed_count,
        total_minutes=total_minutes,
        completion_rate=round(completion_rate, 2),
        avg_daily=round(avg_daily, 2)
    )


@router.get("/statistics/daily", response_model=List[DailyStats])
async def get_daily_statistics(
    days: int = 7,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取每日统计数据

    - **days**: 最近N天（默认7天）
    """
    # 计算开始日期
    end_date = datetime.now().replace(hour=23, minute=59, second=59)
    start_date = end_date - timedelta(days=days-1)
    start_date = start_date.replace(hour=0, minute=0, second=0, microsecond=0)

    # 按日期分组统计
    result = await db.execute(
        select(
            func.date(Pomodoro.created_at).label('date'),
            func.count(Pomodoro.id).label('count'),
            func.sum(case((Pomodoro.completed == True, 1), else_=0)).label('completed'),
            func.sum(Pomodoro.duration).label('total_minutes')
        )
        .where(
            and_(
                Pomodoro.created_at >= start_date,
                Pomodoro.created_at <= end_date,
                Pomodoro.user_id == current_user.id,
            )
        )
        .group_by(func.date(Pomodoro.created_at))
        .order_by(func.date(Pomodoro.created_at))
    )

    stats_dict = {}
    for row in result:
        row_map = row._mapping
        date_value = row_map.get("date")
        count_value = row_map.get("count") or 0
        completed_value = row_map.get("completed") or 0
        minutes_value = row_map.get("total_minutes") or 0
        stats_dict[str(date_value)] = DailyStats(
            date=str(date_value),
            count=int(count_value),
            completed_count=int(completed_value),
            total_minutes=float(minutes_value),
        )

    # 填充缺失的日期
    daily_stats = []
    current_date = start_date
    while current_date <= end_date:
        date_str = current_date.strftime('%Y-%m-%d')
        if date_str in stats_dict:
            daily_stats.append(stats_dict[date_str])
        else:
            daily_stats.append(DailyStats(
                date=date_str,
                count=0,
                completed_count=0,
                total_minutes=0
            ))
        current_date += timedelta(days=1)

    return daily_stats


class PomodorosBatchCreate(BaseModel):
    """批量创建番茄钟请求"""
    records: List[PomodoroCreate]
    completed_ats: List[Optional[str]] = Field(default_factory=list)  # ISO date strings for each record


class BatchCreateResponse(BaseModel):
    """批量创建响应"""
    created: int
    ids: List[int]


@router.post("/batch", response_model=BatchCreateResponse)
async def batch_create_pomodoros(
    data: PomodorosBatchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    批量创建番茄钟记录（用于迁移 localStorage 历史数据）

    - **records**: 番茄钟记录列表
    - **completed_ats**: 每条记录的完成时间（ISO格式，可选）
    """
    created_ids = []
    for i, record in enumerate(data.records):
        if record.task_id is not None:
            task_result = await db.execute(
                select(Task)
                .join(Goal, Task.goal_id == Goal.id)
                .where(Task.id == record.task_id, Goal.user_id == current_user.id)
            )
            if not task_result.scalar_one_or_none():
                continue

        completed_at = None
        if i < len(data.completed_ats):
            completed_at_value = data.completed_ats[i]
            if completed_at_value is not None:
                try:
                    completed_at = datetime.fromisoformat(completed_at_value)
                except (ValueError, TypeError):
                    completed_at = datetime.now()
        if completed_at is None:
            completed_at = datetime.now()

        pomodoro = Pomodoro(
            user_id=current_user.id,
            chapter_id=record.chapter_id,
            task_id=record.task_id,
            task_name=record.task_name,
            started_at=completed_at - timedelta(minutes=record.duration),
            ended_at=completed_at,
            duration=record.duration,
            completed=True
        )
        db.add(pomodoro)
        await db.flush()
        created_ids.append(pomodoro.id)

    await db.commit()

    return BatchCreateResponse(
        created=len(created_ids),
        ids=created_ids
    )
