"""用户画像聚合计算服务

从 pomodoro、learning_events、wrong_questions 等表聚合计算用户画像，
并将结果持久化到 user_profiles 表。
"""
from __future__ import annotations

import logging
from datetime import datetime, timedelta, date
from typing import Any, Optional

from sqlalchemy import select, func, and_
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.user_profile import UserProfile
from app.models.pomodoro import Pomodoro
from app.models.learning_event import LearningEvent
from app.models.question import WrongQuestion

logger = logging.getLogger(__name__)

# 近期窗口（天）
RECENT_DAYS = 30
# 最短数据量要求（番茄钟数）才生成画像
MIN_DATA_THRESHOLD = 3
# 最少需要的学习天数才生成有意义的画像
MIN_STUDY_DAYS = 7


async def compute_and_save_profile(db: AsyncSession, user_id: int) -> UserProfile:
    """聚合计算并持久化用户画像，返回最新画像对象。"""
    try:
        profile = await _compute_profile(db, user_id)
        await _upsert_profile(db, profile)
        logger.info("用户画像已更新 user_id=%s", user_id)
        return profile
    except Exception as exc:
        logger.warning("画像计算失败 user_id=%s: %s", user_id, exc)
        raise


async def get_profile(db: AsyncSession, user_id: int) -> Optional[UserProfile]:
    """获取用户画像（不触发重新计算）。"""
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    return result.scalar_one_or_none()


async def get_or_compute_profile(db: AsyncSession, user_id: int) -> Optional[UserProfile]:
    """获取画像；若不存在或超过 1 小时未更新则重新计算。"""
    result = await db.execute(
        select(UserProfile).where(UserProfile.user_id == user_id)
    )
    profile = result.scalar_one_or_none()

    should_recompute = (
        profile is None
        or profile.last_updated is None
        or (datetime.now() - profile.last_updated).total_seconds() > 3600
    )

    if should_recompute:
        try:
            profile = await compute_and_save_profile(db, user_id)
        except Exception:
            pass  # 计算失败时返回旧画像或 None

    return profile


def build_profile_prompt_snippet(profile: Optional[UserProfile]) -> str:
    """将用户画像序列化为可注入 system prompt 的文字片段。"""
    if profile is None:
        return ""

    lines = ["\n\n【用户学习画像（请据此给出个性化建议）】"]

    # 基础统计
    lines.append(f"- 累计学习天数：{profile.total_study_days} 天")
    lines.append(f"- 总学习时长：{profile.total_study_hours:.1f} 小时")
    lines.append(f"- 已完成番茄钟：{profile.total_pomodoros} 个")
    lines.append(f"- 日均番茄钟：{profile.avg_pomodoro_per_day:.1f} 个")
    lines.append(f"- 平均单次专注：{profile.avg_session_duration} 分钟")

    # 专注度
    lines.append(f"- 专注度评分：{profile.focus_score:.0f}/100")
    lines.append(f"- 坚持度评分：{profile.consistency_score:.0f}/100")

    # 连续天数
    streak = (profile.recent_performance or {}).get("streak", 0)
    if streak:
        lines.append(f"- 当前连续学习天数：{streak} 天")

    # 中断率
    interruption_rate = (profile.recent_performance or {}).get("interruption_rate", None)
    if interruption_rate is not None:
        lines.append(f"- 近期番茄中断率：{interruption_rate:.0%}")

    # 走神/分心统计
    perf = profile.recent_performance or {}
    distracted_rate = perf.get("distracted_rate", None)
    distracted_count = perf.get("distracted_count", 0)
    early_done_count = perf.get("early_done_count", 0)
    if distracted_rate is not None and distracted_rate > 0:
        lines.append(f"- 近期走神中断次数：{distracted_count} 次（占比 {distracted_rate:.0%}）")
        if distracted_rate >= 0.3:
            lines.append("  ⚠️ 该用户近期频繁走神，请在适当时机主动询问状态，提供专注力或情绪调节建议，不要说教")
    if early_done_count > 0:
        lines.append(f"- 近期提前完成次数：{early_done_count} 次（高效信号，可适当增加任务难度）")

    # 黄金时段
    _optimal = str(profile.optimal_hours) if profile.optimal_hours is not None else ""
    if _optimal:
        lines.append(f"- 黄金学习时段：{_optimal}")

    # 薄弱点
    weak = profile.weak_points
    if weak is not None and isinstance(weak, list) and len(weak) > 0:
        lines.append(f"- 薄弱知识点：{', '.join(str(w) for w in weak[:5])}")

    # 近期趋势（最近 7 天日均学习时长）
    perf = profile.recent_performance or {}
    daily_hours = perf.get("daily_hours", [])
    if daily_hours and len(daily_hours) >= 3:
        avg_recent = sum(daily_hours[-7:]) / len(daily_hours[-7:])
        lines.append(f"- 近 7 天日均学习：{avg_recent:.1f} 小时")

    lines.append(
        "请根据以上数据，在回答问题时适时给出针对性建议（如调整学习节奏、重点复习薄弱点等）。"
    )

    return "\n".join(lines)


