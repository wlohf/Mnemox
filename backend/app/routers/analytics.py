"""数据分析路由 — 学习趋势、时段效率相关性、目标完成预测"""
from __future__ import annotations

from datetime import datetime, timedelta, date
from typing import Optional, List

import numpy as np
import pandas as pd
from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel
from scipy import stats as sp_stats
from sqlalchemy import select, func, and_, case
from sqlalchemy.ext.asyncio import AsyncSession

from app.auth import get_current_user
from app.database import get_db
from app.models.goal import Goal, Task
from app.models.pomodoro import Pomodoro
from app.models.question import WrongQuestion, ReviewSchedule
from app.models.user import User
from app.services.coach_experiment_service import build_coach_experiment_report
from app.services.north_star_metrics_service import build_north_star_metrics
from app.utils.error_safety import redact_sensitive_text
from app.services.behavior_evidence_service import get_behavior_evidence, read_focus_date_range, summarize_focus, measured_minutes


router = APIRouter()


# ════════════════════════════════════════════
# Schemas
# ════════════════════════════════════════════

class TrendPoint(BaseModel):
    date: str
    study_minutes: float | None
    pomodoro_count: int
    completed_count: int
    completion_rate: float | None


class TrendResponse(BaseModel):
    period: str
    start_date: str
    end_date: str
    points: List[TrendPoint]
    summary: dict


class SlotEfficiency(BaseModel):
    slot: str
    slot_label: str
    pomodoro_count: int
    completed_count: int
    completion_rate: float | None
    avg_duration: float | None
    early_done_count: int
    efficiency_score: float | None


class EfficiencyResponse(BaseModel):
    slots: List[SlotEfficiency]
    correlation: dict
    best_slot: Optional[str]
    insight: str


class PredictionResponse(BaseModel):
    goal_id: int
    goal_title: str
    total_tasks: int
    completed_tasks: int
    progress_rate: float
    predicted_completion_date: Optional[str]
    predicted_days_remaining: Optional[int]
    confidence: Optional[float]
    on_track: bool
    insight: str


