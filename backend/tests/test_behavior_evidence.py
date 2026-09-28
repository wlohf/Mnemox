"""DI-0: provenance, missingness, grouping, current evidence and local-day use."""
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import patch

from fastapi import BackgroundTasks, FastAPI
from httpx import ASGITransport, AsyncClient
from sqlalchemy import func, select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base, get_db
import app.models  # noqa: F401
from app.auth import get_current_user
from app.models.coach import CoachPreference
from app.models.goal import Goal, Task
from app.models.learning_event import LearningEvent
from app.models.memory import UserMemory
from app.models.pomodoro import Pomodoro
from app.models.session import StudySession
from app.models.user import User
from app.models.user_profile import UserProfile
from app.routers.learning import get_learning_dashboard
from app.routers.pomodoro import (
    PomodoroCreate, PomodoroUpdate, PomodorosBatchCreate,
    start_pomodoro, complete_pomodoro, batch_create_pomodoros,
)
from app.routers.profile import router as profile_router
from app.routers.analytics import get_eda_report
from app.services.behavior_evidence_service import get_behavior_evidence
from app.services.learning_event_service import record_learning_event
from app.services.agent_memory_learning_service import run_agent_memory_learning
from app.services.learning_snapshot_service import build_learning_snapshot
from app.services.profile_service import build_profile_prompt_snippet, get_or_compute_profile
from app.agents.chat_agent import ChatAgent


NOW = datetime(2026, 9, 28, 1)  # Shanghai 09:00, local day starts at Sep 27 16:00 UTC.


class BehaviorEvidenceTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{Path(self.tmp.name) / 'evidence.db'}")
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessions = async_sessionmaker(self.engine, expire_on_commit=False)
        async with self.sessions() as db:
            users = [User(username=name, email=f"{name}@example.test", hashed_password="hash") for name in ("owner", "other")]
            db.add_all(users)
            await db.flush()
            self.uid, self.other = [u.id for u in users]
            db.add(CoachPreference(user_id=self.uid, time_zone="Asia/Shanghai"))
            await db.commit()
        self.actor = SimpleNamespace(id=self.uid)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmp.cleanup()

    def focus(self, **changes):
        values = dict(user_id=self.uid, time_basis="utc", record_origin="recorded",
                      started_at=NOW - timedelta(minutes=25), ended_at=NOW,
                      created_at=NOW - timedelta(minutes=25), duration=25,
                      planned_duration=25, actual_duration=25, completed=True)
        values.update(changes)
        return Pomodoro(**values)

    async def test_no_observations_are_unknown_not_zero_or_a_personality(self):
        async with self.sessions() as db:
            report = await get_behavior_evidence(db, self.uid, days=7, now=NOW)
            self.assertEqual(report.coverage["included_record_count"], 0)
            self.assertIsNone(report.metrics["actual_minutes"])
            self.assertIsNone(report.metrics["completion_rate"])
            self.assertTrue(all(d["status"] == "no_observation" and d["actual_minutes"] is None for d in report.daily))
            self.assertEqual(report.assessment, "descriptive_only")
            self.assertEqual(await db.scalar(select(func.count()).select_from(UserMemory)), 0)
            self.assertEqual(await db.scalar(select(func.count()).select_from(UserProfile)), 0)

    async def test_legacy_eda_does_not_assign_a_confident_personality_to_empty_or_biased_records(self):
        async with self.sessions() as db:
            empty = await get_eda_report(days=30, db=db, current_user=self.actor)
            self.assertIsNone(empty.profile.confidence)
            self.assertNotIn("间歇突击型", empty.markdown)
            db.add_all([self.focus() for _ in range(40)])
            await db.commit()
            report = await get_eda_report(days=30, db=db, current_user=self.actor)
            self.assertIsNone(report.profile.confidence)
            self.assertIsNone(report.summary["profile_confidence"])
            self.assertNotIn("高强度稳定型", report.markdown)

    async def test_chat_reads_current_evidence_and_never_exposes_old_trait_scores(self):
        async with self.sessions() as db:
            db.add(UserProfile(user_id=self.uid, focus_score=100, optimal_hours="20:00-22:00"))
            db.add(self.focus(actual_duration=10))
            await db.commit()
            with patch("app.services.behavior_evidence_service.utc_now_db", return_value=NOW):
                result = await ChatAgent()._get_profile(SimpleNamespace(db=db, user_id=self.uid))
            self.assertEqual(result["profile"]["metrics"]["actual_minutes"], 10)
            self.assertNotIn("focus_score", result["profile"])
            snapshot = await build_learning_snapshot(db, self.uid, now=NOW)
            self.assertEqual(snapshot["profile"], {})
            self.assertEqual(snapshot["learning"]["today_actual_minutes"], 10)

    async def test_local_day_and_interrupted_actual_duration_match_dashboard_and_coach(self):
        async with self.sessions() as db:
            db.add_all([
                self.focus(started_at=datetime(2026, 9, 27, 17, 35), ended_at=datetime(2026, 9, 27, 18), actual_duration=25),
                self.focus(started_at=datetime(2026, 9, 27, 15, 30), ended_at=datetime(2026, 9, 27, 15, 55)),
                self.focus(completed=False, stop_reason="distracted", actual_duration=5, duration=5, task_name="证明练习"),
            ])
            await db.commit()
            report = await get_behavior_evidence(db, self.uid, days=1, now=NOW)
            with patch("app.routers.learning.utc_now_db", return_value=NOW):
                dashboard = await get_learning_dashboard(db, self.actor)
            snapshot = await build_learning_snapshot(db, self.uid, now=NOW)
            self.assertEqual(report.metrics["actual_minutes"], 30)
            self.assertEqual(report.metrics["finished_count"], 2)
            self.assertEqual(dashboard["today"], "2026-09-28")
            self.assertEqual(dashboard["today_actual_minutes"], 30)
            self.assertEqual(snapshot["learning"]["today_actual_minutes"], 30)
            self.assertEqual(snapshot["time_zone"], "Asia/Shanghai")
            interruption = snapshot["learning"]["recent_interrupted_or_distracted"][0]
            self.assertEqual(interruption["task_name"], "证明练习")
            self.assertIsNotNone(interruption["started_at"])

    async def test_dst_day_uses_local_calendar_boundaries_instead_of_fixed_24_hours(self):
        async with self.sessions() as db:
            pref = await db.get(CoachPreference, self.uid)
            pref.time_zone = "America/New_York"
            endpoints = [datetime(2026, 3, 8, 4, 55), datetime(2026, 3, 8, 5, 30), datetime(2026, 3, 9, 3, 55)]
            db.add_all([self.focus(started_at=end - timedelta(minutes=25), ended_at=end, created_at=end) for end in endpoints])
            await db.commit()
            report = await get_behavior_evidence(db, self.uid, days=1, now=datetime(2026, 3, 9, 3, 59))
            self.assertEqual(report.window["last_local_date"], "2026-03-08")
            self.assertEqual(report.metrics["actual_minutes"], 50)
            self.assertEqual({r.local_hour for r in report.records}, {0, 23})

    async def test_planned_duration_and_start_event_do_not_add_to_actual_evidence(self):
        async with self.sessions() as db:
            started = await start_pomodoro(PomodoroCreate(duration=50, started_at=NOW - timedelta(minutes=10)), db, self.actor)
            await complete_pomodoro(started.id, PomodoroUpdate(completed=False, actual_duration=10, stop_reason="early_done", ended_at=NOW), BackgroundTasks(), db, self.actor)
            await db.commit()
            # Even a replay/derived report in the ledger is not another session.
            db.add(LearningEvent(user_id=self.uid, event_type="pomodoro_complete", timestamp=NOW,
                                 duration=600, event_data={"pomodoro_id": started.id}))
            db.add(LearningEvent(user_id=self.uid, event_type="agent.report", timestamp=NOW,
                                 duration=3000, event_data={"source_pomodoro": started.id}))
            await db.commit()
            report = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertEqual(report.metrics["actual_minutes"], 10)
            self.assertEqual(report.metrics["completed_count"], 1)
            self.assertEqual(report.coverage["experience_group_count"], 1)
            self.assertEqual(report.records[0].planned_minutes, 50)
            self.assertEqual(report.records[0].outcome, "early_done")
            learned = await run_agent_memory_learning(db, self.uid, rebuild_profile=False)
            self.assertGreater(learned["candidate_count"], 0)
            memory = await db.scalar(select(UserMemory).where(UserMemory.user_id == self.uid, UserMemory.memory_key == "agent_time_investment_pattern"))
            self.assertIn("10 分钟", memory.memory_value)

    async def test_unknown_actual_duration_does_not_become_planned_or_elapsed_minutes(self):
        async with self.sessions() as db:
            result = await start_pomodoro(PomodoroCreate(duration=50, started_at=NOW - timedelta(minutes=10)), db, self.actor)
            await complete_pomodoro(result.id, PomodoroUpdate(completed=True, ended_at=NOW), BackgroundTasks(), db, self.actor)
            await db.commit()
            report = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertIsNone(report.metrics["actual_minutes"])
            self.assertEqual(report.metrics["unknown_actual_duration_count"], 1)
            self.assertEqual(report.records[0].planned_minutes, 50)
            self.assertIsNone(report.records[0].actual_minutes)
            outcome = await db.scalar(select(LearningEvent).where(LearningEvent.event_type == "pomodoro.completed"))
            self.assertIsNone(outcome.duration)
            self.assertIsNone(outcome.event_data["duration"])

    async def test_older_offline_import_keeps_missing_plan_and_estimated_start_explicit(self):
        async with self.sessions() as db:
            body = PomodorosBatchCreate(records=[{"duration": 10, "client_record_id": "old-offline"}], completed_ats=[NOW])
            await batch_create_pomodoros(body, db, self.actor)
            await batch_create_pomodoros(body, db, self.actor)
            await db.commit()
            report = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertEqual(report.metrics["actual_minutes"], 10)
            self.assertEqual(report.metrics["finished_count"], 1)
            self.assertIsNone(report.records[0].planned_minutes)
            self.assertIsNone(report.records[0].started_at)
            self.assertIn("estimated_start_time", report.records[0].quality_flags)
            event = await db.scalar(select(LearningEvent).where(LearningEvent.event_type == "pomodoro.started"))
            self.assertIsNone(event.duration)
            self.assertIsNone(event.event_data["planned_duration"])

    async def test_demo_legacy_unknown_times_and_unfinished_rows_are_explicitly_excluded(self):
        async with self.sessions() as db:
            db.add(UserMemory(user_id=self.uid, memory_key="demo_mnemox_seeded", memory_value="seeded", category="system", status="ignored"))
            db.add_all([
                self.focus(record_origin="demo"), self.focus(record_origin="simulation"),
                self.focus(record_origin="legacy", note="Demo 专注记录"),
                self.focus(time_basis="legacy"), self.focus(ended_at=None, completed=False),
                self.focus(),
            ])
            await db.commit()
            report = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertEqual(report.metrics["finished_count"], 1)
            self.assertEqual(report.metrics["actual_minutes"], 25)
            self.assertEqual(report.quality_counts["synthetic_record"], 3)
            self.assertEqual(report.quality_counts["unknown_time_basis"], 1)
            self.assertEqual(report.quality_counts["unfinished_record"], 1)
            self.assertEqual(await db.scalar(select(func.count()).select_from(Pomodoro)), 6)

    async def test_long_real_session_is_retained_but_invalid_measurement_is_not_summed(self):
        async with self.sessions() as db:
            db.add_all([
                self.focus(started_at=NOW - timedelta(hours=5), actual_duration=240),
                self.focus(actual_duration=100),
                self.focus(actual_duration=-1),
                self.focus(started_at=NOW + timedelta(minutes=1)),
                self.focus(ended_at=NOW + timedelta(minutes=5)),
            ])
            await db.commit()
            report = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertEqual(report.metrics["actual_minutes"], 240)
            self.assertEqual(report.quality_counts["long_session_review"], 1)
            self.assertEqual(report.quality_counts["duration_exceeds_elapsed"], 2)
            self.assertEqual(report.quality_counts["invalid_actual_duration"], 1)
            self.assertEqual(report.metrics["unknown_actual_duration_count"], 2)

    async def test_shared_session_is_one_group_and_single_context_does_not_gain_certainty(self):
        async with self.sessions() as db:
            session = StudySession(user_id=self.uid)
            db.add(session)
            await db.flush()
            db.add_all([self.focus(session_id=session.id) for _ in range(40)])
            await db.commit()
            report = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertEqual(report.coverage["included_record_count"], 40)
            self.assertEqual(report.coverage["experience_group_count"], 1)
            self.assertIn("limited_task_context_coverage", report.limitations)
            self.assertEqual(report.assessment, "descriptive_only")

    async def test_source_version_changes_and_deleted_records_disappear_without_a_projection(self):
        async with self.sessions() as db:
            row = self.focus()
            db.add(row)
            await db.commit()
            first = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertEqual(first.model_dump(), (await get_behavior_evidence(db, self.uid, now=NOW)).model_dump())
            row.note = "我之前填错了背景"
            row.actual_duration = 15
            await db.commit()
            second = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertNotEqual(first.records[0].source.version, second.records[0].source.version)
            self.assertEqual(second.metrics["actual_minutes"], 15)
            row.actual_duration = None
            await db.flush()
            missing = await get_behavior_evidence(db, self.uid, now=NOW)
            row.actual_duration = -1
            await db.flush()
            invalid = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertNotEqual(missing.records[0].source.version, invalid.records[0].source.version)
            await db.delete(row)
            await db.commit()
            self.assertEqual((await get_behavior_evidence(db, self.uid, now=NOW)).records, [])

    async def test_task_context_and_records_cannot_cross_user_boundary(self):
        async with self.sessions() as db:
            goal = Goal(user_id=self.other, title="private goal")
            db.add(goal)
            await db.flush()
            task = Task(goal_id=goal.id, title="private task", task_type="secret")
            db.add(task)
            await db.flush()
            db.add_all([self.focus(task_id=task.id), self.focus(user_id=self.other)])
            await db.commit()
            report = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertEqual(len(report.records), 1)
            self.assertIsNone(report.records[0].task_type)
            self.assertIsNone(report.records[0].task_id)
            self.assertIn("unavailable_task_context", report.records[0].quality_flags)

    async def test_truncation_is_explicit_not_reported_as_complete_history(self):
        async with self.sessions() as db:
            db.add_all([self.focus() for _ in range(3)])
            await db.commit()
            with patch("app.services.behavior_evidence_service.MAX_FOCUS_RECORDS", 2):
                report = await get_behavior_evidence(db, self.uid, now=NOW)
            self.assertTrue(report.coverage["truncated"])
            self.assertEqual(report.metrics["finished_count"], 2)
            self.assertIn("record_limit_reached", report.limitations)

    async def test_recent_window_changes_without_turning_long_history_into_a_stable_trait(self):
        async with self.sessions() as db:
            old = NOW - timedelta(days=60, hours=4)
            db.add_all([self.focus(started_at=old - timedelta(minutes=25), ended_at=old) for _ in range(35)])
            db.add(self.focus())
            await db.commit()
            with patch("app.services.profile_service.utc_now_db", return_value=NOW):
                profile = await get_or_compute_profile(db, self.uid)
            self.assertEqual(profile.total_pomodoros, 36)
            summary = profile.recent_performance["focus_evidence"]
            self.assertEqual(summary["metrics"]["finished_count"], 1)
            self.assertEqual(summary["metrics"]["most_recorded_hour"], 9)
            self.assertEqual(summary["assessment"], "descriptive_only")
            self.assertTrue(profile.recent_performance["data_insufficient"])

    async def test_profile_rolls_over_at_local_midnight_even_inside_cache_ttl(self):
        async with self.sessions() as db:
            before = datetime(2026, 9, 28, 15, 55)
            with patch("app.services.profile_service.utc_now_db", return_value=before):
                profile = await get_or_compute_profile(db, self.uid)
            self.assertEqual(profile.recent_performance["dates"][-1], "2026-09-28")
            with patch("app.services.profile_service.utc_now_db", return_value=before + timedelta(minutes=10)):
                profile = await get_or_compute_profile(db, self.uid)
            self.assertEqual(profile.recent_performance["dates"][-1], "2026-09-29")

    async def test_profile_records_uncertainty_and_recomputes_old_or_timezone_stale_projection(self):
        async with self.sessions() as db:
            db.add_all([self.focus(), self.focus(actual_duration=None)])
            db.add(UserProfile(user_id=self.uid, last_updated=NOW, optimal_hours="20:00-22:00"))
            await db.commit()
            with patch("app.services.profile_service.utc_now_db", return_value=NOW):
                profile = await get_or_compute_profile(db, self.uid)
            self.assertEqual(profile.optimal_hours, "09:00-10:00")
            self.assertIsNone(profile.recent_performance["daily_hours"][0])
            self.assertEqual(profile.total_study_hours, round(25 / 60, 2))
            prompt = build_profile_prompt_snippet(profile)
            for forbidden in ("黄金学习时段", "专注度评分", "坚持度评分", "深度学习型", "至少 7 天"):
                self.assertNotIn(forbidden, prompt)
            self.assertIn("缺少可信实际时长：1 条", prompt)
            pref = await db.get(CoachPreference, self.uid)
            pref.time_zone = "America/New_York"
            await db.flush()
            snapshot = await build_learning_snapshot(db, self.uid, now=NOW)
            self.assertEqual(snapshot["profile"], {})
            self.assertEqual(snapshot["time_zone"], "America/New_York")
            with patch("app.services.profile_service.utc_now_db", return_value=NOW):
                profile = await get_or_compute_profile(db, self.uid)
            self.assertEqual(profile.recent_performance["time_zone"], "America/New_York")
            await db.rollback()

    async def test_http_evidence_is_read_only_user_scoped_and_bounds_window(self):
        async with self.sessions() as db:
            db.add_all([self.focus(), self.focus(user_id=self.other)])
            await db.commit()
        app = FastAPI()
        app.include_router(profile_router, prefix="/api/profile")
        async def override_db():
            async with self.sessions() as db:
                yield db
                await db.rollback()
        app.dependency_overrides[get_db] = override_db
        app.dependency_overrides[get_current_user] = lambda: self.actor
        async with AsyncClient(transport=ASGITransport(app=app), base_url="http://test") as client:
            with patch("app.services.behavior_evidence_service.utc_now_db", return_value=NOW):
                response = await client.get(f"/api/profile/evidence?days=1&user_id={self.other}")
            self.assertEqual(response.status_code, 200)
            self.assertEqual(response.json()["user_id"], self.uid)
            self.assertEqual(len(response.json()["records"]), 1)
            self.assertEqual((await client.get("/api/profile/evidence?days=10000")).status_code, 422)
        async with self.sessions() as db:
            self.assertEqual(await db.scalar(select(func.count()).select_from(UserProfile)), 0)

    async def test_recorded_time_is_server_owned_separate_from_occurrence(self):
        async with self.sessions() as db:
            with patch("app.services.learning_event_service.utc_now_db", return_value=NOW):
                event = await record_learning_event(db, self.uid, "pomodoro.completed", source="test",
                    occurred_at=NOW - timedelta(days=3), metadata={"recorded_at": "forged"})
            self.assertEqual(event["timestamp"], "2026-09-25T01:00:00Z")
            self.assertEqual(event["metadata"]["recorded_at"], "2026-09-28T01:00:00Z")

    async def test_demo_events_advance_checkpoint_without_creating_user_traits(self):
        async with self.sessions() as db:
            event = await record_learning_event(db, self.uid, "pomodoro.completed", source="test",
                payload={"demo": True, "duration_basis": "actual", "actual_duration": 25})
            result = await run_agent_memory_learning(db, self.uid, rebuild_profile=False)
            self.assertEqual(result["candidate_count"], 0)
            self.assertEqual(result["checkpoint"]["last_event_id"], event["id"])
