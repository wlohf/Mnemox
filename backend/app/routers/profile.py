"""用户学习画像路由"""
from fastapi import APIRouter, Depends
from sqlalchemy.ext.asyncio import AsyncSession
from pydantic import BaseModel
from typing import Optional, Any

from ..database import get_db
from ..auth import get_current_user
from ..models.user import User
from app.services.profile_service import (
    get_or_compute_profile,
    compute_and_save_profile,
)

router = APIRouter()


# ── helpers ──────────────────────────────────────────────────────────────────

def _f(val: Any, default: float = 0.0) -> float:
    if val is None:
        return default
    return float(val)  # type: ignore[arg-type]


def _i(val: Any, default: int = 0) -> int:
    if val is None:
        return default
    return int(val)  # type: ignore[arg-type]


def _s(val: Any) -> Optional[str]:
    if val is None:
        return None
    return str(val)


# ── schema ────────────────────────────────────────────────────────────────────

class ProfileResponse(BaseModel):
    """用户画像响应"""
    user_id: int
    total_study_hours: float
    total_study_days: int
    total_pomodoros: int
    avg_session_duration: int
    avg_pomodoro_per_day: float
    optimal_hours: Optional[str]
    preferred_time_slots: Optional[Any]
    self_control_score: float
    consistency_score: float
    focus_score: float
    planning_score: float
    streak_days: int
    weak_points: Optional[Any]
    recent_performance: Optional[Any]
    last_updated: Optional[str]
    data_insufficient: bool = False
    insights: list[str] = []

    model_config = {"from_attributes": True}


def _build_response(uid: int, profile: Any) -> ProfileResponse:
    lu = profile.last_updated
    last_updated: Optional[str] = lu.isoformat() if lu is not None else None  # type: ignore[union-attr]
    perf: dict[str, Any] = profile.recent_performance or {}
    return ProfileResponse(
        user_id=uid,
        total_study_hours=_f(profile.total_study_hours),
        total_study_days=_i(profile.total_study_days),
        total_pomodoros=_i(profile.total_pomodoros),
        avg_session_duration=_i(profile.avg_session_duration),
        avg_pomodoro_per_day=_f(profile.avg_pomodoro_per_day),
        optimal_hours=_s(profile.optimal_hours),
        preferred_time_slots=profile.preferred_time_slots,
        self_control_score=_f(profile.self_control_score, 50.0),
        consistency_score=_f(profile.consistency_score, 50.0),
        focus_score=_f(profile.focus_score, 50.0),
        planning_score=_f(profile.planning_score, 50.0),
        streak_days=_i(perf.get("streak", 0)),
        weak_points=profile.weak_points,
        recent_performance=profile.recent_performance,
        last_updated=last_updated,
        data_insufficient=bool(perf.get("data_insufficient", False)),
        insights=list(perf.get("insights", [])),
    )


# ── routes ────────────────────────────────────────────────────────────────────

@router.get("", response_model=ProfileResponse)
async def get_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProfileResponse:
    """获取当前用户的学习画像（不存在时自动计算）"""
    uid = _i(current_user.id)
    profile = await get_or_compute_profile(db, uid)
    if profile is None:
        profile = await compute_and_save_profile(db, uid)
        await db.commit()
    return _build_response(uid, profile)


@router.post("/refresh", response_model=ProfileResponse)
async def refresh_profile(
    db: AsyncSession = Depends(get_db),
    current_user: User = Depends(get_current_user),
) -> ProfileResponse:
    """立即重新计算用户画像并返回最新结果"""
    uid = _i(current_user.id)
    profile = await compute_and_save_profile(db, uid)
    await db.commit()
    return _build_response(uid, profile)