# ──────────────────────────────────────────────
# 内部计算逻辑
# ──────────────────────────────────────────────

async def _compute_profile(db: AsyncSession, user_id: int) -> UserProfile:
    """从数据库聚合所有维度，返回未持久化的 UserProfile 对象。"""
    now = datetime.now()
    since = now - timedelta(days=RECENT_DAYS)

    # ── 番茄钟全量统计 ──
    all_pomodoros_result = await db.execute(
        select(Pomodoro).where(Pomodoro.user_id == user_id)
    )
    all_pomodoros = all_pomodoros_result.scalars().all()

    completed = [p for p in all_pomodoros if p.completed]
    cancelled = [p for p in all_pomodoros if not p.completed and p.ended_at is not None]

    total_pomodoros = len(completed)
    total_minutes = sum(p.duration for p in completed if p.duration)
    total_hours = total_minutes / 60.0

    # ── 日均番茄 ──
    study_dates: set[date] = set()
    for p in completed:
        ts = p.started_at or p.created_at
        if ts:
            study_dates.add(ts.date())
    total_study_days = len(study_dates)
    avg_pomodoro_per_day = total_pomodoros / total_study_days if total_study_days else 0.0

    # ── 平均单次专注时长 ──
    avg_session_duration = int(total_minutes / total_pomodoros) if total_pomodoros else 0

    # ── 专注度评分（完成率，0-100）──
    total_attempts = len(all_pomodoros)
    completion_rate = total_pomodoros / total_attempts if total_attempts else 0.0
    focus_score = round(completion_rate * 100, 1)

    # ── 中断率（近30天）──
    recent_pomodoros = [p for p in all_pomodoros if (p.started_at or p.created_at) and (p.started_at or p.created_at) >= since]
    recent_completed = [p for p in recent_pomodoros if p.completed]
    recent_cancelled = [p for p in recent_pomodoros if not p.completed and p.ended_at is not None]
    interruption_rate = len(recent_cancelled) / len(recent_pomodoros) if recent_pomodoros else 0.0

    # ── 连续学习天数（streak）──
    streak = _compute_streak(study_dates)

    # ── 坚持度评分（streak 归一化，满 30 天满分）──
    consistency_score = min(streak / 30.0 * 100, 100.0)

    # ── 黄金时段（按小时段统计完成数，取 top 2 小时）──
    optimal_hours = _compute_optimal_hours(completed)

    # ── 偏好时段分布 ──
    preferred_time_slots = _compute_time_slot_distribution(completed)

    # ── 近期每日学习时长（最近 30 天，用于趋势图）──
    daily_hours_list, dates_list = _compute_daily_hours(completed, since, now)

    # ── 薄弱知识点（来自 wrong_questions）──
    weak_points = await _compute_weak_points(db, user_id)

    # ── stop_reason 统计（近30天）──
    distracted_count = sum(1 for p in recent_pomodoros if getattr(p, 'stop_reason', None) == 'distracted')
    early_done_count = sum(1 for p in recent_pomodoros if getattr(p, 'stop_reason', None) == 'early_done')
    interrupted_count = sum(1 for p in recent_pomodoros if getattr(p, 'stop_reason', None) == 'interrupted')
    distracted_rate = distracted_count / len(recent_pomodoros) if recent_pomodoros else 0.0

    # ── 组装 recent_performance ──
    recent_performance = {
        "streak": streak,
        "interruption_rate": round(interruption_rate, 4),
        "daily_hours": daily_hours_list,
        "dates": dates_list,
        "completion_rate_30d": round(
            len(recent_completed) / len(recent_pomodoros) if recent_pomodoros else 0.0, 4
        ),
        "distracted_count": distracted_count,
        "early_done_count": early_done_count,
        "interrupted_count": interrupted_count,
        "distracted_rate": round(distracted_rate, 4),
        "data_insufficient": total_study_days < MIN_STUDY_DAYS,
        "data_days": total_study_days,
        "insights": _generate_insights(
            total_study_days=total_study_days,
            optimal_hours=optimal_hours,
            preferred_time_slots=preferred_time_slots,
            focus_score=focus_score,
            consistency_score=consistency_score,
            interruption_rate=interruption_rate,
            distracted_rate=distracted_rate,
            distracted_count=distracted_count,
            avg_session_duration=avg_session_duration,
            streak=streak,
            total_pomodoros=total_pomodoros,
            completion_rate=completion_rate,
        ),
    }

    profile = UserProfile(
        user_id=user_id,
        total_study_hours=round(total_hours, 2),
        total_study_days=total_study_days,
        total_pomodoros=total_pomodoros,
        avg_session_duration=avg_session_duration,
        avg_pomodoro_per_day=round(avg_pomodoro_per_day, 2),
        focus_score=focus_score,
        consistency_score=round(consistency_score, 1),
        self_control_score=focus_score,  # 暂时与 focus 一致，后续可细化
        planning_score=50.0,  # 目标模块打通后再计算
        preferred_time_slots=preferred_time_slots,
        optimal_hours=optimal_hours,
        weak_points=weak_points,
        recent_performance=recent_performance,
        last_updated=datetime.now(),
    )
    return profile


