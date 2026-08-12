"""复习调度服务：FSRS 优先，SM-2 兜底。

决策依据：docs/superpowers/specs/2026-07-26-knowledge-layer-context-substrate-agent-architecture.md（D1/D6）。

- 正常路径使用 py-fsrs（学习/再学习步骤置空 → 纯天级调度，与现有数据模型一致）。
- `fsrs` 包不可用时回退到原 SM-2 算法，行为与替换前保持一致（降级纪律）。
- 旧字段（interval_days / ease_factor / repetitions）继续维护一个版本周期：
  FSRS 路径下 interval_days 由 due 反推、repetitions 保持"失败清零/成功+1"语义、
  ease_factor 冻结不再变化；SM-2 兜底路径下三者仍按旧算法更新。
- 存量卡迁移采用"保守初始化"：无 FSRS 状态但已有复习历史的卡，
  以 stability≈当前间隔天数、difficulty 由 ease_factor 线性映射进入 Review 状态。
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

try:  # pragma: no cover - 导入是否成功由环境决定
    from fsrs import Card as _FsrsCard
    from fsrs import Rating as _FsrsRating
    from fsrs import Scheduler as _FsrsScheduler
    from fsrs import State as _FsrsState

    _FSRS_IMPORT_OK = True
except Exception:  # pragma: no cover
    _FSRS_IMPORT_OK = False

# SM-2 quality(0-5) → FSRS Rating：0-2 为失败，3 勉强通过，4 正常，5 轻松
_QUALITY_TO_RATING = {0: 1, 1: 1, 2: 1, 3: 2, 4: 3, 5: 4}

_MIN_EASE_FACTOR = 130
_DEFAULT_EASE_FACTOR = 250


@dataclass(frozen=True)
class ReviewInput:
    """一次复习前的调度状态快照。"""

    interval_days: int = 1
    ease_factor: int = _DEFAULT_EASE_FACTOR
    repetitions: int = 0
    stability: float | None = None
    difficulty: float | None = None
    fsrs_state: int | None = None
    fsrs_step: int | None = None
    due_at: datetime | None = None
    last_review_at: datetime | None = None


@dataclass(frozen=True)
class ScheduleResult:
    """一次复习后的调度结果（与传入 now 同一时钟域的 naive datetime）。"""

    due_at: datetime
    interval_days: int
    repetitions: int
    ease_factor: int
    stability: float | None
    difficulty: float | None
    fsrs_state: int | None
    fsrs_step: int | None
    last_review_at: datetime
    algorithm: str  # "fsrs" | "sm2"


_scheduler_instance: Any = None


def is_fsrs_available() -> bool:
    return _FSRS_IMPORT_OK


def _get_scheduler() -> Any:
    global _scheduler_instance
    if _scheduler_instance is None:
        # 空学习步骤 → 首次复习即进入 Review 状态、天级间隔；关闭 fuzzing 保证可确定性
        _scheduler_instance = _FsrsScheduler(
            learning_steps=(),
            relearning_steps=(),
            enable_fuzzing=False,
        )
    return _scheduler_instance


def _as_utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _as_naive(value: datetime) -> datetime:
    return value.astimezone(timezone.utc).replace(tzinfo=None) if value.tzinfo else value


def _clamp_quality(quality: int) -> int:
    return max(0, min(5, int(quality)))


def _legacy_difficulty(ease_factor_scaled: int) -> float:
    """把 SM-2 ease factor（130-350，*100 存储）保守映射到 FSRS difficulty（1-10）。"""
    ef = max(_MIN_EASE_FACTOR, int(ease_factor_scaled or _DEFAULT_EASE_FACTOR)) / 100.0
    return min(10.0, max(1.0, 11.0 - (ef - 1.3) * 5.0))


def _build_card(state: ReviewInput, now_utc: datetime) -> Any:
    """从存量字段构建 FSRS Card：已有 FSRS 状态 > 有复习历史 > 全新卡。"""
    if state.stability is not None:
        return _FsrsCard(
            state=_FsrsState(int(state.fsrs_state or int(_FsrsState.Review))),
            step=state.fsrs_step,
            stability=float(state.stability),
            difficulty=float(state.difficulty or _legacy_difficulty(state.ease_factor)),
            due=_as_utc(state.due_at) if state.due_at else now_utc,
            last_review=_as_utc(state.last_review_at) if state.last_review_at else None,
        )
    has_history = (state.repetitions or 0) > 0 or (state.interval_days or 1) > 1
    if has_history:
        return _FsrsCard(
            state=_FsrsState.Review,
            step=None,
            stability=float(max(1, state.interval_days or 1)),
            difficulty=_legacy_difficulty(state.ease_factor),
            due=_as_utc(state.due_at) if state.due_at else now_utc,
            last_review=None,
        )
    return _FsrsCard()


def _sm2_update(interval_days: int, repetitions: int, ease_factor_scaled: int, quality: int):
    """原 SM-2 算法（ease_factor 使用 *100 的整数存储），作为 FSRS 不可用时的兜底。"""
    ef = (ease_factor_scaled or _DEFAULT_EASE_FACTOR) / 100.0
    ef = ef + (0.1 - (5 - quality) * (0.08 + (5 - quality) * 0.02))
    ef = max(1.3, ef)
    if quality < 3:
        new_repetitions = 0
        new_interval = 1
    else:
        if repetitions <= 0:
            new_interval = 1
        elif repetitions == 1:
            new_interval = 6
        else:
            base = interval_days or 1
            new_interval = max(1, int(round(base * ef)))
        new_repetitions = repetitions + 1
    return new_interval, new_repetitions, int(round(ef * 100))


def _next_repetitions(repetitions: int, quality: int) -> int:
    return 0 if quality < 3 else int(repetitions or 0) + 1


def schedule_review(state: ReviewInput, quality: int, now: datetime) -> ScheduleResult:
    """计算一次复习后的下一次调度。

    FSRS 可用时走 FSRS；否则回退 SM-2。返回值中的时间均为 naive datetime，
    与调用方传入的 now 保持同一时钟域。
    """
    quality = _clamp_quality(quality)

    if not _FSRS_IMPORT_OK:
        days, reps, ef = _sm2_update(
            state.interval_days or 1, state.repetitions or 0, state.ease_factor, quality
        )
        return ScheduleResult(
            due_at=now + timedelta(days=days),
            interval_days=days,
            repetitions=reps,
            ease_factor=ef,
            stability=state.stability,
            difficulty=state.difficulty,
            fsrs_state=state.fsrs_state,
            fsrs_step=state.fsrs_step,
            last_review_at=now,
            algorithm="sm2",
        )

    now_utc = _as_utc(now)
    card = _build_card(state, now_utc)
    rating = _FsrsRating(_QUALITY_TO_RATING[quality])
    updated, _log = _get_scheduler().review_card(card, rating, review_datetime=now_utc)

    due_naive = _as_naive(updated.due)
    # FSRS due 与 now 同为 UTC 域；换算回调用方时钟域只需保留 delta
    delta = due_naive - _as_naive(now_utc)
    due_at = now + delta
    interval_days = max(0, int(round(delta.total_seconds() / 86400)))

    return ScheduleResult(
        due_at=due_at,
        interval_days=interval_days,
        repetitions=_next_repetitions(state.repetitions or 0, quality),
        ease_factor=int(state.ease_factor or _DEFAULT_EASE_FACTOR),
        stability=float(updated.stability) if updated.stability is not None else None,
        difficulty=float(updated.difficulty) if updated.difficulty is not None else None,
        fsrs_state=int(updated.state),
        fsrs_step=updated.step if updated.step is None else int(updated.step),
        last_review_at=now,
        algorithm="fsrs",
    )


def review_input_from(entity: Any, due_attr: str) -> ReviewInput:
    """从 ORM 实体（AnkiCard / ReviewSchedule）读取调度快照。"""
    return ReviewInput(
        interval_days=int(getattr(entity, "interval_days", 1) or 1),
        ease_factor=int(getattr(entity, "ease_factor", _DEFAULT_EASE_FACTOR) or _DEFAULT_EASE_FACTOR),
        repetitions=int(getattr(entity, "repetitions", 0) or 0),
        stability=getattr(entity, "stability", None),
        difficulty=getattr(entity, "difficulty", None),
        fsrs_state=getattr(entity, "fsrs_state", None),
        fsrs_step=getattr(entity, "fsrs_step", None),
        due_at=getattr(entity, due_attr, None),
        last_review_at=getattr(entity, "last_review_at", None),
    )


def apply_review(entity: Any, quality: int, now: datetime, due_attr: str) -> ScheduleResult:
    """对 ORM 实体执行一次复习调度并写回字段，返回调度结果。"""
    result = schedule_review(review_input_from(entity, due_attr), quality, now)
    setattr(entity, due_attr, result.due_at)
    entity.interval_days = result.interval_days
    entity.repetitions = result.repetitions
    entity.ease_factor = result.ease_factor
    entity.last_quality = _clamp_quality(quality)
    entity.stability = result.stability
    entity.difficulty = result.difficulty
    entity.fsrs_state = result.fsrs_state
    entity.fsrs_step = result.fsrs_step
    entity.last_review_at = result.last_review_at
    return result
