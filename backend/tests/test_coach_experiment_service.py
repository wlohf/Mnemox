import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.config import settings
from app.database import Base
from app.models.user import User
from app.services.coach_action_service import create_coach_nudge
from app.services.coach_experiment_service import (
    build_coach_experiment_assignment,
    build_coach_experiment_report,
)
from app.services.coach_skills.base import CoachSkillResult
from app.services.learning_event_service import CanonicalEventType, record_coach_nudge_event


class CoachExperimentServiceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "coach-experiment.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as connection:
            await connection.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> int:
        async with self.sessions() as session:
            user = User(
                username=username,
                email=f"{username}@example.com",
                hashed_password="hash",
                is_active=True,
            )
            session.add(user)
            await session.flush()
            user_id = int(user.id)
            await session.commit()
            return user_id

    def test_assignment_is_stable_bounded_and_a_a_only(self):
        first = build_coach_experiment_assignment(
            42,
            enabled=True,
            experiment_id="test-aa-v1",
            split_percent=50,
        )
        second = build_coach_experiment_assignment(
            42,
            enabled=True,
            experiment_id="test-aa-v1",
            split_percent=50,
        )

        self.assertEqual(first, second)
        self.assertIn(first["variant"], {"control", "shadow"})
        self.assertGreaterEqual(first["bucket"], 0)
        self.assertLess(first["bucket"], 10_000)
        self.assertEqual(first["mode"], "aa_observation")
        self.assertFalse(first["policy_applied"])
        variants = {
            build_coach_experiment_assignment(
                user_id,
                enabled=True,
                experiment_id="test-aa-v1",
                split_percent=50,
            )["variant"]
            for user_id in range(1, 100)
        }
        self.assertEqual(variants, {"control", "shadow"})
        self.assertIsNone(build_coach_experiment_assignment(42, enabled=False))

    async def test_nudge_and_immutable_lifecycle_event_keep_same_assignment(self):
        user_id = await self._create_user("experiment-instrumentation")
        with patch.object(settings, "COACH_INTERVENTION_EXPERIMENT_ENABLED", True):
            async with self.sessions() as session:
                nudge = await create_coach_nudge(
                    session,
                    user_id,
                    event_id=None,
                    skill_id="minimum_next_step",
                    policy={
                        "channel": "agent_panel",
                        "priority": "low",
                        "reason": "test",
                        "evidence": [],
                    },
                    result=CoachSkillResult(
                        title="最小一步",
                        body="敏感正文不应进入事件账本",
                        suggested_action={"type": "route", "route": "/pomodoro"},
                        route="/pomodoro",
                    ),
                )
                shown = await record_coach_nudge_event(
                    session,
                    user_id,
                    nudge,
                    CanonicalEventType.COACH_NUDGE_SHOWN,
                )
                await session.commit()

        assignment = nudge["explainability"]["experiment"]
        self.assertEqual(shown["payload"]["experiment"], assignment)
        self.assertFalse(shown["payload"]["experiment"]["policy_applied"])
        self.assertNotIn("title", shown["payload"])
        self.assertNotIn("body", shown["payload"])
        self.assertNotIn("user_id", shown["payload"]["experiment"])

    async def test_report_separates_mature_pending_and_uninstrumented_exposures(self):
        user_id = await self._create_user("experiment-report")
        now = datetime(2026, 9, 1, 12, 0, 0)
        assignment = build_coach_experiment_assignment(
            user_id,
            enabled=True,
            experiment_id="coach_intervention_aa_v1",
            split_percent=50,
        )

        def nudge(nudge_id: str, *, instrumented: bool = True):
            return {
                "id": nudge_id,
                "event_id": None,
                "skill_id": "review_debt_rescue",
                "channel": "agent_panel",
                "priority": "low",
                "suggested_action": {"type": "route", "route": "/review"},
                "requires_confirmation": False,
                "explainability": {"experiment": assignment} if instrumented else {},
            }

        mature = nudge("cn_mature")
        pending = nudge("cn_pending")
        legacy = nudge("cn_legacy", instrumented=False)
        async with self.sessions() as session:
            await record_coach_nudge_event(
                session,
                user_id,
                mature,
                CanonicalEventType.COACH_NUDGE_SHOWN,
                occurred_at=now - timedelta(days=10),
            )
            await record_coach_nudge_event(
                session,
                user_id,
                mature,
                CanonicalEventType.COACH_NUDGE_ACCEPTED,
                outcome="accepted",
                occurred_at=now - timedelta(days=9, hours=20),
            )
            await record_coach_nudge_event(
                session,
                user_id,
                mature,
                CanonicalEventType.COACH_NUDGE_STARTED,
                outcome="started",
                occurred_at=now - timedelta(days=9, hours=19),
            )
            await record_coach_nudge_event(
                session,
                user_id,
                mature,
                CanonicalEventType.COACH_NUDGE_COMPLETED,
                outcome="completed",
                attribution={"method": "domain_event", "attempt_id": "attempt-1"},
                occurred_at=now - timedelta(days=9),
            )
            await record_coach_nudge_event(
                session,
                user_id,
                pending,
                CanonicalEventType.COACH_NUDGE_SHOWN,
                occurred_at=now - timedelta(days=2),
            )
            await record_coach_nudge_event(
                session,
                user_id,
                legacy,
                CanonicalEventType.COACH_NUDGE_SHOWN,
                occurred_at=now - timedelta(days=10),
            )
            await session.commit()

        with patch.object(settings, "COACH_INTERVENTION_EXPERIMENT_ENABLED", True):
            async with self.sessions() as session:
                report = await build_coach_experiment_report(
                    session,
                    user_id,
                    days=14,
                    now=now,
                )

        variant = next(item for item in report["variants"] if item["variant"] == assignment["variant"])
        self.assertTrue(report["enabled"])
        self.assertFalse(report["policy_behavior_changed"])
        self.assertEqual(variant["shown_count"], 2)
        self.assertEqual(variant["mature_exposure_count"], 1)
        self.assertEqual(variant["pending_attribution_count"], 1)
        self.assertEqual(variant["accepted_count"], 1)
        self.assertEqual(variant["started_count"], 1)
        self.assertEqual(variant["completed_count"], 1)
        self.assertEqual(variant["completed_by_domain_event_count"], 1)
        self.assertEqual(variant["execution_rate"], 100.0)
        self.assertEqual(report["coverage"]["instrumented_shown_count"], 2)
        self.assertEqual(report["coverage"]["uninstrumented_shown_count"], 1)
        self.assertFalse(report["decision_readiness"]["ready"])


if __name__ == "__main__":
    unittest.main()
