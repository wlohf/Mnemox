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

router = APIRouter()


# ════════════════════════════════════════════
# Schemas
# ════════════════════════════════════════════

class TrendPoint(BaseModel):
    date: str
    study_minutes: float
    pomodoro_count: int
    completed_count: int
    completion_rate: float


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
    completion_rate: float
    avg_duration: float
    early_done_count: int
    efficiency_score: float


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
    now = datetime.now()
    end_date = now.date()

    if period == "custom":
        if not start or not end:
            raise HTTPException(status_code=400, detail="自定义时间段需提供 start 和 end 参数")
        try:
            start_date = date.fromisoformat(start)
            end_date = date.fromisoformat(end)
        except ValueError:
            raise HTTPException(status_code=400, detail="日期格式错误，请使用 YYYY-MM-DD")
        if start_date > end_date:
            raise HTTPException(status_code=400, detail="开始日期不能晚于结束日期")
    else:
        days_map = {"7d": 7, "30d": 30, "90d": 90, "365d": 365}
        days = days_map.get(period)
        if days is None:
            raise HTTPException(status_code=400, detail="period 可选值: 7d / 30d / 90d / 365d / custom")
        start_date = end_date - timedelta(days=days - 1)

    # 查询时间范围内的番茄钟
    since_dt = datetime.combine(start_date, datetime.min.time())
    until_dt = datetime.combine(end_date, datetime.max.time())

    result = await db.execute(
        select(Pomodoro).where(
            Pomodoro.user_id == current_user.id,
            Pomodoro.created_at >= since_dt,
            Pomodoro.created_at <= until_dt,
        )
    )
    pomodoros = result.scalars().all()

    # 用 pandas 聚合每日数据
    if pomodoros:
        records = []
        for p in pomodoros:
            ts = p.started_at or p.created_at
            records.append({
                "date": ts.date() if ts else None,
                "duration": float(p.duration) if p.duration else 0.0,
                "completed": bool(p.completed),
            })
        df = pd.DataFrame(records).dropna(subset=["date"])
        daily = df.groupby("date").agg(
            study_minutes=("duration", "sum"),
            pomodoro_count=("duration", "count"),
            completed_count=("completed", "sum"),
        ).reset_index()
        daily["completion_rate"] = np.where(
            daily["pomodoro_count"] > 0,
            (daily["completed_count"] / daily["pomodoro_count"] * 100).round(1),
            0.0,
        )
        daily_dict = {row["date"]: row for _, row in daily.iterrows()}
    else:
        daily_dict = {}

    # 生成连续日期序列，填充空白天
    num_days = (end_date - start_date).days + 1
    points: List[TrendPoint] = []
    total_minutes = 0.0
    total_pomodoros = 0
    total_completed = 0

    for i in range(num_days):
        d = start_date + timedelta(days=i)
        row = daily_dict.get(d)
        if row is not None:
            mins = float(row["study_minutes"])
            cnt = int(row["pomodoro_count"])
            comp = int(row["completed_count"])
            rate = float(row["completion_rate"])
        else:
            mins, cnt, comp, rate = 0.0, 0, 0, 0.0

        total_minutes += mins
        total_pomodoros += cnt
        total_completed += comp

        points.append(TrendPoint(
            date=d.isoformat(),
            study_minutes=round(mins, 1),
            pomodoro_count=cnt,
            completed_count=comp,
            completion_rate=rate,
        ))

    active_days = sum(1 for p in points if p.pomodoro_count > 0)
    avg_daily = round(total_minutes / num_days, 1) if num_days > 0 else 0.0

    summary = {
        "total_study_hours": round(total_minutes / 60, 2),
        "total_pomodoros": total_pomodoros,
        "total_completed": total_completed,
        "overall_completion_rate": round(total_completed / total_pomodoros * 100, 1) if total_pomodoros > 0 else 0.0,
        "active_days": active_days,
        "total_days": num_days,
        "avg_daily_minutes": avg_daily,
    }

    return TrendResponse(
        period=period,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        points=points,
        summary=summary,
    )


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
    """
    分析不同时段的学习效率。

    效率指标：该时段内番茄钟完成率 + 提前完成占比。
    使用 scipy 计算时段与效率得分的 Spearman 相关性。
    """
    since = datetime.now() - timedelta(days=days)

    result = await db.execute(
        select(Pomodoro).where(
            Pomodoro.user_id == current_user.id,
            Pomodoro.created_at >= since,
        )
    )
    pomodoros = result.scalars().all()

    if len(pomodoros) < 5:
        return EfficiencyResponse(
            slots=[],
            correlation={"method": "spearman", "coefficient": None, "p_value": None},
            best_slot=None,
            insight="数据不足（至少需要 5 个番茄钟），暂无法分析时段效率。",
        )

    # 构建 DataFrame
    records = []
    for p in pomodoros:
        ts = p.started_at or p.created_at
        if not ts:
            continue
        records.append({
            "hour": ts.hour,
            "slot": _hour_to_slot(ts.hour),
            "duration": float(p.duration) if p.duration else 0.0,
            "completed": bool(p.completed),
            "stop_reason": p.stop_reason,
        })

    df = pd.DataFrame(records)
    df["early_done"] = df["stop_reason"] == "early_done"

    # 按时段聚合
    slot_agg = df.groupby("slot").agg(
        pomodoro_count=("completed", "count"),
        completed_count=("completed", "sum"),
        avg_duration=("duration", "mean"),
        early_done_count=("early_done", "sum"),
    ).reset_index()

    slot_agg["completion_rate"] = np.where(
        slot_agg["pomodoro_count"] > 0,
        (slot_agg["completed_count"] / slot_agg["pomodoro_count"] * 100).round(1),
        0.0,
    )
    # 效率得分 = 完成率 × 0.7 + 提前完成占比 × 0.3（归一化到 0-100）
    slot_agg["early_rate"] = np.where(
        slot_agg["pomodoro_count"] > 0,
        slot_agg["early_done_count"] / slot_agg["pomodoro_count"] * 100,
        0.0,
    )
    slot_agg["efficiency_score"] = (
        slot_agg["completion_rate"] * 0.7 + slot_agg["early_rate"] * 0.3
    ).round(1)

    # 构建返回数据
    slot_order = ["morning", "afternoon", "evening", "night"]
    slots_out: List[SlotEfficiency] = []
    scores_for_corr: List[float] = []
    indices_for_corr: List[int] = []

    for idx, slot_name in enumerate(slot_order):
        row = slot_agg[slot_agg["slot"] == slot_name]
        if row.empty:
            slots_out.append(SlotEfficiency(
                slot=slot_name,
                slot_label=_SLOT_RANGES[slot_name][2],
                pomodoro_count=0, completed_count=0,
                completion_rate=0.0, avg_duration=0.0,
                early_done_count=0, efficiency_score=0.0,
            ))
        else:
            r = row.iloc[0]
            eff = SlotEfficiency(
                slot=slot_name,
                slot_label=_SLOT_RANGES[slot_name][2],
                pomodoro_count=int(r["pomodoro_count"]),
                completed_count=int(r["completed_count"]),
                completion_rate=float(r["completion_rate"]),
                avg_duration=round(float(r["avg_duration"]), 1),
                early_done_count=int(r["early_done_count"]),
                efficiency_score=float(r["efficiency_score"]),
            )
            slots_out.append(eff)
            if eff.pomodoro_count >= 2:
                scores_for_corr.append(eff.efficiency_score)
                indices_for_corr.append(idx)

    # Spearman 相关性（时段序号 vs 效率得分）
    corr_result: dict = {"method": "spearman", "coefficient": None, "p_value": None}
    if len(scores_for_corr) >= 3:
        coef, pval = sp_stats.spearmanr(indices_for_corr, scores_for_corr)
        corr_result["coefficient"] = round(float(coef), 4) if not np.isnan(coef) else None
        corr_result["p_value"] = round(float(pval), 4) if not np.isnan(pval) else None

    # 找最佳时段
    valid_slots = [s for s in slots_out if s.pomodoro_count >= 2]
    best_slot = max(valid_slots, key=lambda s: s.efficiency_score).slot if valid_slots else None
    best_label = _SLOT_RANGES[best_slot][2] if best_slot else "未知"

    # 生成洞察
    if best_slot:
        best_obj = next(s for s in slots_out if s.slot == best_slot)
        insight = (
            f"你在「{best_label}」时段效率最高（得分 {best_obj.efficiency_score}），"
            f"完成率 {best_obj.completion_rate}%，"
            f"建议将重要学习任务安排在此时段。"
        )
    else:
        insight = "数据量不足，暂无法判断最佳学习时段。"

    return EfficiencyResponse(
        slots=slots_out,
        correlation=corr_result,
        best_slot=best_slot,
        insight=insight,
    )


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
    confidence: float
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
    """生成用户可读的学习行为 EDA 报告。"""
    end_date = datetime.now().date()
    start_date = end_date - timedelta(days=days - 1)

    since_dt = datetime.combine(start_date, datetime.min.time())
    until_dt = datetime.combine(end_date, datetime.max.time())

    p_result = await db.execute(
        select(Pomodoro).where(
            Pomodoro.user_id == current_user.id,
            Pomodoro.created_at >= since_dt,
            Pomodoro.created_at <= until_dt,
        )
    )
    pomodoros = p_result.scalars().all()

    if pomodoros:
        records = []
        for p in pomodoros:
            ts = p.started_at or p.created_at
            if ts is None:
                continue
            records.append({
                "date": ts.date(),
                "hour": int(ts.hour),
                "duration": float(p.duration or 0.0),
                "completed": 1 if p.completed else 0,
                "stop_reason": (p.stop_reason or "none"),
            })
        pdf = pd.DataFrame(records)
    else:
        pdf = pd.DataFrame(columns=["date", "hour", "duration", "completed", "stop_reason"])

    t_result = await db.execute(
        select(Task, Goal)
        .join(Goal, Task.goal_id == Goal.id)
        .where(
            Goal.user_id == current_user.id,
            Task.planned_date >= start_date,
            Task.planned_date <= end_date,
        )
    )
    task_rows = t_result.all()

    total_tasks = len(task_rows)
    completed_tasks = sum(1 for row in task_rows if getattr(row[0], "status", "") == "completed")
    pending_tasks = max(0, total_tasks - completed_tasks)

    wq_result = await db.execute(
        select(WrongQuestion).where(WrongQuestion.user_id == current_user.id)
    )
    wrong_questions = wq_result.scalars().all()

    all_dates = [start_date + timedelta(days=i) for i in range(days)]
    date_lookup = {d.isoformat(): d for d in all_dates}

    daily_points: List[dict] = []
    daily_df = pd.DataFrame(columns=["date", "study_minutes", "pomodoro_count", "completion_rate"])  # for rolling/calc
    if not pdf.empty:
        daily_df = pdf.groupby("date").agg(
            study_minutes=("duration", "sum"),
            pomodoro_count=("duration", "count"),
            completion_rate=("completed", "mean"),
        ).reset_index()

    daily_map = {
        row["date"].isoformat(): {
            "study_minutes": float(row["study_minutes"]),
            "pomodoro_count": int(row["pomodoro_count"]),
            "completion_rate": float(row["completion_rate"]),
        }
        for _, row in daily_df.iterrows()
    }

    rolling_minutes_source: List[float] = []
    for d in all_dates:
        key = d.isoformat()
        cell = daily_map.get(key, {"study_minutes": 0.0, "pomodoro_count": 0, "completion_rate": 0.0})
        rolling_minutes_source.append(float(cell["study_minutes"]))
        daily_points.append({
            "date": key,
            "study_minutes": round(float(cell["study_minutes"]), 1),
            "pomodoro_count": int(cell["pomodoro_count"]),
            "completion_rate": round(float(cell["completion_rate"]) * 100, 1),
        })

    rolling7: List[float] = []
    for i in range(len(rolling_minutes_source)):
        left = max(0, i - 6)
        window = rolling_minutes_source[left:i + 1]
        rolling7.append(round(float(sum(window) / max(1, len(window))), 1))

    for i, point in enumerate(daily_points):
        point["rolling7_minutes"] = rolling7[i]

    total_minutes = float(pdf["duration"].sum()) if not pdf.empty else 0.0
    pomodoro_count = int(len(pdf))
    completion_rate = float(pdf["completed"].mean()) if not pdf.empty else 0.0
    active_days = int(pdf["date"].nunique()) if not pdf.empty else 0
    avg_daily_minutes = round(total_minutes / days, 1)

    peak_hour = None
    if not pdf.empty:
        peak_hour = int(pdf.groupby("hour")["completed"].mean().idxmax())

    stop_reason_counts = {
        "early_done": 0,
        "interrupted": 0,
        "distracted": 0,
    }
    if not pdf.empty:
        for key in stop_reason_counts.keys():
            stop_reason_counts[key] = int((pdf["stop_reason"] == key).sum())

    # 每小时分布（0-23）
    hourly_distribution: List[dict] = []
    for hour in range(24):
        if not pdf.empty:
            slot = pdf[pdf["hour"] == hour]
            slot_sessions = int(len(slot))
            slot_minutes = float(slot["duration"].sum()) if slot_sessions else 0.0
            slot_completion = float(slot["completed"].mean()) if slot_sessions else 0.0
            slot_avg_duration = float(slot["duration"].mean()) if slot_sessions else 0.0
        else:
            slot_sessions = 0
            slot_minutes = 0.0
            slot_completion = 0.0
            slot_avg_duration = 0.0
        hourly_distribution.append({
            "hour": hour,
            "sessions": slot_sessions,
            "minutes": round(slot_minutes, 1),
            "completion_rate": round(slot_completion * 100, 1),
            "avg_duration": round(slot_avg_duration, 1),
        })

    # 每周分布（周一到周日）
    weekday_labels = ["周一", "周二", "周三", "周四", "周五", "周六", "周日"]
    weekday_distribution: List[dict] = []
    for wd in range(7):
        if not pdf.empty:
            day_part = pdf[pdf["date"].apply(lambda x: x.weekday()) == wd]
            day_sessions = int(len(day_part))
            day_minutes = float(day_part["duration"].sum()) if day_sessions else 0.0
            day_completion = float(day_part["completed"].mean()) if day_sessions else 0.0
        else:
            day_sessions = 0
            day_minutes = 0.0
            day_completion = 0.0
        weekday_distribution.append({
            "weekday": wd,
            "label": weekday_labels[wd],
            "sessions": day_sessions,
            "minutes": round(day_minutes, 1),
            "completion_rate": round(day_completion * 100, 1),
        })

    # 小时-周几热力图
    heatmap_points: List[List[float]] = []
    if not pdf.empty:
        for wd in range(7):
            wd_part = pdf[pdf["date"].apply(lambda x: x.weekday()) == wd]
            for hour in range(24):
                hh = wd_part[wd_part["hour"] == hour]
                heatmap_points.append([hour, wd, round(float(hh["duration"].sum()) if len(hh) else 0.0, 1)])
    else:
        for wd in range(7):
            for hour in range(24):
                heatmap_points.append([hour, wd, 0.0])

    # 时长分桶
    duration_bucket_distribution = [
        {"bucket": "<20m", "count": 0},
        {"bucket": "20-29m", "count": 0},
        {"bucket": "30-44m", "count": 0},
        {"bucket": "45m+", "count": 0},
    ]
    if not pdf.empty:
        duration_bucket_distribution[0]["count"] = int((pdf["duration"] < 20).sum())
        duration_bucket_distribution[1]["count"] = int(((pdf["duration"] >= 20) & (pdf["duration"] < 30)).sum())
        duration_bucket_distribution[2]["count"] = int(((pdf["duration"] >= 30) & (pdf["duration"] < 45)).sum())
        duration_bucket_distribution[3]["count"] = int((pdf["duration"] >= 45).sum())

    stop_reason_distribution = [
        {"reason": "正常完成", "key": "early_done", "count": stop_reason_counts["early_done"]},
        {"reason": "临时中断", "key": "interrupted", "count": stop_reason_counts["interrupted"]},
        {"reason": "走神分心", "key": "distracted", "count": stop_reason_counts["distracted"]},
    ]

    weak_points_top = sorted(
        [
            {
                "knowledge_point": (wq.knowledge_point or "未标注"),
                "wrong_count": int(wq.wrong_count or 0),
                "mastery_status": (wq.mastery_status or "not_mastered"),
            }
            for wq in wrong_questions
        ],
        key=lambda x: x["wrong_count"],
        reverse=True,
    )[:5]

    insights: List[EDAInsight] = []
    if avg_daily_minutes < 45:
        insights.append(EDAInsight(
            title="学习时长偏低",
            detail=f"近 {days} 天日均仅 {avg_daily_minutes} 分钟，建议设定最小 25 分钟底线。",
            severity="high",
        ))
    if completion_rate < 0.6 and pomodoro_count > 0:
        insights.append(EDAInsight(
            title="专注完成率偏低",
            detail=f"番茄钟完成率仅 {completion_rate * 100:.1f}%，中断可能影响学习连贯性。",
            severity="medium",
        ))
    if pending_tasks >= 8:
        insights.append(EDAInsight(
            title="任务积压明显",
            detail=f"当前周期内待完成任务 {pending_tasks} 个，建议做一次任务减负与重排。",
            severity="high",
        ))
    if peak_hour is not None:
        insights.append(EDAInsight(
            title="高效时段识别",
            detail=f"你的高效时段集中在 {peak_hour}:00 左右，建议将高认知任务放到该时间段。",
            severity="info",
        ))

    # 用户画像类型判断
    morning_minutes = sum(item["minutes"] for item in hourly_distribution if 5 <= item["hour"] <= 11)
    day_minutes = sum(item["minutes"] for item in hourly_distribution if 12 <= item["hour"] <= 18)
    night_minutes = sum(item["minutes"] for item in hourly_distribution if item["hour"] >= 20 or item["hour"] <= 1)
    minute_total_safe = max(1.0, total_minutes)

    morning_ratio = morning_minutes / minute_total_safe
    day_ratio = day_minutes / minute_total_safe
    night_ratio = night_minutes / minute_total_safe
    active_ratio = active_days / max(1, days)

    profile_type = "均衡成长型"
    confidence = 0.62
    profile_evidence: List[str] = []
    if night_ratio >= 0.45 and peak_hour is not None and (peak_hour >= 20 or peak_hour <= 1):
        profile_type = "夜间高效型"
        confidence = min(0.96, 0.66 + night_ratio)
        profile_evidence.append(f"夜间学习时长占比 {night_ratio * 100:.1f}%")
        profile_evidence.append(f"峰值效率时段在 {peak_hour}:00")
    elif morning_ratio >= 0.45 and peak_hour is not None and 6 <= peak_hour <= 11:
        profile_type = "晨间冲刺型"
        confidence = min(0.96, 0.66 + morning_ratio)
        profile_evidence.append(f"上午学习时长占比 {morning_ratio * 100:.1f}%")
        profile_evidence.append(f"峰值效率时段在 {peak_hour}:00")
    elif day_ratio >= 0.5 and peak_hour is not None and 12 <= peak_hour <= 18:
        profile_type = "白天稳态型"
        confidence = min(0.94, 0.64 + day_ratio)
        profile_evidence.append(f"白天学习时长占比 {day_ratio * 100:.1f}%")
        profile_evidence.append(f"峰值效率时段在 {peak_hour}:00")
    elif active_ratio < 0.45:
        profile_type = "间歇突击型"
        confidence = min(0.92, 0.55 + (1 - active_ratio))
        profile_evidence.append(f"活跃学习天数占比仅 {active_ratio * 100:.1f}%")
        profile_evidence.append("学习节奏呈现较明显波动")
    elif completion_rate >= 0.8 and avg_daily_minutes >= 90:
        profile_type = "高强度稳定型"
        confidence = 0.9
        profile_evidence.append(f"完成率 {completion_rate * 100:.1f}% 且日均学习 {avg_daily_minutes} 分钟")

    best_study_window = f"{peak_hour}:00-{(peak_hour + 1) % 24}:00" if peak_hour is not None else "暂无明显峰值"
    if not profile_evidence:
        profile_evidence.append("学习行为在多个时段分布较均衡")

    recommendations = [
        "每日先完成 1 个最小任务，再处理复习，降低启动阻力。",
        "将高难度任务安排到个人高效时段，低能量时段做整理类任务。",
        "每晚进行 3 分钟复盘：完成了什么、明天第一步做什么。",
    ]
    if stop_reason_counts["distracted"] > stop_reason_counts["early_done"]:
        recommendations.append("走神次数偏高，建议缩短单次专注时长到 20-25 分钟并增加短休息。")

    if profile_type == "夜间高效型":
        recommendations.append("把最难任务固定在 21:00 左右，白天只做轻任务和复习。")
    elif profile_type == "晨间冲刺型":
        recommendations.append("在 9:00-11:00 放置核心任务，下午安排复盘与错题整理。")
    elif profile_type == "白天稳态型":
        recommendations.append("保持午后主学习段，晚上只做回顾，避免额外认知负担。")
    elif profile_type == "间歇突击型":
        recommendations.append("先把目标改为“每周稳定 4 天”，再逐步加时长，优先保证节奏连续。")
    elif profile_type == "高强度稳定型":
        recommendations.append("增加每周一次深度复盘，避免高强度下的策略性疲劳。")

    chart_analysis = [
        f"趋势图显示近 {days} 天累计 {round(total_minutes, 1)} 分钟，日均 {avg_daily_minutes} 分钟。",
        f"7 日滚动均值可用于判断节奏是否稳定，当前活跃天数为 {active_days} 天。",
        f"时段分布中峰值窗口为 {best_study_window}，更适合放高认知任务。",
        f"周内分布帮助识别“周中高效”还是“周末补偿”，可据此安排计划密度。",
        f"停止原因中走神 {stop_reason_counts['distracted']} 次、中断 {stop_reason_counts['interrupted']} 次，可作为抗干扰优化指标。",
        "时长分桶可判断你更适合短冲刺还是长专注，并用于设置个性化番茄时长。",
    ]

    summary = {
        "total_minutes": round(total_minutes, 1),
        "avg_daily_minutes": avg_daily_minutes,
        "pomodoro_count": pomodoro_count,
        "completion_rate": round(completion_rate * 100, 1),
        "active_days": active_days,
        "total_tasks": total_tasks,
        "completed_tasks": completed_tasks,
        "pending_tasks": pending_tasks,
        "peak_hour": peak_hour,
        "best_study_window": best_study_window,
        "profile_type": profile_type,
        "profile_confidence": round(confidence, 3),
        "morning_ratio": round(morning_ratio, 3),
        "day_ratio": round(day_ratio, 3),
        "night_ratio": round(night_ratio, 3),
        "stop_reason_counts": stop_reason_counts,
        "weak_points_top": weak_points_top,
    }

    charts = {
        "daily_trend": daily_points,
        "hourly_distribution": hourly_distribution,
        "weekday_distribution": weekday_distribution,
        "hour_week_heatmap": {
            "hours": list(range(24)),
            "weekdays": weekday_labels,
            "points": heatmap_points,
        },
        "stop_reason_distribution": stop_reason_distribution,
        "duration_bucket_distribution": duration_bucket_distribution,
        "completion_funnel": [
            {"stage": "开始专注", "value": pomodoro_count},
            {"stage": "正常完成", "value": stop_reason_counts["early_done"]},
            {"stage": "临时中断", "value": stop_reason_counts["interrupted"]},
            {"stage": "走神终止", "value": stop_reason_counts["distracted"]},
        ],
    }

    markdown_lines = [
        f"# 学习行为 EDA 报告（近 {days} 天）",
        "",
        f"- 区间：{start_date.isoformat()} ~ {end_date.isoformat()}",
        f"- 总学习时长：{summary['total_minutes']} 分钟",
        f"- 日均学习时长：{summary['avg_daily_minutes']} 分钟",
        f"- 番茄钟完成率：{summary['completion_rate']}%",
        f"- 任务完成：{completed_tasks}/{total_tasks}",
        f"- 学习画像：{profile_type}（置信度 {round(confidence * 100, 1)}%）",
        f"- 最佳学习窗口：{best_study_window}",
        "",
        "## 关键洞察",
    ]
    if insights:
        markdown_lines.extend([f"- **{item.title}**：{item.detail}" for item in insights])
    else:
        markdown_lines.append("- 当前阶段数据整体平稳，暂无显著异常。")
    markdown_lines.extend([
        "",
        "## 图表解读",
    ])
    markdown_lines.extend([f"- {line}" for line in chart_analysis])
    markdown_lines.extend([
        "",
        "## 建议动作",
    ])
    markdown_lines.extend([f"- {rec}" for rec in recommendations])

    return EDAReportResponse(
        period_days=days,
        start_date=start_date.isoformat(),
        end_date=end_date.isoformat(),
        summary=summary,
        daily_points=daily_points,
        insights=insights,
        recommendations=recommendations,
        profile=EDAProfile(
            profile_type=profile_type,
            confidence=round(confidence, 3),
            best_study_window=best_study_window,
            evidence=profile_evidence,
        ),
        chart_analysis=chart_analysis,
        charts=charts,
        markdown="\n".join(markdown_lines),
    )
