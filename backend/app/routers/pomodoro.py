"""番茄钟路由"""
from app.utils.utc import utc_now_db, to_db_utc, to_utc_iso
import logging

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException, Query
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select, func, and_, case
from typing import List, Optional, Literal, cast
from pydantic import BaseModel, Field
from datetime import datetime, timedelta
import calendar
import uuid
import json

from app.utils.mutation_lock import lock_user_mutation
from app.models.material import Chapter, Material

from ..database import get_db
from ..models.pomodoro import Pomodoro
from ..auth import get_current_user
from ..models.user import User
from ..services.event_tracker import EventTracker
from ..models.learning_event import EventType
from ..models.goal import Task, Goal
from ..services.coach_action_attempt_service import (
    ACTIVE_ATTEMPT_STATUSES,
    bind_coach_attempt_to_domain_event,
    get_coach_action_attempt,
)
from ..services.learning_event_service import CanonicalEventType
from app.utils.error_safety import redact_sensitive_text, safe_exception_summary


router = APIRouter()
logger = logging.getLogger(__name__)


async def _refresh_profile_after_commit(user_id: int) -> None:
    """Refresh a derived profile only after the request transaction commits."""
    from app.database import async_session_maker
    from app.services.profile_service import compute_and_save_profile

    async with async_session_maker() as session:
        try:
            await compute_and_save_profile(session, user_id)
            await session.commit()
        except Exception as exc:
            await session.rollback()
            logger.warning(
                "番茄钟完成后的画像刷新失败 user_id=%s err=%s",
                user_id,
                safe_exception_summary(exc),
            )


class PomodoroCreate(BaseModel):
    """创建番茄钟请求"""
    chapter_id: Optional[int] = None
    task_id: Optional[int] = None
    task_name: Optional[str] = None
    duration: float = Field(25.0, gt=0, le=1440, allow_inf_nan=False)
    client_record_id: Optional[str] = Field(None, min_length=1, max_length=100)
    started_at: Optional[datetime] = None
    coach_action_attempt_id: Optional[str] = Field(None, max_length=40)


class PomodoroUpdate(BaseModel):
    """更新番茄钟请求"""
    completed: bool
    note: Optional[str] = None
    actual_duration: Optional[float] = Field(None, gt=0, le=1440, allow_inf_nan=False)
    stop_reason: Optional[Literal["early_done", "interrupted", "distracted"]] = None
    ended_at: Optional[datetime] = None


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
    planned_duration: Optional[float] = None
    actual_duration: Optional[float] = None
    note: Optional[str]
    coach_action_attempt_id: Optional[str] = None
    client_record_id: Optional[str] = None
    stop_reason: Optional[str] = None
    time_basis: str = "legacy"
    created_at: str

    model_config = {"from_attributes": True}


class PomodoroStats(BaseModel):
    """番茄钟统计"""
    total_count: int  # 总数
    completed_count: int  # 完成数
    total_minutes: float | None  # 总时长（分钟）
    completion_rate: float | None  # 完成率
    avg_daily: float  # 日均结束记录数
    unknown_duration_count: int = 0
    truncated: bool = False
    time_zone: str = "UTC"


class DailyStats(BaseModel):
    """每日统计"""
    date: str
    count: int
    completed_count: int
    total_minutes: float | None


def _response(p: Pomodoro) -> PomodoroResponse:
    return PomodoroResponse(
        id=p.id, chapter_id=p.chapter_id, task_id=p.task_id, task_name=p.task_name,
        started_at=to_utc_iso(p.started_at or p.created_at),
        ended_at=to_utc_iso(p.ended_at) if p.ended_at else None,
        duration=p.duration, completed=p.completed, note=p.note,
        planned_duration=p.planned_duration, actual_duration=p.actual_duration,
        coach_action_attempt_id=p.coach_action_attempt_id, client_record_id=p.client_record_id,
        stop_reason=p.stop_reason, time_basis=p.time_basis, created_at=to_utc_iso(p.created_at),
    )


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
    return await _start_pomodoro(data, db, current_user)


