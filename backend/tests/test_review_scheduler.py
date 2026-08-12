"""复习调度服务（FSRS 优先 / SM-2 兜底）单元测试。"""
from datetime import datetime, timedelta

import pytest

from app.services import review_scheduler
from app.services.review_scheduler import (
    ReviewInput,
    apply_review,
    is_fsrs_available,
    schedule_review,
)

NOW = datetime(2026, 7, 26, 12, 0, 0)


class FakeCard:
    """模拟 AnkiCard / ReviewSchedule 的调度字段。"""

    def __init__(self, **kwargs):
        defaults = {
            "interval_days": 1,
            "ease_factor": 250,
            "repetitions": 0,
            "last_quality": None,
            "stability": None,
            "difficulty": None,
            "fsrs_state": None,
            "fsrs_step": None,
            "due_at": None,
            "last_review_at": None,
        }
        defaults.update(kwargs)
        for key, value in defaults.items():
            setattr(self, key, value)


def test_fsrs_package_is_installed():
    assert is_fsrs_available(), "fsrs 包应随 requirements 安装"


def test_new_card_good_review_schedules_future_due_date():
    # Arrange
    state = ReviewInput()

    # Act
    result = schedule_review(state, quality=4, now=NOW)

    # Assert
    assert result.algorithm == "fsrs"
    assert result.due_at > NOW
    assert result.interval_days >= 1
    assert result.stability is not None and result.stability > 0
    assert result.difficulty is not None and 1.0 <= result.difficulty <= 10.0
    assert result.repetitions == 1
    assert result.last_review_at == NOW


def test_failed_review_resets_repetitions_and_schedules_short_interval():
    # Arrange
    state = ReviewInput(interval_days=10, repetitions=4, stability=10.0, difficulty=5.0)

    # Act
    result = schedule_review(state, quality=1, now=NOW)

    # Assert
    assert result.repetitions == 0
    assert result.interval_days <= 10
    assert result.due_at > NOW


def test_legacy_card_without_fsrs_state_is_seeded_from_interval():
    # Arrange: 存量卡（interval=14 天、EF=2.5、无 FSRS 字段）
    state = ReviewInput(interval_days=14, ease_factor=250, repetitions=3)

    # Act
    result = schedule_review(state, quality=4, now=NOW)

    # Assert: 保守初始化后 Good 应给出比原间隔更长的下一次间隔
    assert result.algorithm == "fsrs"
    assert result.interval_days > 14
    assert result.stability is not None and result.stability > 14
    assert result.repetitions == 4


def test_higher_quality_gives_longer_interval():
    # Arrange
    state = ReviewInput(interval_days=6, ease_factor=250, repetitions=2)

    # Act
    hard = schedule_review(state, quality=3, now=NOW)
    easy = schedule_review(state, quality=5, now=NOW)

    # Assert
    assert easy.interval_days > hard.interval_days


def test_ease_factor_is_frozen_under_fsrs():
    # Arrange
    state = ReviewInput(interval_days=6, ease_factor=280, repetitions=2)

    # Act
    result = schedule_review(state, quality=4, now=NOW)

    # Assert: legacy 字段冻结，不再被 FSRS 修改
    assert result.ease_factor == 280


def test_quality_is_clamped_to_valid_range():
    # Act
    result = schedule_review(ReviewInput(), quality=9, now=NOW)

    # Assert: 超界评分按 5 处理而不是崩溃
    assert result.due_at > NOW


def test_sm2_fallback_when_fsrs_unavailable(monkeypatch):
    # Arrange
    monkeypatch.setattr(review_scheduler, "_FSRS_IMPORT_OK", False)
    state = ReviewInput(interval_days=6, ease_factor=250, repetitions=2)

    # Act
    result = schedule_review(state, quality=4, now=NOW)

    # Assert: 行为与原 SM-2 一致（6 * 2.5 = 15 天），字段照常维护
    assert result.algorithm == "sm2"
    assert result.interval_days == 15
    assert result.due_at == NOW + timedelta(days=15)
    assert result.repetitions == 3
    assert result.ease_factor == 250


def test_sm2_fallback_failed_review_resets_to_one_day(monkeypatch):
    # Arrange
    monkeypatch.setattr(review_scheduler, "_FSRS_IMPORT_OK", False)
    state = ReviewInput(interval_days=10, ease_factor=250, repetitions=4)

    # Act
    result = schedule_review(state, quality=1, now=NOW)

    # Assert
    assert result.interval_days == 1
    assert result.repetitions == 0


def test_apply_review_writes_back_all_scheduling_fields():
    # Arrange
    card = FakeCard(interval_days=14, ease_factor=250, repetitions=3)

    # Act
    result = apply_review(card, quality=4, now=NOW, due_attr="due_at")

    # Assert
    assert card.due_at == result.due_at
    assert card.interval_days == result.interval_days
    assert card.repetitions == result.repetitions
    assert card.last_quality == 4
    assert card.stability == result.stability
    assert card.difficulty == result.difficulty
    assert card.fsrs_state == result.fsrs_state
    assert card.last_review_at == NOW


def test_consecutive_reviews_grow_interval():
    # Arrange
    card = FakeCard()

    # Act: 连续三次 Good 复习（按到期时间推进）
    first = apply_review(card, 4, NOW, due_attr="due_at")
    second = apply_review(card, 4, first.due_at, due_attr="due_at")
    third = apply_review(card, 4, second.due_at, due_attr="due_at")

    # Assert: 间隔单调增长（间隔重复的核心性质）
    assert first.interval_days >= 1
    assert second.interval_days > first.interval_days
    assert third.interval_days > second.interval_days


def test_naive_datetime_in_gives_naive_datetime_out():
    # Act
    result = schedule_review(ReviewInput(), quality=4, now=NOW)

    # Assert: 返回时间与传入 now 同为 naive，避免与现有 DateTime 列混用出错
    assert result.due_at.tzinfo is None
    assert result.last_review_at.tzinfo is None
