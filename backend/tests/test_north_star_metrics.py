import tempfile
import unittest
from datetime import datetime, timedelta, timezone
from pathlib import Path

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.user import User
from app.services.learning_event_service import (
    CanonicalEventType,
    record_coach_nudge_event,
    record_learning_event,
    record_review_completed_event,
    record_review_scheduled_event,
)
from app.services.north_star_metrics_service import build_north_star_metrics, validate_metric_time_zone


class NorthStarMetricsTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "north_star_metrics.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> int:
        async with self.sessionmaker() as session:
            user = User(username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return user_id

    async def test_metrics_use_mature_events_and_ignore_pending_observation_windows(self):
        user_id = await self._create_user("owner")
        now = datetime(2026, 8, 1, 12, 0, 0)

        async with self.sessionmaker() as session:
            completed_nudge = {
                "id": "cn_completed",
                "event_id": "ce_trigger",
                "skill_id": "restart_after_interruption",
                "channel": "in_app_nudge",
                "priority": "medium",
                "suggested_action": {"type": "route", "route": "/pomodoro"},
                "requires_confirmation": False,
            }
            ignored_nudge = {**completed_nudge, "id": "cn_ignored"}
            pending_nudge = {**completed_nudge, "id": "cn_pending"}
            await record_coach_nudge_event(
                session,
                user_id,
                completed_nudge,
                CanonicalEventType.COACH_NUDGE_SHOWN,
                occurred_at=now - timedelta(days=10),
            )
            await record_coach_nudge_event(
                session,
                user_id,
                completed_nudge,
                CanonicalEventType.COACH_NUDGE_COMPLETED,
                outcome="completed",
                occurred_at=now - timedelta(days=9),
            )
            await record_coach_nudge_event(
                session,
                user_id,
                ignored_nudge,
                CanonicalEventType.COACH_NUDGE_SHOWN,
                occurred_at=now - timedelta(days=10),
            )
            await record_coach_nudge_event(
                session,
                user_id,
                pending_nudge,
                CanonicalEventType.COACH_NUDGE_SHOWN,
                occurred_at=now - timedelta(days=2),
            )

            await record_learning_event(
                session,
                user_id,
                CanonicalEventType.POMODORO_INTERRUPTED,
                source="test",
                payload={"pomodoro_id": 1},
                occurred_at=now - timedelta(days=9),
            )
            await record_learning_event(
                session,
                user_id,
                CanonicalEventType.POMODORO_STARTED,
                source="test",
                payload={"pomodoro_id": 2},
                occurred_at=now - timedelta(days=9) + timedelta(minutes=30),
            )
            await record_learning_event(
                session,
                user_id,
                CanonicalEventType.POMODORO_INTERRUPTED,
                source="test",
                payload={"pomodoro_id": 3},
                occurred_at=now - timedelta(days=8),
            )
            await record_learning_event(
                session,
                user_id,
                CanonicalEventType.POMODORO_INTERRUPTED,
                source="test",
                payload={"pomodoro_id": 4},
                occurred_at=now - timedelta(days=1),
            )

            on_time_due = now - timedelta(days=7)
            missed_due = now - timedelta(days=6)
            pending_due = now - timedelta(hours=8)
            await record_review_scheduled_event(
                session,
                user_id,
                entity_type="review_schedule",
                entity_id=101,
                due_at=on_time_due,
                source="test",
                item_type="question",
                item_id=1,
                occurred_at=now - timedelta(days=10),
            )
            await record_review_completed_event(
                session,
                user_id,
                entity_type="review_schedule",
                entity_id=101,
                scheduled_for=on_time_due,
                source="test",
                quality=4,
                occurred_at=on_time_due + timedelta(hours=2),
            )
            await record_review_scheduled_event(
                session,
                user_id,
                entity_type="review_schedule",
                entity_id=102,
                due_at=missed_due,
                source="test",
                item_type="question",
                item_id=2,
                occurred_at=now - timedelta(days=10),
            )
            await record_review_scheduled_event(
                session,
                user_id,
                entity_type="review_schedule",
                entity_id=103,
                due_at=pending_due,
                source="test",
                item_type="chapter",
                item_id=3,
                occurred_at=now - timedelta(days=1),
            )

            for pomodoro_id, offset, duration in ((10, 2, 900), (11, 1, 1500), (12, 1, 600)):
                await record_learning_event(
                    session,
                    user_id,
                    CanonicalEventType.POMODORO_COMPLETED,
                    source="test",
                    payload={"pomodoro_id": pomodoro_id},
                    duration=duration,
                    occurred_at=now - timedelta(days=offset),
                )
            await session.commit()

        async with self.sessionmaker() as session:
            report = await build_north_star_metrics(session, user_id, days=14, time_zone="UTC", now=now)

        metrics = report["metrics"]
        self.assertEqual(metrics["suggestion_execution_rate"]["value"], 50.0)
        self.assertEqual(metrics["suggestion_execution_rate"]["denominator"], 2)
        self.assertEqual(metrics["suggestion_execution_rate"]["pending_attribution_count"], 1)
        self.assertEqual(metrics["interruption_recovery_time"]["value"], 30.0)
        self.assertEqual(metrics["interruption_recovery_time"]["denominator"], 2)
        self.assertEqual(metrics["interruption_recovery_time"]["unrecovered_count"], 1)
        self.assertEqual(metrics["review_on_time_rate"]["value"], 50.0)
        self.assertEqual(metrics["review_on_time_rate"]["denominator"], 2)
        self.assertEqual(metrics["review_on_time_rate"]["pending_observation_count"], 1)
        self.assertEqual(metrics["weekly_effective_study_sessions"]["value"], 2)
        self.assertEqual(metrics["weekly_effective_study_sessions"]["minimum_duration_minutes"], 15)
        self.assertEqual(report["period"]["time_zone"], "UTC")

    async def test_coach_lifecycle_events_are_deduped_and_do_not_store_nudge_body(self):
        user_id = await self._create_user("privacy")
        nudge = {
            "id": "cn_private",
            "event_id": "ce_private",
            "skill_id": "low_motivation",
            "channel": "chat_inline",
            "priority": "low",
            "suggested_action": {"type": "route", "route": "/goals"},
            "requires_confirmation": True,
            "title": "sensitive title",
            "body": "sensitive body",
        }
        occurred_at = datetime(2026, 8, 1, 10, 0, 0)

        async with self.sessionmaker() as session:
            first = await record_coach_nudge_event(
                session,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_SHOWN,
                occurred_at=occurred_at,
            )
            second = await record_coach_nudge_event(
                session,
                user_id,
                nudge,
                CanonicalEventType.COACH_NUDGE_SHOWN,
                occurred_at=occurred_at,
            )
            await session.commit()

        self.assertEqual(first["id"], second["id"])
        self.assertEqual(first["metadata"]["schema_version"], 1)
        self.assertEqual(first["payload"]["nudge_id"], "cn_private")
        self.assertNotIn("title", first["payload"])
        self.assertNotIn("body", first["payload"])

    def test_time_zone_validation(self):
        self.assertEqual(validate_metric_time_zone("Asia/Tokyo"), "Asia/Tokyo")
        with self.assertRaises(ValueError):
            validate_metric_time_zone("not/a-real-zone")

    async def test_time_zone_changes_the_current_window_for_aware_now(self):
        user_id = await self._create_user("time-zone-owner")
        async with self.sessionmaker() as session:
            await record_learning_event(
                session,
                user_id,
                CanonicalEventType.POMODORO_COMPLETED,
                source="test",
                payload={"pomodoro_id": 99},
                duration=25 * 60,
                occurred_at=datetime(2026, 8, 10, 0, 10),
            )
            await session.commit()

        utc_now = datetime(2026, 8, 9, 23, 30, tzinfo=timezone.utc)
        async with self.sessionmaker() as session:
            utc_report = await build_north_star_metrics(
                session, user_id, days=7, time_zone="UTC", now=utc_now
            )
            shanghai_report = await build_north_star_metrics(
                session, user_id, days=7, time_zone="Asia/Shanghai", now=utc_now
            )

        self.assertEqual(utc_report["period"]["end_at"], "2026-08-09T23:30:00")
        self.assertEqual(shanghai_report["period"]["end_at"], "2026-08-10T07:30:00")
        self.assertEqual(utc_report["metrics"]["weekly_effective_study_sessions"]["value"], 0)
        self.assertEqual(shanghai_report["metrics"]["weekly_effective_study_sessions"]["value"], 1)


if __name__ == "__main__":
    unittest.main()