@router.get("/north-star")
async def get_north_star_metrics(
    days: int = Query(28, ge=7, le=90, description="统计窗口（7-90 天）"),
    time_zone: str = Query("UTC", min_length=1, max_length=64, description="IANA 时区，例如 Asia/Tokyo"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the four behavior metrics with their evidence and coverage state."""

    try:
        return await build_north_star_metrics(
            db,
            int(current_user.id),
            days=days,
            time_zone=time_zone,
        )
    except ValueError as exc:
        raise HTTPException(status_code=400, detail=redact_sensitive_text(exc)) from exc


@router.get("/coach-experiment")
async def get_coach_experiment_report(
    days: int = Query(28, ge=7, le=90, description="观察窗口（7-90 天）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Return the current learner's observation-only Coach experiment trace."""

    return await build_coach_experiment_report(db, int(current_user.id), days=days)


# ════════════════════════════════════════════
# 1. 学习时长趋势（自定义时间段）
# ════════════════════════════════════════════

@router.get("/trend", response_model=TrendResponse)
async def get_study_trend(
    period: str = Query("30d", description="时间段: 7d / 30d / 90d / 365d / custom"),
    start: Optional[str] = Query(None, description="自定义开始日期 YYYY-MM-DD（period=custom 时必填）"),
    end: Optional[str] = Query(None, description="自定义结束日期 YYYY-MM-DD（period=custom 时必填）"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    获取学习时长趋势数据，支持自定义时间段。

    - period: 7d / 30d / 90d / 365d / custom
    - start, end: period=custom 时使用
    """
    _, context = await read_focus_date_range(db, current_user.id)
    end_date = context['today']
    if period == 'custom':
        try:
            start_date, end_date = date.fromisoformat(start or ''), date.fromisoformat(end or '')
        except ValueError:
            raise HTTPException(400, '请提供 YYYY-MM-DD 格式的 start 和 end')
    else:
        days = {'7d':7, '30d':30, '90d':90, '365d':365}.get(period)
        if days is None:
            raise HTTPException(400, '不支持的 period')
        start_date = end_date - timedelta(days=days-1)
    count = (end_date-start_date).days+1
    if not 1 <= count <= 366:
        raise HTTPException(400, '时间区间须在 1–366 天之间')
    records, context = await read_focus_date_range(db, current_user.id, start_date, end_date)
    points = []
    for offset in range(count):
        day = (start_date+timedelta(days=offset)).isoformat()
        values = summarize_focus([r for r in records if r.local_date == day])
        points.append(TrendPoint(date=day, study_minutes=values['actual_minutes'],
            pomodoro_count=values['finished_count'], completed_count=values['completed_count'],
            completion_rate=values['completion_rate']*100 if values['completion_rate'] is not None else None))
    values = summarize_focus(records)
    return TrendResponse(period=period,start_date=start_date.isoformat(),end_date=end_date.isoformat(),points=points,
        summary={'total_study_hours': values['actual_minutes']/60 if values['actual_minutes'] is not None else None,
            'total_pomodoros':values['finished_count'],'total_completed':values['completed_count'],
            'overall_completion_rate':values['completion_rate']*100 if values['completion_rate'] is not None else None,
            'active_days':sum(p.pomodoro_count>0 for p in points),'total_days':count,
            'avg_daily_minutes':None, 'mean_observed_session_minutes':values['mean_actual_minutes'],
            'missing_days_are_unknown': True, **context})


# ════════════════════════════════════════════
# 2. 时段效率相关性分析（pandas + scipy）
# ════════════════════════════════════════════

_SLOT_RANGES = {
    "morning":   (6, 12, "上午 6-12"),
    "afternoon": (12, 18, "下午 12-18"),
    "evening":   (18, 23, "晚上 18-23"),
    "night":     (23, 6, "深夜 23-6"),
}


def _hour_to_slot(hour: int) -> str:
    if 6 <= hour < 12:
        return "morning"
    elif 12 <= hour < 18:
        return "afternoon"
    elif 18 <= hour < 23:
        return "evening"
    else:
        return "night"


@router.get("/efficiency", response_model=EfficiencyResponse)
async def get_time_slot_efficiency(
    days: int = Query(30, ge=7, le=365, description="分析最近 N 天的数据"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Activity distribution only: completion is not learning efficiency."""
    report = await get_behavior_evidence(db, current_user.id, days=days)
    slots = []
    for name, (_, _, label) in _SLOT_RANGES.items():
        records = [r for r in report.records if r.included and r.local_hour is not None and _hour_to_slot(r.local_hour) == name]
        values = summarize_focus(records)
        slots.append(SlotEfficiency(slot=name,slot_label=label,pomodoro_count=values['finished_count'],
            completed_count=values['completed_count'], avg_duration=values['mean_actual_minutes'],
            completion_rate=values['completion_rate']*100 if values['completion_rate'] is not None else None,
            early_done_count=values['early_done_count'],efficiency_score=None))
    return EfficiencyResponse(slots=slots,correlation={'method':'not_estimated','coefficient':None,'p_value':None},
        best_slot=None,insight='这里只展示各时段的记录分布和完成情况，尚不能判断学习效率或最适合你的时段。')


# ════════════════════════════════════════════
# 3. 目标完成日期预测（numpy 线性回归）
# ════════════════════════════════════════════

@router.get("/prediction", response_model=List[PredictionResponse])
async def predict_goal_completion(
    goal_id: Optional[int] = Query(None, description="指定目标 ID，不传则预测所有活跃目标"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    基于历史任务完成速度，用线性回归预测目标完成日期。
    """
    # 查询目标
    query = select(Goal).where(Goal.user_id == current_user.id, Goal.status == "active")
    if goal_id:
        query = query.where(Goal.id == goal_id)
    goal_result = await db.execute(query)
    goals = goal_result.scalars().all()

    if not goals:
        return []

    predictions: List[PredictionResponse] = []

    for goal in goals:
        # 查询该目标下所有任务
        task_result = await db.execute(
            select(Task).where(Task.goal_id == goal.id)
        )
        tasks = task_result.scalars().all()
        total_tasks = len(tasks)

        if total_tasks == 0:
            predictions.append(PredictionResponse(
                goal_id=goal.id,
                goal_title=goal.title,
                total_tasks=0,
                completed_tasks=0,
                progress_rate=0.0,
                predicted_completion_date=None,
                predicted_days_remaining=None,
                confidence=None,
                on_track=False,
                insight="该目标尚未创建任务，无法预测。",
            ))
            continue

        completed_tasks = [t for t in tasks if t.status == "completed"]
        completed_count = len(completed_tasks)
        progress_rate = round(completed_count / total_tasks * 100, 1)

        # 已全部完成
        if completed_count == total_tasks:
            predictions.append(PredictionResponse(
                goal_id=goal.id,
                goal_title=goal.title,
                total_tasks=total_tasks,
                completed_tasks=completed_count,
                progress_rate=100.0,
                predicted_completion_date=None,
                predicted_days_remaining=0,
                confidence=1.0,
                on_track=True,
                insight="目标已完成！",
            ))
            continue

        # 构建累计完成曲线：按完成时间排序
        completed_with_time = [
            t for t in completed_tasks if t.completed_at is not None
        ]

        if len(completed_with_time) < 2:
            # 数据不足，用简单速率估算
            if completed_count > 0 and goal.plan_start_date:
                days_elapsed = (date.today() - goal.plan_start_date).days or 1
                rate = completed_count / days_elapsed  # 每天完成任务数
                remaining = total_tasks - completed_count
                est_days = int(remaining / rate) if rate > 0 else None
                est_date = (date.today() + timedelta(days=est_days)).isoformat() if est_days else None
                on_track = (
                    goal.deadline is not None
                    and est_date is not None
                    and date.fromisoformat(est_date) <= goal.deadline
                )
                predictions.append(PredictionResponse(
                    goal_id=goal.id,
                    goal_title=goal.title,
                    total_tasks=total_tasks,
                    completed_tasks=completed_count,
                    progress_rate=progress_rate,
                    predicted_completion_date=est_date,
                    predicted_days_remaining=est_days,
                    confidence=0.3,
                    on_track=on_track,
                    insight=f"数据较少，粗略估计还需 {est_days} 天完成。" if est_days else "无法估计完成时间。",
                ))
            else:
                predictions.append(PredictionResponse(
                    goal_id=goal.id,
                    goal_title=goal.title,
                    total_tasks=total_tasks,
                    completed_tasks=completed_count,
                    progress_rate=progress_rate,
                    predicted_completion_date=None,
                    predicted_days_remaining=None,
                    confidence=None,
                    on_track=False,
                    insight="完成数据不足（至少需要 2 个已完成任务），暂无法预测。",
                ))
            continue

        # 线性回归：X = 天数（从第一个完成日算起），Y = 累计完成数
        completed_with_time.sort(key=lambda t: t.completed_at)
        base_date = completed_with_time[0].completed_at.date()

        x_days = []
        y_cumulative = []
        for i, t in enumerate(completed_with_time, 1):
            day_offset = (t.completed_at.date() - base_date).days
            x_days.append(float(day_offset))
            y_cumulative.append(float(i))

        x_arr = np.array(x_days)
        y_arr = np.array(y_cumulative)

        # numpy 线性回归: y = slope * x + intercept
        if len(set(x_days)) < 2:
            # 所有任务同一天完成，无法拟合
            rate = completed_count  # 一天完成这么多
            remaining = total_tasks - completed_count
            est_days = max(1, int(remaining / rate)) if rate > 0 else None
            predictions.append(PredictionResponse(
                goal_id=goal.id,
                goal_title=goal.title,
                total_tasks=total_tasks,
                completed_tasks=completed_count,
                progress_rate=progress_rate,
                predicted_completion_date=(date.today() + timedelta(days=est_days)).isoformat() if est_days else None,
                predicted_days_remaining=est_days,
                confidence=0.4,
                on_track=True,
                insight=f"任务集中完成，预计还需 {est_days} 天。" if est_days else "无法预测。",
            ))
            continue

        # polyfit degree=1
        coeffs = np.polyfit(x_arr, y_arr, 1)
        slope = float(coeffs[0])
        intercept = float(coeffs[1])

        # R² 置信度
        y_pred = slope * x_arr + intercept
        ss_res = float(np.sum((y_arr - y_pred) ** 2))
        ss_tot = float(np.sum((y_arr - np.mean(y_arr)) ** 2))
        r_squared = 1 - ss_res / ss_tot if ss_tot > 0 else 0.0
        confidence = round(max(0.0, min(1.0, r_squared)), 3)

        if slope <= 0:
            predictions.append(PredictionResponse(
                goal_id=goal.id,
                goal_title=goal.title,
                total_tasks=total_tasks,
                completed_tasks=completed_count,
                progress_rate=progress_rate,
                predicted_completion_date=None,
                predicted_days_remaining=None,
                confidence=confidence,
                on_track=False,
                insight="完成速度趋于停滞，建议调整学习计划。",
            ))
            continue

        # 预测：y = total_tasks 时的 x
        target_day = (total_tasks - intercept) / slope
        days_from_base = max(0, int(target_day))
        predicted_date = base_date + timedelta(days=days_from_base)
        days_remaining = (predicted_date - date.today()).days
        days_remaining = max(0, days_remaining)

        on_track = goal.deadline is not None and predicted_date <= goal.deadline

        if goal.deadline:
            deadline_str = goal.deadline.isoformat()
            if on_track:
                insight = f"按当前进度，预计 {predicted_date.isoformat()} 完成，在截止日期（{deadline_str}）之前。"
            else:
                overdue_days = (predicted_date - goal.deadline).days
                insight = f"按当前进度，预计 {predicted_date.isoformat()} 完成，将超出截止日期 {overdue_days} 天，建议加快进度。"
        else:
            insight = f"按当前进度，预计 {predicted_date.isoformat()} 完成（还需约 {days_remaining} 天）。"

        predictions.append(PredictionResponse(
            goal_id=goal.id,
            goal_title=goal.title,
            total_tasks=total_tasks,
            completed_tasks=completed_count,
            progress_rate=progress_rate,
            predicted_completion_date=predicted_date.isoformat(),
            predicted_days_remaining=days_remaining,
            confidence=confidence,
            on_track=on_track,
            insight=insight,
        ))

    return predictions


# ════════════════════════════════════════════
# 4. SM-2 复习预测（未来 N 天复习任务分布）
# ════════════════════════════════════════════

class ReviewForecastDay(BaseModel):
    date: str
    question_count: int
    chapter_count: int
    total: int


class ReviewForecastResponse(BaseModel):
    forecast_days: int
    days: List[ReviewForecastDay]
    total_due: int
    overdue_count: int
    insight: str


@router.get("/review-forecast", response_model=ReviewForecastResponse)
async def get_review_forecast(
    days: int = Query(7, ge=1, le=30, description="预测未来 N 天"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    基于 SM-2 复习计划表，预测未来 N 天每天需要复习的任务数量。
    同时统计已逾期未复习的任务。
    """
    now = datetime.now()
    today = now.date()
    end_date = today + timedelta(days=days)

    # 查询所有 pending 的复习任务
    result = await db.execute(
        select(ReviewSchedule).where(
            ReviewSchedule.user_id == current_user.id,
            ReviewSchedule.status == "pending",
        )
    )
    schedules = result.scalars().all()

    # 按日期分桶
    overdue_count = 0
    day_buckets: dict = {}
    for i in range(days):
        d = today + timedelta(days=i)
        day_buckets[d] = {"question": 0, "chapter": 0}

    for s in schedules:
        sched_date = s.scheduled_date
        if not sched_date:
            continue
        # 处理 datetime 和 date 类型
        s_date = sched_date.date() if hasattr(sched_date, "date") else sched_date

        if s_date < today:
            overdue_count += 1
            # 逾期的算到今天
            if today in day_buckets:
                item_type = s.item_type or "question"
                day_buckets[today][item_type] = day_buckets[today].get(item_type, 0) + 1
        elif s_date <= end_date and s_date in day_buckets:
            item_type = s.item_type or "question"
            day_buckets[s_date][item_type] = day_buckets[s_date].get(item_type, 0) + 1

    forecast_days_list: List[ReviewForecastDay] = []
    total_due = 0
    for i in range(days):
        d = today + timedelta(days=i)
        bucket = day_buckets.get(d, {"question": 0, "chapter": 0})
        q_count = bucket.get("question", 0)
        c_count = bucket.get("chapter", 0)
        total = q_count + c_count
        total_due += total
        forecast_days_list.append(ReviewForecastDay(
            date=d.isoformat(),
            question_count=q_count,
            chapter_count=c_count,
            total=total,
        ))

    # 生成洞察
    if total_due == 0 and overdue_count == 0:
        insight = f"未来 {days} 天没有待复习任务，保持学习节奏！"
    elif overdue_count > 0:
        insight = f"有 {overdue_count} 个逾期任务需要尽快复习，未来 {days} 天共 {total_due} 个复习任务。"
    else:
        avg = total_due / days
        peak_day = max(forecast_days_list, key=lambda d: d.total)
        insight = f"未来 {days} 天共 {total_due} 个复习任务，日均 {avg:.1f} 个，{peak_day.date} 最多（{peak_day.total} 个）。"

    return ReviewForecastResponse(
        forecast_days=days,
        days=forecast_days_list,
        total_due=total_due,
        overdue_count=overdue_count,
        insight=insight,
    )


# ════════════════════════════════════════════
# 5. 学习报告导出（CSV / Excel）
# ════════════════════════════════════════════

@router.get("/export")
async def export_study_report(
    format: str = Query("csv", description="导出格式: csv / excel"),
    period: str = Query("30d", description="时间段: 7d / 30d / 90d / 365d / custom"),
    start: Optional[str] = Query(None),
    end: Optional[str] = Query(None),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """
    导出学习报告为 CSV 或 Excel 文件。

    包含：每日学习时长、番茄钟统计、完成率。
    """
    from fastapi.responses import StreamingResponse
    import io

    # 复用 trend 的时间段解析逻辑
    now = datetime.now()
    end_date = now.date()

    if period == "custom":
        if not start or not end:
            raise HTTPException(status_code=400, detail="自定义时间段需提供 start 和 end 参数")
        try:
            start_date = date.fromisoformat(start)
            end_date = date.fromisoformat(end)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误")
    else:
        days_map = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
        d = days_map.get(period, 30)
        start_date = end_date - timedelta(days=d - 1)

    since_dt = datetime.combine(start_date, datetime.min.time())
    until_dt = datetime.combine(end_date, datetime.max.time())

    # 查询番茄钟数据
    result = await db.execute(
        select(Pomodoro).where(
            Pomodoro.user_id == current_user.id,
            Pomodoro.created_at >= since_dt,
            Pomodoro.created_at <= until_dt,
        )
    )
    pomodoros = result.scalars().all()

    # 构建 DataFrame
    if pomodoros:
        records = []
        for p in pomodoros:
            ts = p.started_at or p.created_at
            records.append({
                "日期": ts.date().isoformat() if ts else "",
                "开始时间": ts.strftime("%H:%M") if ts else "",
                "时长(分钟)": float(p.duration) if p.duration else 0.0,
                "是否完成": "是" if p.completed else "否",
                "停止原因": {"early_done": "提前完成", "interrupted": "临时中断", "distracted": "走神"}.get(p.stop_reason or "", "正常完成" if p.completed else ""),
                "任务名称": p.task_name or "",
            })
        df = pd.DataFrame(records)
    else:
        df = pd.DataFrame(columns=["日期", "开始时间", "时长(分钟)", "是否完成", "停止原因", "任务名称"])

    # 追加汇总行
    if not df.empty:
        summary_row = {
            "日期": "汇总",
            "开始时间": "",
            "时长(分钟)": df["时长(分钟)"].sum(),
            "是否完成": f'{(df["是否完成"] == "是").sum()}/{len(df)}',
            "停止原因": "",
            "任务名称": "",
        }
        df = pd.concat([df, pd.DataFrame([summary_row])], ignore_index=True)

    # 查询错题数据
    wq_result = await db.execute(
        select(WrongQuestion).where(
            WrongQuestion.user_id == current_user.id,
        )
    )
    wrong_questions = wq_result.scalars().all()

    if wrong_questions:
        wq_records = []
        for wq in wrong_questions:
            q = wq.question
            wq_records.append({
                "错题内容": q.content if q else "",
                "知识点": wq.knowledge_point or "",
                "错误次数": wq.wrong_count or 0,
                "复习次数": wq.review_count or 0,
                "回忆难度": {"easy": "很快做出来", "hard": "有点卡", "forgot": "完全想不起来"}.get(wq.recall_difficulty or "", "未评估"),
                "掌握度": wq.mastery_score or 0.0,
                "掌握状态": {"mastered": "已掌握", "partial": "部分掌握", "not_mastered": "未掌握"}.get(wq.mastery_status or "", "未掌握"),
            })
        wq_df = pd.DataFrame(wq_records)
    else:
        wq_df = pd.DataFrame(columns=["错题内容", "知识点", "错误次数", "复习次数", "回忆难度", "掌握度", "掌握状态"])

    # 导出
    if format == "excel":
        buffer = io.BytesIO()
        with pd.ExcelWriter(buffer, engine="openpyxl") as writer:
            df.to_excel(writer, sheet_name="番茄钟记录", index=False)
            wq_df.to_excel(writer, sheet_name="错题分析", index=False)
        buffer.seek(0)
        filename = f"study_report_{start_date}_{end_date}.xlsx"
        return StreamingResponse(
            buffer,
            media_type="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )
    else:
        # CSV：只导出番茄钟（CSV 不支持多 sheet）
        buffer = io.StringIO()
        df.to_csv(buffer, index=False, encoding="utf-8-sig")
        buffer.seek(0)
        filename = f"study_report_{start_date}_{end_date}.csv"
        return StreamingResponse(
            io.BytesIO(buffer.getvalue().encode("utf-8-sig")),
            media_type="text/csv; charset=utf-8",
            headers={"Content-Disposition": f'attachment; filename="{filename}"'},
        )


class EDAInsight(BaseModel):
    title: str
    detail: str
    severity: str


class EDAProfile(BaseModel):
    profile_type: str
    confidence: Optional[float]
    best_study_window: str
    evidence: List[str]


class EDAReportResponse(BaseModel):
    period_days: int
    start_date: str
    end_date: str
    summary: dict
    daily_points: List[dict]
    insights: List[EDAInsight]
    recommendations: List[str]
    profile: EDAProfile
    chart_analysis: List[str]
    charts: dict
    markdown: str


@router.get("/eda-report", response_model=EDAReportResponse)
async def get_eda_report(
    days: int = Query(30, ge=7, le=365, description="统计最近 N 天学习行为"),
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
):
    """Reproducible descriptive report over the same canonical evidence as DI."""
    report = await get_behavior_evidence(db, current_user.id, days=days)
    records = [r for r in report.records if r.included]
    first, last = report.window['first_local_date'], report.window['last_local_date']
    def distribution(subset):
        v = summarize_focus(subset)
        return {'sessions':v['finished_count'], 'minutes':v['actual_minutes'],
                'completion_rate':v['completion_rate']*100 if v['completion_rate'] is not None else None,
                'avg_duration':v['mean_actual_minutes']}
    daily = []
    for point in report.daily:
        subset = [r for r in records if r.local_date == point['date']]
        v = distribution(subset)
        daily.append({'date':point['date'],'study_minutes':v['minutes'],'pomodoro_count':v['sessions'],
            'completion_rate':v['completion_rate'],'rolling7_minutes':None,'status':point['status'],
            'unknown_duration_count':point['unknown_duration_count']})
    hourly = [{'hour':hour, **distribution([r for r in records if r.local_hour == hour])} for hour in range(24)]
    labels = ['周一','周二','周三','周四','周五','周六','周日']
    weekday = [{'weekday':i,'label':label, **distribution([r for r in records if date.fromisoformat(r.local_date).weekday()==i])} for i,label in enumerate(labels)]
    heat = [[hour, wd, distribution([r for r in records if r.local_hour==hour and date.fromisoformat(r.local_date).weekday()==wd])['minutes']]
            for wd in range(7) for hour in range(24)]
    tasks = (await db.scalars(select(Task).join(Goal).where(Goal.user_id==current_user.id,
        Task.planned_date >= date.fromisoformat(first),Task.planned_date <= date.fromisoformat(last)))).all()
    from app.services.experience_service import demo_goal_ids
    demo_goals = await demo_goal_ids(db,current_user.id)
    tasks = [t for t in tasks if t.goal_id not in demo_goals]
    completed = sum(t.status=='completed' and t.completed_at is not None for t in tasks)
    m = report.metrics
    actual_days = sum(point['actual_minutes'] is not None for point in report.daily)
    reasons = {'completed':m['completed_count']-m['early_done_count'],'early_done':m['early_done_count'],
               'interrupted':m['interrupted_count']-m['distracted_count'],'distracted':m['distracted_count']}
    values = [measured_minutes(r) for r in records if measured_minutes(r) is not None]
    buckets = [{'bucket':label,'count':sum(low <= v < high for v in values)} for label,low,high in
               [('少于 20 分钟',0,20),('20–30 分钟',20,30),('30–45 分钟',30,45),('45 分钟以上',45,1441)]]
    boundary = '描述性记录，不推断固定人格或学习效率'
    summary = {'total_minutes':m['actual_minutes'],
        'avg_daily_minutes':round(m['actual_minutes']/actual_days,1) if actual_days else None,
        'average_basis':'仅实际时长已记录的日期；未记录日期未知',
        'pomodoro_count':m['finished_count'],'completion_rate':m['completion_rate']*100 if m['completion_rate'] is not None else None,
        'active_days':report.coverage['observed_days'],'total_tasks':len(tasks),'completed_tasks':completed,
        'pending_tasks':len(tasks)-completed,'peak_hour':m['most_recorded_hour'],
        'profile_type':boundary,'profile_confidence':None,'stop_reason_counts':reasons,
        'unknown_duration_count':m['unknown_actual_duration_count'],'coverage':report.coverage,
        'time_zone':report.time_zone,'quality_counts':report.quality_counts}
    notes = [f"按 {report.time_zone} 的自然日归属结束记录。", '只累加明确记录的实际时长，缺失不是零。',
             '同源记录不增加独立证据；记录分布不能推断效率、原因或长期特性。',
             f"有 {m['unknown_actual_duration_count']} 条结束记录缺少可用实际时长。"]
    charts = {'daily_trend':daily,'hourly_distribution':hourly,'weekday_distribution':weekday,
        'hour_week_heatmap':{'hours':list(range(24)),'weekdays':labels,'points':heat},
        'stop_reason_distribution':[{'reason':name,'key':key,'count':reasons[key]} for key,name in
            [('completed','正常完成'),('early_done','提前完成'),('interrupted','临时中断'),('distracted','走神终止')]],
        'duration_bucket_distribution':buckets,'completion_funnel':[]}
    return EDAReportResponse(period_days=days,start_date=first,end_date=last,summary=summary,daily_points=daily,
        insights=[],recommendations=['如需探索适用条件和反例，可在学习画像中启用阶段性理解。'],
        profile=EDAProfile(profile_type=boundary,confidence=None,best_study_window='暂不推断',evidence=notes),
        chart_analysis=notes,charts=charts,markdown='\n'.join([f'# 学习记录报告（近 {days} 天）', boundary,
            '实际记录分钟：'+str(m['actual_minutes'] if m['actual_minutes'] is not None else '未知'), *notes]))
