"""Cohort regression tests for distinct synthetic Coach user profiles.

Every case shares one temporary SQLite database so the test also verifies that
the event ledger, metrics, and policy decisions remain scoped to each user.
These fixtures validate implementation behaviour only; they do not measure
real learner outcomes.
"""
from __future__ import annotations

import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.services.coach_policy_engine import default_coach_preferences, evaluate_coach_policy
from app.services.learning_event_service import (
    CanonicalEventType,
    record_coach_nudge_event,
    record_learning_event,
    record_review_completed_event,
    record_review_scheduled_event,
)
from app.services.north_star_metrics_service import build_north_star_metrics


NOW = datetime(2026, 8, 27, 12, 0, 0)


def _nudge(nudge_id: str) -> dict[str, object]:
    return {
        "id": nudge_id,
        "event_id": f"event_{nudge_id}",
        "skill_id": "restart_after_interruption",
        "channel": "in_app_nudge",
        "priority": "medium",
        "suggested_action": {"type": "route", "route": "/pomodoro"},
        "requires_confirmation": False,
    }


class CoachBehaviorUserProfileTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(
            f"sqlite+aiosqlite:///{Path(self.tmpdir.name) / 'user_profiles.sqlite3'}",
            future=True,
        )
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, profile: str) -> int:
        user = User(
            username=f"synthetic_{profile}",
            email=f"synthetic_{profile}@example.invalid",
            hashed_password="synthetic-only",
            is_active=True,
        )
        self.session.add(user)
        await self.session.flush()
        return int(user.id)

    async def _record_nudge(self, user_id: int, nudge_id: str, shown_at: datetime, outcome: str | None = None) -> None:
        nudge = _nudge(nudge_id)
        await record_coach_nudge_event(
            self.session,
            user_id,
            nudge,
            CanonicalEventType.COACH_NUDGE_SHOWN,
            occurred_at=shown_at,
        )
        if outcome in {"domain", "confirmation"}:
            await record_coach_nudge_event(
                self.session,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_ACCEPTED,
                outcome="accepted",
                occurred_at=shown_at + timedelta(minutes=1),
            )
            await record_coach_nudge_event(
                self.session,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_STARTED,
                outcome="started",
                occurred_at=shown_at + timedelta(minutes=2),
            )
            await record_coach_nudge_event(
                self.session,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_COMPLETED,
                outcome="completed",
                attribution={"method": "domain_event" if outcome == "domain" else "user_confirmation"},
                occurred_at=shown_at + timedelta(minutes=25),
            )
        elif outcome == "abandoned":
            await record_coach_nudge_event(
                self.session,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_STARTED,
                outcome="started",
                occurred_at=shown_at + timedelta(minutes=2),
            )
            await record_coach_nudge_event(
                self.session,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_ABANDONED,
                outcome="abandoned",
                occurred_at=shown_at + timedelta(minutes=25),
            )

    async def _record_interruptions(self, user_id: int, recoveries: list[int | None]) -> None:
        for index, recovery_minutes in enumerate(recoveries):
            interrupted_at = NOW - timedelta(days=8 - index)
            await record_learning_event(
                self.session,
                user_id,
                CanonicalEventType.POMODORO_INTERRUPTED,
                source="synthetic_profile",
                payload={"pomodoro_id": f"interrupt-{index}"},
                occurred_at=interrupted_at,
            )
            if recovery_minutes is not None:
                await record_learning_event(
                    self.session,
                    user_id,
                    CanonicalEventType.POMODORO_STARTED,
                    source="synthetic_profile",
                    payload={"pomodoro_id": f"restart-{index}"},
                    occurred_at=interrupted_at + timedelta(minutes=recovery_minutes),
                )

    async def _record_reviews(
        self,
        user_id: int,
        outcomes: list[bool],
        *,
        newest_is_pending: bool = False,
        age_days: int = 0,
    ) -> None:
        for index, is_on_time in enumerate(outcomes):
            due_at = NOW - timedelta(days=7 - index + age_days)
            if newest_is_pending and index == len(outcomes) - 1:
                due_at = NOW - timedelta(hours=8)
            entity_id = 700 + index
            await record_review_scheduled_event(
                self.session,
                user_id,
                entity_type="synthetic_review",
                entity_id=entity_id,
                due_at=due_at,
                source="synthetic_profile",
                occurred_at=due_at - timedelta(days=1),
            )
            if is_on_time:
                await record_review_completed_event(
                    self.session,
                    user_id,
                    entity_type="synthetic_review",
                    entity_id=entity_id,
                    scheduled_for=due_at,
                    source="synthetic_profile",
                    quality=4,
                    occurred_at=due_at + timedelta(hours=2),
                )

    async def _record_sessions(self, user_id: int, durations_in_minutes: list[int], *, age_days: int = 0) -> None:
        for index, minutes in enumerate(durations_in_minutes):
            await record_learning_event(
                self.session,
                user_id,
                CanonicalEventType.POMODORO_COMPLETED,
                source="synthetic_profile",
                payload={"pomodoro_id": f"session-{age_days}-{index}"},
                duration=minutes * 60,
                occurred_at=NOW - timedelta(days=age_days + index),
            )

    async def test_metrics_and_policy_across_distinct_user_profiles(self):
        """Exercise stable, returning, new, inactive and interruption-sensitive learners."""

        async with self.sessions() as self.session:
            steady_user = await self._create_user("steady")
            returning_user = await self._create_user("returning")
            new_user = await self._create_user("new")
            inactive_user = await self._create_user("inactive")

            # 规律学习者：所有成熟建议完成，稳定完成复习和学习时段。
            for index in range(4):
                await self._record_nudge(steady_user, f"shared-nudge-{index}", NOW - timedelta(days=9), "domain")
            await self._record_reviews(steady_user, [True, True, True])
            await self._record_sessions(steady_user, [25, 25, 25, 25])

            # 重新投入者：有放弃、有恢复延迟，也有少量有效学习。
            for index, outcome in enumerate(("domain", "confirmation", "abandoned", "abandoned")):
                await self._record_nudge(returning_user, f"returning-nudge-{index}", NOW - timedelta(days=9), outcome)
            await self._record_interruptions(returning_user, [20, 100, None])
            await self._record_reviews(returning_user, [True, False, False])
            await self._record_sessions(returning_user, [25, 25, 10])

            # 新用户：所有观察都还没成熟。故意复用规律用户的 nudge id，验证不能串用户归因。
            for index in range(3):
                await self._record_nudge(new_user, f"shared-nudge-{index}", NOW - timedelta(days=1))
            await record_learning_event(
                self.session,
                new_user,
                CanonicalEventType.POMODORO_INTERRUPTED,
                source="synthetic_profile",
                payload={"pomodoro_id": "new-interrupt"},
                occurred_at=NOW - timedelta(hours=6),
            )
            await self._record_reviews(new_user, [False], newest_is_pending=True)
            await self._record_sessions(new_user, [15, 14])

            # 长期未使用者：其历史不应落入当前 14 天统计窗口。
            await self._record_nudge(inactive_user, "inactive-nudge", NOW - timedelta(days=20), "domain")
            await self._record_reviews(inactive_user, [True], age_days=20)
            await self._record_sessions(inactive_user, [25], age_days=20)

            steady_metrics = await build_north_star_metrics(self.session, steady_user, days=14, now=NOW)
            returning_metrics = await build_north_star_metrics(self.session, returning_user, days=14, now=NOW)
            new_metrics = await build_north_star_metrics(self.session, new_user, days=14, now=NOW)
            inactive_metrics = await build_north_star_metrics(self.session, inactive_user, days=14, now=NOW)
            await self.session.commit()

        with self.subTest("规律学习者"):
            self.assertEqual(steady_metrics["metrics"]["suggestion_execution_rate"]["value"], 100.0)
            self.assertEqual(steady_metrics["metrics"]["review_on_time_rate"]["value"], 100.0)
            self.assertEqual(steady_metrics["metrics"]["weekly_effective_study_sessions"]["value"], 4)

        with self.subTest("重新投入者"):
            suggestions = returning_metrics["metrics"]["suggestion_execution_rate"]
            recovery = returning_metrics["metrics"]["interruption_recovery_time"]
            reviews = returning_metrics["metrics"]["review_on_time_rate"]
            self.assertEqual((suggestions["value"], suggestions["abandoned_count"]), (50.0, 2))
            self.assertEqual((recovery["value"], recovery["denominator"], recovery["unrecovered_count"]), (60.0, 3, 1))
            self.assertEqual((reviews["value"], reviews["denominator"]), (33.3, 3))
            self.assertEqual(returning_metrics["metrics"]["weekly_effective_study_sessions"]["value"], 2)

        with self.subTest("新用户与跨用户隔离"):
            suggestions = new_metrics["metrics"]["suggestion_execution_rate"]
            recovery = new_metrics["metrics"]["interruption_recovery_time"]
            reviews = new_metrics["metrics"]["review_on_time_rate"]
            self.assertEqual((suggestions["value"], suggestions["denominator"], suggestions["pending_attribution_count"]), (None, 0, 3))
            self.assertEqual((recovery["value"], recovery["denominator"], recovery["pending_observation_count"]), (None, 0, 1))
            self.assertEqual((reviews["value"], reviews["denominator"], reviews["pending_observation_count"]), (None, 0, 1))
            self.assertEqual(new_metrics["metrics"]["weekly_effective_study_sessions"]["value"], 1)

        with self.subTest("长期未使用者"):
            self.assertEqual(inactive_metrics["metrics"]["suggestion_execution_rate"]["denominator"], 0)
            self.assertEqual(inactive_metrics["metrics"]["review_on_time_rate"]["denominator"], 0)
            self.assertEqual(inactive_metrics["metrics"]["weekly_effective_study_sessions"]["value"], 0)

        base_snapshot = {
            "generated_at": NOW.replace(hour=22, minute=30).isoformat(),
            "review": {"due_review_count": 0},
            "learning": {},
            "risk_flags": {},
            "coach": {"today_nudge_count": 0, "last_nudge_at": None},
        }
        interrupted = {"event_type": "pomodoro.interrupted", "source": "pomodoro", "severity": "info", "payload": {}}
        quiet_decision = evaluate_coach_policy(
            {**interrupted, "channel": "desktop_notification"},
            base_snapshot,
            {
                **default_coach_preferences(),
                "desktop_notifications_enabled": True,
                "allowed_channels": ["desktop_notification", "in_app_nudge"],
                "quiet_hours_start": "22:00",
                "quiet_hours_end": "07:00",
            },
            [],
        )
        disruption_decision = evaluate_coach_policy(
            interrupted,
            {**base_snapshot, "generated_at": NOW.isoformat()},
            default_coach_preferences(),
            [],
            [{"skill_id": "restart_after_interruption", "channel": "in_app_nudge", "event_type": "pomodoro.interrupted", "too_disruptive_count": 2, "recent_score": -2.0}],
        )
        with self.subTest("夜间静默与高频打扰敏感者"):
            self.assertEqual((quiet_decision["should_intervene"], quiet_decision["reason"]), (False, "quiet_hours"))
            self.assertEqual((disruption_decision["should_intervene"], disruption_decision["reason"]), (False, "learned_disruption_feedback"))