async def _upsert_profile(db: AsyncSession, profile: UserProfile) -> None:
    """INSERT OR REPLACE user_profiles 行（SQLite upsert）。"""
    existing = await db.execute(
        select(UserProfile).where(UserProfile.user_id == profile.user_id)
    )
    row = existing.scalar_one_or_none()
    if row is None:
        db.add(profile)
    else:
        row.total_study_hours = profile.total_study_hours
        row.total_study_days = profile.total_study_days
        row.total_pomodoros = profile.total_pomodoros
        row.avg_session_duration = profile.avg_session_duration
        row.avg_pomodoro_per_day = profile.avg_pomodoro_per_day
        row.focus_score = profile.focus_score
        row.consistency_score = profile.consistency_score
        row.self_control_score = profile.self_control_score
        row.planning_score = profile.planning_score
        row.preferred_time_slots = profile.preferred_time_slots
        row.optimal_hours = profile.optimal_hours
        row.weak_points = profile.weak_points
        row.recent_performance = profile.recent_performance
        row.last_updated = profile.last_updated
    await db.commit()


def _compute_streak(study_dates: set[date]) -> int:
    """计算截至今天的连续学习天数。"""
    if not study_dates:
        return 0
    today = date.today()
    streak = 0
    cursor = today
    while cursor in study_dates:
        streak += 1
        cursor -= timedelta(days=1)
    return streak


def _compute_optimal_hours(completed_pomodoros: list[Any]) -> str:
    """统计各小时完成的番茄数，返回 top 2 连续小时区间，如 '21:00-23:00'。"""
    if not completed_pomodoros:
        return ""
    hour_count: dict[int, int] = {}
    for p in completed_pomodoros:
        ts = p.started_at or p.created_at
        if ts:
            h = ts.hour
            hour_count[h] = hour_count.get(h, 0) + 1
    if not hour_count:
        return ""
    best_hour = max(hour_count, key=lambda h: hour_count[h])
    return f"{best_hour:02d}:00-{(best_hour + 2) % 24:02d}:00"


def _compute_time_slot_distribution(completed_pomodoros: list[Any]) -> dict[str, float]:
    """计算早/午/晚/深夜四个时段的学习占比。"""
    slots = {"morning": 0, "afternoon": 0, "evening": 0, "night": 0}
    for p in completed_pomodoros:
        ts = p.started_at or p.created_at
        if not ts:
            continue
        h = ts.hour
        if 6 <= h < 12:
            slots["morning"] += 1
        elif 12 <= h < 18:
            slots["afternoon"] += 1
        elif 18 <= h < 23:
            slots["evening"] += 1
        else:
            slots["night"] += 1
    total = sum(slots.values()) or 1
    return {k: round(v / total, 4) for k, v in slots.items()}


def _compute_daily_hours(
    completed_pomodoros: list[Any],
    since: datetime,
    now: datetime,
) -> tuple[list[float], list[str]]:
    """返回 since..now 窗口内每天的学习小时数列表和对应日期字符串列表。"""
    daily: dict[date, float] = {}
    for p in completed_pomodoros:
        ts = p.started_at or p.created_at
        if ts and ts >= since:
            d = ts.date()
            daily[d] = daily.get(d, 0.0) + (p.duration or 0) / 60.0

    # 生成连续日期序列
    num_days = (now.date() - since.date()).days + 1
    dates_list = []
    hours_list = []
    for i in range(num_days):
        d = since.date() + timedelta(days=i)
        dates_list.append(d.isoformat())
        hours_list.append(round(daily.get(d, 0.0), 2))
    return hours_list, dates_list