async def _start_pomodoro(
    data: PomodoroCreate, db: AsyncSession, current_user: User, *,
    planned_duration_known: bool = True, start_estimated: bool = False,
):
    await lock_user_mutation(db, int(current_user.id))
    if data.client_record_id:
        existing = await db.scalar(select(Pomodoro).where(
            Pomodoro.user_id == current_user.id, Pomodoro.client_record_id == data.client_record_id,
        ).execution_options(populate_existing=True))
        if existing:
            if (existing.task_id, existing.chapter_id, existing.task_name, existing.coach_action_attempt_id) != (
                data.task_id, data.chapter_id, data.task_name, data.coach_action_attempt_id,
            ):
                raise HTTPException(status_code=409, detail="计时标识不能用于不同任务")
            return _response(existing)
    if data.chapter_id is not None:
        owned = await db.scalar(select(Chapter.id).join(Material).where(
            Chapter.id == data.chapter_id, Material.user_id == current_user.id))
        if owned is None:
            raise HTTPException(status_code=404, detail="章节不存在")
    if data.task_id is not None:
        task_result = await db.execute(
            select(Task)
            .join(Goal, Task.goal_id == Goal.id)
            .where(Task.id == data.task_id, Goal.user_id == current_user.id)
        )
        if not task_result.scalar_one_or_none():
            raise HTTPException(status_code=404, detail="任务不存在")

    attempt_id = str(data.coach_action_attempt_id or "").strip() or None
    if attempt_id:
        attempt = await get_coach_action_attempt(db, int(current_user.id), attempt_id)
        if not attempt or attempt.status not in ACTIVE_ATTEMPT_STATUSES:
            raise HTTPException(status_code=400, detail="Coach 行动尝试不可用")

    pomodoro = Pomodoro(
        user_id=current_user.id,
        chapter_id=data.chapter_id,
        task_id=data.task_id,
        coach_action_attempt_id=attempt_id,
        task_name=data.task_name,
        started_at=to_db_utc(data.started_at) if data.started_at else utc_now_db(),
        client_record_id=data.client_record_id or str(uuid.uuid4()),
        time_basis="utc",
        duration=data.duration,
        planned_duration=data.duration if planned_duration_known else None,
        record_origin="offline_estimated" if start_estimated else "recorded",
        completed=False
    )

    db.add(pomodoro)
    await db.flush()
    await db.refresh(pomodoro)

    # Keep the domain record, ledger event, and projection outbox in one
    # request transaction. ``get_db`` commits only after this handler returns.
    tracker = EventTracker(db, user_id=cast(int, cast(object, current_user.id)))
    started_event = await tracker.track(
        event_type=EventType.POMODORO_START,
        event_data={
            "pomodoro_id": pomodoro.id,
            "task_name": data.task_name,
            "duration": pomodoro.planned_duration,
            "duration_basis": "planned" if planned_duration_known else "unknown",
            "planned_duration": pomodoro.planned_duration,
            "started_at_basis": "estimated_from_reported_duration" if start_estimated else "recorded",
            "coach_action_attempt_id": attempt_id,
        },
        chapter_id=pomodoro.chapter_id,
        task_id=pomodoro.task_id,
        duration=int(data.duration * 60) if planned_duration_known else None,
        source="pomodoro_router",
        dedupe_key=f"pomodoro.started:{pomodoro.id}",
        occurred_at=pomodoro.started_at,
    )
    if attempt_id:
        try:
            await bind_coach_attempt_to_domain_event(
                db,
                int(current_user.id),
                attempt_id,
                event_id=int(started_event.id),
                event_type=CanonicalEventType.POMODORO_STARTED,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc

    return _response(pomodoro)


@router.put("/{pomodoro_id}/complete", response_model=PomodoroResponse)
async def complete_pomodoro(
    pomodoro_id: int,
    data: PomodoroUpdate,
    background_tasks: BackgroundTasks,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    完成或取消番茄钟

    - **pomodoro_id**: 番茄钟ID
    - **completed**: 是否完成
    - **note**: 备注（可选）
    """
    await lock_user_mutation(db, int(current_user.id))
    result = await db.execute(
        select(Pomodoro).where(Pomodoro.id == pomodoro_id, Pomodoro.user_id == current_user.id).execution_options(populate_existing=True)
    )
    pomodoro = result.scalar_one_or_none()

    if not pomodoro:
        raise HTTPException(status_code=404, detail="番茄钟不存在")

    if pomodoro.ended_at is not None:
        duration = round(float(data.actual_duration), 1) if data.actual_duration is not None else pomodoro.duration
        if (pomodoro.completed != data.completed or abs(pomodoro.duration - duration) > 0.001
                or pomodoro.stop_reason != data.stop_reason
                or (data.note is not None and pomodoro.note != data.note)
                or (data.ended_at is not None and pomodoro.ended_at != to_db_utc(data.ended_at))):
            raise HTTPException(status_code=409, detail="该计时已有不同的结束结果，请刷新记录")
        return _response(pomodoro)
    ended_at = to_db_utc(data.ended_at) if data.ended_at else utc_now_db()
    if pomodoro.time_basis == "utc" and pomodoro.started_at and ended_at < pomodoro.started_at:
        raise HTTPException(status_code=422, detail="结束时间不能早于开始时间")
    if pomodoro.time_basis == "legacy":
        pomodoro.time_basis = "mixed"  # Legacy start, UTC end; never shift both blindly.
    pomodoro.completed = data.completed
    pomodoro.ended_at = ended_at
    if data.note:
        pomodoro.note = data.note
    if data.actual_duration is not None:
        pomodoro.duration = max(0.1, round(float(data.actual_duration), 1))
        pomodoro.actual_duration = pomodoro.duration
    if data.stop_reason is not None:
        pomodoro.stop_reason = data.stop_reason
    elif data.completed:
        pomodoro.stop_reason = None  # 正常完成不设原因

    await db.flush()
    await db.refresh(pomodoro)

    # Keep the domain update, event ledger, and projection outbox atomic.
    _uid: int = cast(int, cast(object, current_user.id))
    event_type = EventType.POMODORO_COMPLETE if data.completed else EventType.POMODORO_INTERRUPT
    actual_mins = pomodoro.actual_duration
    tracker = EventTracker(db, user_id=_uid)
    outcome_event = await tracker.track(
        event_type=event_type,
        event_data={
            "pomodoro_id": pomodoro.id,
            "task_name": pomodoro.task_name,
            "duration": actual_mins,
            "duration_basis": "actual" if pomodoro.actual_duration is not None else "unknown",
            "actual_duration": pomodoro.actual_duration,
            "planned_duration": pomodoro.planned_duration,
            "completed": data.completed,
            "stop_reason": data.stop_reason,  # early_done / interrupted / distracted
            "coach_action_attempt_id": pomodoro.coach_action_attempt_id,
        },
        chapter_id=pomodoro.chapter_id,
        task_id=pomodoro.task_id,
        duration=int(actual_mins * 60) if actual_mins is not None else None,
        source="pomodoro_router",
        dedupe_key=f"pomodoro.{'completed' if data.completed else 'interrupted'}:{pomodoro.id}",
        occurred_at=pomodoro.ended_at,
    )
    if pomodoro.coach_action_attempt_id:
        try:
            await bind_coach_attempt_to_domain_event(
                db,
                _uid,
                pomodoro.coach_action_attempt_id,
                event_id=int(outcome_event.id),
                event_type=(
                    CanonicalEventType.POMODORO_COMPLETED
                    if data.completed
                    else CanonicalEventType.POMODORO_INTERRUPTED
                ),
                outcome="completed" if data.completed else "abandoned",
                reason=data.stop_reason,
            )
        except ValueError as exc:
            raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc
    background_tasks.add_task(_refresh_profile_after_commit, _uid)

    return _response(pomodoro)


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

    return [_response(p) for p in pomodoros]


async def _evidence_stats(db, user_id, first=None, last=None):
    from app.services.behavior_evidence_service import read_focus_date_range, summarize_focus
    records, context = await read_focus_date_range(db, user_id, first, last)
    values = summarize_focus(records)
    observed = [r.local_date for r in records if r.included and r.local_date]
    from datetime import date as date_type
    first = first or (date_type.fromisoformat(min(observed)) if observed else context['today'])
    last = last or context['today']
    return PomodoroStats(total_count=values['finished_count'],completed_count=values['completed_count'],
        total_minutes=values['actual_minutes'],completion_rate=values['completion_rate']*100 if values['completion_rate'] is not None else None,
        avg_daily=round(values['finished_count']/max(1,(min(last,context['today'])-first).days+1),2),
        unknown_duration_count=context['unknown_duration_count'],truncated=context['truncated'],time_zone=context['time_zone'])


@router.get("/statistics/total", response_model=PomodoroStats)
async def get_total_statistics(db: AsyncSession = Depends(get_db),current_user: User = Depends(get_current_user)):
    return await _evidence_stats(db, current_user.id)


@router.get("/statistics/weekly", response_model=PomodoroStats)
async def get_weekly_statistics(db: AsyncSession = Depends(get_db),current_user: User = Depends(get_current_user)):
    from app.services.behavior_evidence_service import read_focus_date_range
    _, context = await read_focus_date_range(db,current_user.id)
    today = context['today']
    return await _evidence_stats(db,current_user.id,today-timedelta(days=today.weekday()),today)


@router.get("/statistics/monthly", response_model=PomodoroStats)
async def get_monthly_statistics(year: Optional[int] = None, month: Optional[int] = None,
    db: AsyncSession = Depends(get_db),current_user: User = Depends(get_current_user)):
    from datetime import date as date_type
    from app.services.behavior_evidence_service import read_focus_date_range
    _, context = await read_focus_date_range(db,current_user.id)
    today = context['today']
    try:
        first = date_type(year or today.year,month or today.month,1)
        last = date_type(first.year,first.month,calendar.monthrange(first.year,first.month)[1])
    except ValueError:
        raise HTTPException(400,'无效的年月')
    return await _evidence_stats(db,current_user.id,first,last)


@router.get("/statistics/daily", response_model=List[DailyStats])
async def get_daily_statistics(days: int = Query(7,ge=1,le=366),
    db: AsyncSession = Depends(get_db),current_user: User = Depends(get_current_user)):
    from app.services.behavior_evidence_service import get_behavior_evidence, summarize_focus
    report = await get_behavior_evidence(db,current_user.id,days=days)
    result = []
    for day in report.daily:
        values = summarize_focus([r for r in report.records if r.local_date==day['date']])
        result.append(DailyStats(date=day['date'],count=values['finished_count'],completed_count=values['completed_count'],
            total_minutes=values['actual_minutes']))
    return result


class PomodoroImport(PomodoroCreate):
    backend_id: Optional[int] = None
    planned_duration: Optional[float] = Field(None, gt=0, le=1440, allow_inf_nan=False)
    completed: bool = True
    stop_reason: Optional[Literal["early_done", "interrupted", "distracted"]] = None
    note: Optional[str] = None


class PomodorosBatchCreate(BaseModel):
    records: List[PomodoroImport] = Field(max_length=500)
    completed_ats: List[datetime]


class BatchCreateResponse(BaseModel):
    created: int
    ids: List[int]


@router.post("/batch", response_model=BatchCreateResponse)
async def batch_create_pomodoros(
    data: PomodorosBatchCreate,
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
    background_tasks: BackgroundTasks = None,
):
    """Replay online/offline records atomically; one client identity, one outcome."""
    if len(data.records) != len(data.completed_ats):
        raise HTTPException(status_code=422, detail="每条计时记录必须提供对应的结束时间")
    await lock_user_mutation(db, int(current_user.id))
    ids, created = [], 0
    completed_tasks = BackgroundTasks()
    for record, timestamp in zip(data.records, data.completed_ats):
        ended_at = to_db_utc(timestamp)
        # Legacy clients did send a completion timestamp: deterministic fallback
        # prevents reimport on retries. New clients always send their stable ID.
        client_id = record.client_record_id or str(uuid.uuid5(uuid.NAMESPACE_URL,
            json.dumps(record.model_dump(mode="json"), sort_keys=True) + to_utc_iso(ended_at)))
        existing = await db.scalar(select(Pomodoro).where(
            Pomodoro.user_id == current_user.id,
            Pomodoro.id == record.backend_id if record.backend_id is not None else Pomodoro.client_record_id == client_id,
        ).execution_options(populate_existing=True))
        if record.backend_id is not None and existing is None:
            raise HTTPException(status_code=404, detail="待同步的原计时不存在，请检查账户和记录")
        if existing is not None:
            if (existing.task_id, existing.task_name) != (record.task_id, record.task_name):
                raise HTTPException(status_code=409, detail="计时标识不能用于不同任务")
            if existing.client_record_id is None:
                existing.client_record_id = client_id
            target_id = existing.id
        else:
            started = await _start_pomodoro(PomodoroCreate(
                **record.model_dump(exclude={"backend_id", "completed", "stop_reason", "note", "client_record_id", "started_at", "planned_duration", "duration"}),
                duration=record.planned_duration or record.duration,
                client_record_id=client_id,
                started_at=record.started_at or ended_at - timedelta(minutes=record.duration),
            ), db, current_user, planned_duration_known=record.planned_duration is not None,
                start_estimated=record.started_at is None)
            target_id = started.id
            created += 1
        await complete_pomodoro(target_id, PomodoroUpdate(
            completed=record.completed, actual_duration=record.duration, stop_reason=record.stop_reason,
            note=record.note, ended_at=ended_at,
        ), completed_tasks, db, current_user)
        ids.append(target_id)
    await db.flush()
    if background_tasks is not None and completed_tasks.tasks:
        background_tasks.add_task(_refresh_profile_after_commit, int(current_user.id))
    return BatchCreateResponse(created=created, ids=ids)
