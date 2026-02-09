"""番茄钟路由"""
from fastapi import APIRouter, Depends, HTTPException
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, extract, case, Integer
from typing import List, Optional
from pydantic import BaseModel
from datetime import datetime, timedelta
import calendar

from app.database import get_db
from app.models.pomodoro import Pomodoro


router = APIRouter()


class PomodoroCreate(BaseModel):
    """创建番茄钟请求"""
    chapter_id: Optional[int] = None
    duration: int = 25  # 默认25分钟


class PomodoroUpdate(BaseModel):
    """更新番茄钟请求"""
    completed: bool
    note: Optional[str] = None


class PomodoroResponse(BaseModel):
    """番茄钟响应"""
    id: int
    chapter_id: Optional[int]
    started_at: str
    ended_at: Optional[str]
    duration: int
    completed: bool
    note: Optional[str]
    created_at: str
    
    class Config:
        from_attributes = True


class PomodoroStats(BaseModel):
    """番茄钟统计"""
    total_count: int  # 总数
    completed_count: int  # 完成数
    total_minutes: int  # 总时长（分钟）
    completion_rate: float  # 完成率
    avg_daily: float  # 日均完成数


class DailyStats(BaseModel):
    """每日统计"""
    date: str
    count: int
    completed_count: int
    total_minutes: int


@router.post("/start", response_model=PomodoroResponse)
async def start_pomodoro(
    data: PomodoroCreate,
    db: AsyncSession = Depends(get_db)
):
    """
    开始一个番茄钟
    
    - **chapter_id**: 关联章节ID（可选）
    - **duration**: 时长（分钟，默认25）
    """
    pomodoro = Pomodoro(
        chapter_id=data.chapter_id,
        started_at=datetime.now(),
        duration=data.duration,
        completed=False
    )
    
    db.add(pomodoro)
    await db.commit()
    await db.refresh(pomodoro)
    
    return PomodoroResponse(
        id=pomodoro.id,
        chapter_id=pomodoro.chapter_id,
        started_at=pomodoro.started_at.isoformat(),
        ended_at=pomodoro.ended_at.isoformat() if pomodoro.ended_at else None,
        duration=pomodoro.duration,
        completed=pomodoro.completed,
        note=pomodoro.note,
        created_at=pomodoro.created_at.isoformat()
    )


@router.put("/{pomodoro_id}/complete", response_model=PomodoroResponse)
async def complete_pomodoro(
    pomodoro_id: int,
    data: PomodoroUpdate,
    db: AsyncSession = Depends(get_db)
):
    """
    完成或取消番茄钟
    
    - **pomodoro_id**: 番茄钟ID
    - **completed**: 是否完成
    - **note**: 备注（可选）
    """
    result = await db.execute(select(Pomodoro).where(Pomodoro.id == pomodoro_id))
    pomodoro = result.scalar_one_or_none()
    
    if not pomodoro:
        raise HTTPException(status_code=404, detail="番茄钟不存在")
    
    pomodoro.completed = data.completed
    pomodoro.ended_at = datetime.now()
    if data.note:
        pomodoro.note = data.note
    
    await db.commit()
    await db.refresh(pomodoro)
    
    return PomodoroResponse(
        id=pomodoro.id,
        chapter_id=pomodoro.chapter_id,
        started_at=pomodoro.started_at.isoformat(),
        ended_at=pomodoro.ended_at.isoformat() if pomodoro.ended_at else None,
        duration=pomodoro.duration,
        completed=pomodoro.completed,
        note=pomodoro.note,
        created_at=pomodoro.created_at.isoformat()
    )


@router.get("/recent", response_model=List[PomodoroResponse])
async def get_recent_pomodoros(
    limit: int = 10,
    db: AsyncSession = Depends(get_db)
):
    """
    获取最近的番茄钟记录
    
    - **limit**: 限制数量（默认10，最大50）
    """
    result = await db.execute(
        select(Pomodoro)
        .order_by(Pomodoro.created_at.desc())
        .limit(min(limit, 50))
    )
    pomodoros = result.scalars().all()
    
    return [
        PomodoroResponse(
            id=p.id,
            chapter_id=p.chapter_id,
            started_at=p.started_at.isoformat(),
            ended_at=p.ended_at.isoformat() if p.ended_at else None,
            duration=p.duration,
            completed=p.completed,
            note=p.note,
            created_at=p.created_at.isoformat()
        )
        for p in pomodoros
    ]


@router.get("/statistics/total", response_model=PomodoroStats)
async def get_total_statistics(db: AsyncSession = Depends(get_db)):
    """
    获取总统计数据
    """
    # 总数和完成数
    result = await db.execute(
        select(
            func.count(Pomodoro.id).label('total'),
            func.sum(case((Pomodoro.completed == True, 1), else_=0)).label('completed'),
            func.sum(Pomodoro.duration).label('total_minutes')
        )
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
async def get_weekly_statistics(db: AsyncSession = Depends(get_db)):
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
        ).where(Pomodoro.created_at >= week_start)
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
    db: AsyncSession = Depends(get_db)
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
                Pomodoro.created_at <= month_end
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
    db: AsyncSession = Depends(get_db)
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
                Pomodoro.created_at <= end_date
            )
        )
        .group_by(func.date(Pomodoro.created_at))
        .order_by(func.date(Pomodoro.created_at))
    )
    
    stats_dict = {
        str(row.date): DailyStats(
            date=str(row.date),
            count=row.count or 0,
            completed_count=row.completed or 0,
            total_minutes=row.total_minutes or 0
        )
        for row in result
    }
    
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