async def _compute_weak_points(db: AsyncSession, user_id: int) -> list[str]:
    """从 wrong_questions 表汇总薄弱知识点（按错误次数降序，取 top 10）。"""
    try:
        result = await db.execute(
            select(
                WrongQuestion.knowledge_point,
                func.count(WrongQuestion.id).label("cnt"),
            )
            .where(
                WrongQuestion.user_id == user_id,
                WrongQuestion.knowledge_point.isnot(None),
            )
            .group_by(WrongQuestion.knowledge_point)
            .order_by(func.count(WrongQuestion.id).desc())
            .limit(10)
        )
        rows = result.all()
        return [str(row.knowledge_point) for row in rows if row.knowledge_point is not None]
    except Exception:
        return []


def _generate_insights(
    total_study_days: int,
    optimal_hours: Optional[str],
    preferred_time_slots: Optional[dict],
    focus_score: float,
    consistency_score: float,
    interruption_rate: float,
    distracted_rate: float,
    distracted_count: int,
    avg_session_duration: int,
    streak: int,
    total_pomodoros: int,
    completion_rate: float,
) -> list[str]:
    """根据统计数据生成叙述性分析洞察结论列表。"""
    insights: list[str] = []

    if total_study_days < MIN_STUDY_DAYS:
        insights.append(f"当前仅有 {total_study_days} 天的学习记录，需要至少 {MIN_STUDY_DAYS} 天数据才能生成准确的分析报告。")
        return insights

    # 1. 高效时段洞察
    if optimal_hours:
        insights.append(
            f"基于 {total_study_days} 天的学习数据分析，你在 {optimal_hours} 完成的番茄钟数量最多、专注时间最长，"
            f"这是你的黄金学习时段，建议将高难度任务安排在这个时间段。"
        )

    # 2. 专注度洞察
    if focus_score >= 80:
        insights.append(
            f"你的番茄钟完成率达到 {focus_score:.0f}%，专注度表现优秀，"
            f"说明你在启动学习任务后能有效保持专注，很少被打断。"
        )
    elif focus_score >= 60:
        insights.append(
            f"你的番茄钟完成率为 {focus_score:.0f}%，专注度中等。"
            f"有约 {100 - focus_score:.0f}% 的学习计划未能完整执行，建议减少外部干扰。"
        )
    else:
        insights.append(
            f"你的番茄钟完成率仅为 {focus_score:.0f}%，有较多中断情况。"
            f"建议检查学习环境或将番茄钟时长调短，从 15 分钟开始建立专注习惯。"
        )

    # 3. 走神/中断洞察
    if distracted_rate > 0.2:
        insights.append(
            f"近30天内有 {distracted_count} 次番茄钟因走神或状态不好而中断（占 {distracted_rate * 100:.0f}%），"
            f"建议在容易分心的时间段降低任务难度，或增加休息频率。"
        )
    elif distracted_count > 0:
        insights.append(
            f"近30天偶发 {distracted_count} 次走神中断，整体自控力良好。"
        )

    # 4. 坚持度洞察
    if streak >= 14:
        insights.append(
            f"你已连续学习 {streak} 天，坚持度表现出色！保持这个节奏，学习效果会持续累积。"
        )
    elif streak >= 7:
        insights.append(
            f"你已连续学习 {streak} 天，坚持度良好。继续保持，争取突破 14 天连续打卡。"
        )
    elif consistency_score < 40:
        insights.append(
            f"学习连续性偏低（当前连续 {streak} 天），学习记录较分散。"
            f"建议固定每天至少完成 1 个番茄钟，养成学习惯性。"
        )

    # 5. 平均专注时长洞察
    if avg_session_duration > 0:
        if avg_session_duration >= 45:
            insights.append(
                f"你的平均单次专注时长为 {avg_session_duration} 分钟，属于深度学习型，"
                f"适合处理需要长时间投入的复杂任务。"
            )
        elif avg_session_duration <= 20:
            insights.append(
                f"你的平均单次专注时长为 {avg_session_duration} 分钟，倾向于短周期学习。"
                f"可以尝试逐渐延长到 25-30 分钟，提升单次学习深度。"
            )

    return insights
