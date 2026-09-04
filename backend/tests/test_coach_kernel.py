import asyncio
import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.coach import CoachActionAttempt, CoachNudge, CoachPreference, CoachSkillStats
from app.models.agent import AgentExecutionLog, AgentJob
from app.models.daily_plan import DailyPlan
from app.models.goal import Goal, Task
from app.models.learning_event import LearningEvent
from app.models.memory import UserMemory
from app.models.note import Note
from app.models.question import ReviewSchedule
from app.models.user import User
from app.services.coach_action_service import create_coach_nudge, mark_coach_nudge_shown
from app.services.coach_action_attempt_service import (
    bind_coach_attempt_to_domain_event,
    get_coach_nudge_replay,
    start_coach_action_attempt,
)
from app.services.coach_event_service import record_coach_event
from app.services.coach_feedback_service import list_recent_coach_feedback, record_coach_feedback
from app.services.coach_learning_service import get_policy_skill_stats, list_skill_stats
from app.services.coach_policy_engine import default_coach_preferences, evaluate_coach_policy
from app.services.coach_runtime_service import run_proactive_review_debt_cycle
from app.services.agent_runtime_worker import AgentRuntimeWorker
from app.services.coach_context_retriever import retrieve_coach_context
from app.services.coach_preference_service import update_coach_preferences
from app.services.coach_skills.base import CoachSkillContext
from app.services.coach_skills.frustration_support import FrustrationSupportSkill
from app.services.coach_skills.low_motivation import LowMotivationSkill
from app.services.coach_skills.minimum_next_step import MinimumNextStepSkill
from app.services.coach_skills.planning_rescue import PlanningRescueSkill
from app.services.coach_skills.reflection_prompt import ReflectionPromptSkill
from app.services.coach_skills.registry import coach_skill_registry
from app.services.coach_workflow_service import advance_coach_workflow, list_coach_workflows, start_coach_workflow
from app.services.agent_service import execute_agent_write_draft
from app.services.learning_snapshot_service import build_learning_snapshot
from app.services.learning_event_service import CanonicalEventType, record_learning_event
from app.services.weekly_learning_report_service import build_weekly_learning_report


class CoachKernelTests(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "coach_kernel.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    async def _create_user(self, username: str) -> int:
        async with self.sessionmaker() as session:
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

    async def test_snapshot_filters_by_user(self):
        owner_id = await self._create_user("owner")
        other_id = await self._create_user("other")
        today = date.today()
        async with self.sessionmaker() as session:
            owner_goal = Goal(user_id=owner_id, title="Owner goal", status="active")
            other_goal = Goal(user_id=other_id, title="Other goal", status="active")
            session.add_all([owner_goal, other_goal])
            await session.flush()
            session.add_all(
                [
                    Task(goal_id=owner_goal.id, title="Owner task", planned_date=today, status="pending"),
                    Task(goal_id=other_goal.id, title="Other task", planned_date=today, status="pending"),
                ]
            )
            session.add(
                ReviewSchedule(
                    user_id=other_id,
                    item_type="chapter",
                    item_id=1,
                    scheduled_date=datetime.now() - timedelta(days=1),
                    status="pending",
                    is_archived=False,
                )
            )
            await session.commit()

        async with self.sessionmaker() as session:
            snapshot = await build_learning_snapshot(session, owner_id, include_memories=False)

        titles = [item["title"] for item in snapshot["tasks"]["today_tasks"]]
        self.assertEqual(titles, ["Owner task"])
        self.assertEqual(snapshot["review"]["due_review_count"], 0)

    async def test_snapshot_uses_the_learners_local_calendar_day(self):
        user_id = await self._create_user("snapshot-time-zone")
        async with self.sessionmaker() as session:
            snapshot = await build_learning_snapshot(
                session,
                user_id,
                include_memories=False,
                now=datetime(2026, 9, 1, 16, 30, 0),
                time_zone="Asia/Shanghai",
            )

        self.assertEqual(snapshot["date"], "2026-09-02")
        self.assertEqual(snapshot["time_zone"], "Asia/Shanghai")

    async def test_event_dedupe_prevents_polling_spam(self):
        user_id = await self._create_user("dedupe")
        async with self.sessionmaker() as session:
            first = await record_coach_event(
                session,
                user_id,
                "pomodoro.interrupted",
                "test",
                {"task_name": "Math"},
                dedupe_key="same-pomodoro",
            )
            second = await record_coach_event(
                session,
                user_id,
                "pomodoro.interrupted",
                "test",
                {"task_name": "Math"},
                dedupe_key="same-pomodoro",
            )
            await session.commit()

        self.assertEqual(first["id"], second["id"])

    async def test_proactive_runtime_creates_one_agent_panel_review_rescue(self):
        user_id = await self._create_user("runtime-review-debt")
        now = datetime.now().replace(microsecond=0)
        async with self.sessionmaker() as session:
            await update_coach_preferences(
                session,
                user_id,
                {
                    "enabled": True,
                    "proactive_enabled": True,
                    "allowed_channels": ["agent_panel"],
                    "min_minutes_between_nudges": 60,
                },
            )
            session.add_all(
                [
                    ReviewSchedule(
                        user_id=user_id,
                        item_type="chapter",
                        item_id=index,
                        scheduled_date=now - timedelta(days=1),
                        status="pending",
                        is_archived=False,
                    )
                    for index in range(1, 7)
                ]
            )
            await session.commit()

        async with self.sessionmaker() as session:
            created = await run_proactive_review_debt_cycle(session, user_id, now=now)
            await session.commit()

        self.assertEqual(created["status"], "nudge_created")
        self.assertEqual(created["nudge"]["skill_id"], "review_debt_rescue")
        self.assertEqual(created["nudge"]["channel"], "agent_panel")
        self.assertEqual(created["due_review_count"], 6)

        async with self.sessionmaker() as session:
            repeated = await run_proactive_review_debt_cycle(session, user_id, now=now + timedelta(minutes=5))
            rows = await session.execute(
                select(CoachNudge).where(CoachNudge.user_id == user_id)
            )
            count = len(rows.scalars().all())

        self.assertEqual(repeated["status"], "skipped")
        self.assertEqual(count, 1)

    async def test_weekly_report_stays_a_read_only_action_draft(self):
        user_id = await self._create_user("weekly-review")
        now = datetime.now().replace(microsecond=0)
        async with self.sessionmaker() as session:
            session.add(
                ReviewSchedule(
                    user_id=user_id,
                    item_type="chapter",
                    item_id=1,
                    scheduled_date=now - timedelta(days=1),
                    status="pending",
                    is_archived=False,
                )
            )
            await session.commit()

        async with self.sessionmaker() as session:
            report = await build_weekly_learning_report(session, user_id, now=now)

        self.assertIn("不会自动修改计划或创建任务", report["disclaimer"])
        self.assertTrue(any(step["route"] == "/review" for step in report["next_steps"]))

    async def test_runtime_worker_records_only_a_meaningful_nudge_job(self):
        user_id = await self._create_user("runtime-worker")
        now = datetime.now().replace(microsecond=0)
        async with self.sessionmaker() as session:
            await update_coach_preferences(
                session,
                user_id,
                {"proactive_enabled": True, "allowed_channels": ["agent_panel"]},
            )
            session.add_all(
                [
                    ReviewSchedule(
                        user_id=user_id,
                        item_type="chapter",
                        item_id=index,
                        scheduled_date=now - timedelta(days=1),
                        status="pending",
                        is_archived=False,
                    )
                    for index in range(1, 7)
                ]
            )
            await session.commit()

        worker = AgentRuntimeWorker(self.sessionmaker, poll_interval_seconds=30, batch_size=10)
        totals = await worker.run_once()
        self.assertEqual(totals, {"scanned": 1, "nudges_created": 1, "failed": 0})

        async with self.sessionmaker() as session:
            jobs = await session.execute(
                select(AgentJob).where(AgentJob.user_id == user_id)
            )
            job = jobs.scalar_one()
            logs = await session.execute(
                select(AgentExecutionLog).where(AgentExecutionLog.user_id == user_id)
            )
            log = logs.scalar_one()
        self.assertEqual(job.agent, "runtime")
        self.assertEqual(job.task, "review_debt_rescue")
        self.assertEqual(job.scenario, "review_debt_rescue_v1")
        self.assertEqual(job.attempt_count, 1)
        self.assertIsNotNone(job.finished_at)
        self.assertEqual(log.status, "completed")
        self.assertEqual(log.extra_metadata["scenario"], "review_debt_rescue_v1")

        # The poller may wake every 30 seconds, but the durable per-user
        # schedule prevents the same first batch of users from being scanned
        # repeatedly or starving later users.
        repeated = await worker.run_once()
        self.assertEqual(repeated, {"scanned": 0, "nudges_created": 0, "failed": 0})
        async with self.sessionmaker() as session:
            jobs = await session.execute(select(AgentJob).where(AgentJob.user_id == user_id))
        self.assertEqual(len(jobs.scalars().all()), 1)

    async def test_runtime_worker_records_a_safe_retry_notice_after_one_user_failure(self):
        user_id = await self._create_user("runtime-retry")
        async with self.sessionmaker() as session:
            await update_coach_preferences(
                session,
                user_id,
                {"proactive_enabled": True, "allowed_channels": ["agent_panel"]},
            )
            await session.commit()

        worker = AgentRuntimeWorker(self.sessionmaker, poll_interval_seconds=30, batch_size=10)
        with patch(
            "app.services.agent_runtime_worker.run_proactive_review_debt_cycle",
            new=AsyncMock(side_effect=RuntimeError("synthetic failure should not reach user history")),
        ):
            totals = await worker.run_once()

        self.assertEqual(totals, {"scanned": 1, "nudges_created": 0, "failed": 1})
        async with self.sessionmaker() as session:
            logs = await session.execute(
                select(AgentExecutionLog).where(AgentExecutionLog.user_id == user_id)
            )
            log = logs.scalar_one()
        self.assertEqual(log.status, "retrying")
        self.assertNotIn("synthetic failure", log.message)
        self.assertEqual(log.extra_metadata["retry"], "scheduled")
        self.assertEqual(log.extra_metadata["retry_in_seconds"], 900)
        async with self.sessionmaker() as session:
            jobs = await session.execute(select(AgentJob).where(AgentJob.user_id == user_id))
            job = jobs.scalar_one()
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.attempt_count, 1)
        self.assertEqual(job.result["retry_in_seconds"], 900)
        snapshot = worker.snapshot()
        self.assertEqual(snapshot["last_error_code"], "agent_runtime.worker_failed")
        self.assertRegex(snapshot["last_error_fingerprint"], r"^[0-9a-f]{16}$")
        self.assertNotIn("last_error", worker.health_snapshot())

    async def test_runtime_worker_defers_startup_catch_up_until_local_quiet_hours_end(self):
        user_id = await self._create_user("runtime-quiet-hours")
        async with self.sessionmaker() as session:
            preferences = await update_coach_preferences(
                session,
                user_id,
                {
                    "proactive_enabled": True,
                    "time_zone": "Asia/Shanghai",
                    "quiet_hours_start": "22:00",
                    "quiet_hours_end": "07:00",
                },
            )
            await session.commit()
        self.assertEqual(preferences["time_zone"], "Asia/Shanghai")

        worker = AgentRuntimeWorker(self.sessionmaker, poll_interval_seconds=30, batch_size=10)
        # 15:00 UTC is 23:00 in Shanghai. A missing next-evaluation timestamp
        # is a startup catch-up candidate, but quiet hours defer it to 07:00.
        totals = await worker.run_once(now=datetime(2026, 9, 1, 15, 0, 0))

        self.assertEqual(totals, {"scanned": 0, "nudges_created": 0, "failed": 0})
        self.assertEqual(worker.snapshot()["quiet_hours_deferred"], 1)
        async with self.sessionmaker() as session:
            preference = await session.get(CoachPreference, user_id)
            jobs = (
                await session.scalars(select(AgentJob).where(AgentJob.user_id == user_id))
            ).all()
        self.assertEqual(preference.proactive_next_evaluate_at, datetime(2026, 9, 1, 23, 0, 0))
        self.assertEqual(jobs, [])

    async def test_runtime_worker_times_out_one_user_and_schedules_safe_retry(self):
        user_id = await self._create_user("runtime-timeout")
        async with self.sessionmaker() as session:
            await update_coach_preferences(
                session,
                user_id,
                {"proactive_enabled": True, "allowed_channels": ["agent_panel"]},
            )
            await session.commit()

        async def slow_cycle(*_args, **_kwargs):
            await asyncio.sleep(0.1)
            return {"status": "skipped", "reason": "should_not_complete", "nudge": None}

        worker = AgentRuntimeWorker(
            self.sessionmaker,
            poll_interval_seconds=30,
            batch_size=10,
            user_timeout_seconds=0.02,
        )
        with patch(
            "app.services.agent_runtime_worker.run_proactive_review_debt_cycle",
            new=slow_cycle,
        ):
            totals = await worker.run_once(now=datetime(2026, 9, 1, 12, 0, 0))

        self.assertEqual(totals, {"scanned": 1, "nudges_created": 0, "failed": 1})
        self.assertEqual(worker.snapshot()["timed_out_users"], 1)
        async with self.sessionmaker() as session:
            jobs = (
                await session.scalars(select(AgentJob).where(AgentJob.user_id == user_id))
            ).all()
        self.assertEqual(len(jobs), 1)
        self.assertEqual(jobs[0].status, "failed")
        self.assertEqual(jobs[0].result["retry_in_seconds"], 900)

    async def test_coach_preferences_validate_time_zone_and_quiet_hour_format(self):
        user_id = await self._create_user("coach-time-zone")
        async with self.sessionmaker() as session:
            preferences = await update_coach_preferences(
                session,
                user_id,
                {
                    "time_zone": "America/New_York",
                    "quiet_hours_start": "21:30",
                    "quiet_hours_end": "06:45",
                },
            )
            self.assertEqual(preferences["time_zone"], "America/New_York")
            self.assertEqual(preferences["quiet_hours_start"], "21:30")
            with self.assertRaises(ValueError):
                await update_coach_preferences(session, user_id, {"time_zone": "not/a-zone"})
            with self.assertRaises(ValueError):
                await update_coach_preferences(session, user_id, {"quiet_hours_start": "25:00"})

    def test_policy_respects_cooldown_daily_cap_and_disabled_skill(self):
        event = {"event_type": "pomodoro.interrupted", "source": "pomodoro", "severity": "info", "payload": {}}
        prefs = default_coach_preferences()
        snapshot = {
            "generated_at": datetime.now().isoformat(),
            "review": {"due_review_count": 0},
            "risk_flags": {},
            "coach": {"today_nudge_count": 0, "last_nudge_at": None},
        }
        allowed = evaluate_coach_policy(event, snapshot, prefs, [])
        self.assertTrue(allowed["should_intervene"])
        self.assertEqual(allowed["skill_id"], "restart_after_interruption")
        self.assertEqual(allowed["channel"], "in_app_nudge")

        cooldown_snapshot = {
            **snapshot,
            "coach": {"today_nudge_count": 0, "last_nudge_at": datetime.now().isoformat()},
        }
        blocked = evaluate_coach_policy(event, cooldown_snapshot, prefs, [])
        self.assertFalse(blocked["should_intervene"])
        self.assertEqual(blocked["reason"], "cooldown_active")

        cap_snapshot = {**snapshot, "coach": {"today_nudge_count": 3, "last_nudge_at": None}}
        capped = evaluate_coach_policy(event, cap_snapshot, prefs, [])
        self.assertFalse(capped["should_intervene"])
        self.assertEqual(capped["reason"], "daily_cap_reached")

        disabled = evaluate_coach_policy(event, snapshot, {**prefs, "disabled_skill_ids": ["restart_after_interruption"]}, [])
        self.assertFalse(disabled["should_intervene"])
        self.assertEqual(disabled["reason"], "skill_disabled")

        chat_event = {"event_type": "chat.low_motivation_detected", "source": "chat", "severity": "info", "payload": {}}
        reactive = evaluate_coach_policy(chat_event, cap_snapshot, prefs, [])
        self.assertTrue(reactive["should_intervene"])
        self.assertEqual(reactive["channel"], "chat_inline")

    def test_policy_respects_snooze_and_quiet_hours(self):
        now = datetime.now().replace(hour=22, minute=30, second=0, microsecond=0)
        snapshot = {
            "generated_at": now.isoformat(),
            "review": {"due_review_count": 0},
            "risk_flags": {},
            "coach": {"today_nudge_count": 0, "last_nudge_at": None},
        }
        event = {"event_type": "pomodoro.interrupted", "source": "pomodoro", "severity": "info", "payload": {}}
        prefs = default_coach_preferences()

        snoozed = evaluate_coach_policy(
            event,
            snapshot,
            prefs,
            [
                {
                    "skill_id": "restart_after_interruption",
                    "outcome": "snoozed",
                    "snooze_until": (now + timedelta(hours=1)).isoformat(),
                }
            ],
        )
        self.assertFalse(snoozed["should_intervene"])
        self.assertEqual(snoozed["reason"], "snoozed")

        expired = evaluate_coach_policy(
            event,
            snapshot,
            prefs,
            [
                {
                    "skill_id": "restart_after_interruption",
                    "outcome": "snoozed",
                    "snooze_until": (now - timedelta(minutes=1)).isoformat(),
                }
            ],
        )
        self.assertTrue(expired["should_intervene"])

        desktop_prefs = {
            **prefs,
            "desktop_notifications_enabled": True,
            "allowed_channels": ["desktop_notification", "in_app_nudge"],
            "quiet_hours_start": "22:00",
            "quiet_hours_end": "07:00",
        }
        quiet = evaluate_coach_policy(
            {**event, "channel": "desktop_notification"},
            snapshot,
            desktop_prefs,
            [],
        )
        self.assertFalse(quiet["should_intervene"])
        self.assertEqual(quiet["reason"], "quiet_hours")

        shanghai_snapshot = {
            **snapshot,
            "generated_at": datetime(2026, 9, 1, 14, 30, 0).isoformat(),
        }
        local_quiet = evaluate_coach_policy(
            {**event, "channel": "desktop_notification"},
            shanghai_snapshot,
            {**desktop_prefs, "time_zone": "Asia/Shanghai"},
            [],
        )
        self.assertFalse(local_quiet["should_intervene"])
        self.assertEqual(local_quiet["reason"], "quiet_hours")

    async def test_low_motivation_skill_returns_deterministic_fallback(self):
        ctx = CoachSkillContext(
            user_id=1,
            event={"event_type": "chat.low_motivation_detected", "payload": {"text": "我学不进去了"}},
            snapshot={
                "tasks": {"today_tasks": [{"id": 1, "title": "复习线性代数"}]},
                "review": {"due_review_count": 0},
            },
            policy={"skill_id": "low_motivation"},
        )
        result = await LowMotivationSkill().generate(ctx)
        self.assertEqual(result.title, "先做最小一步")
        self.assertIn("10分钟", result.body)
        self.assertEqual(result.route, "/pomodoro")

    def test_phase2_policy_routes_emotional_and_planning_events(self):
        prefs = default_coach_preferences()
        snapshot = {
            "generated_at": datetime.now().isoformat(),
            "date": date.today().isoformat(),
            "tasks": {"overdue_task_count": 2, "overdue_tasks": [{"title": "补数学错题"}]},
            "daily_plan": {"has_content": False},
            "review": {"due_review_count": 0},
            "learning": {"today_completed_pomodoros": 0},
            "risk_flags": {"no_daily_plan": True},
            "coach": {"today_nudge_count": 0, "last_nudge_at": None},
        }

        cases = [
            ({"event_type": "chat.frustration_detected", "source": "chat", "payload": {"text": "我感觉自己很差"}, "severity": "warning"}, "frustration_support", "chat_inline"),
            ({"event_type": "chat.overload_detected", "source": "chat", "payload": {"text": "任务太多，不知道先做什么"}, "severity": "info"}, "minimum_next_step", "chat_inline"),
            ({"event_type": "app.evaluate", "source": "frontend", "payload": {}, "severity": "info"}, "planning_rescue", "in_app_nudge"),
            ({"event_type": "pomodoro.completed", "source": "pomodoro", "payload": {}, "severity": "info"}, "reflection_prompt", "in_app_nudge"),
        ]
        for event, skill_id, channel in cases:
            with self.subTest(skill_id=skill_id):
                policy = evaluate_coach_policy(event, snapshot, prefs, [])
                self.assertTrue(policy["should_intervene"])
                self.assertEqual(policy["skill_id"], skill_id)
                self.assertEqual(policy["channel"], channel)

    async def test_phase2_skills_return_deterministic_outputs(self):
        snapshot = {
            "date": date.today().isoformat(),
            "tasks": {
                "today_tasks": [{"id": 1, "title": "整理英语阅读错题", "task_type": "review"}],
                "overdue_tasks": [{"id": 2, "title": "补数学错题", "task_type": "practice"}],
            },
            "daily_plan": {"has_content": False},
            "review": {"due_review_count": 2},
            "learning": {"today_completed_pomodoros": 1},
        }
        base_event = {"event_type": "chat.overload_detected", "payload": {"text": "任务太多了"}}
        results = [
            await FrustrationSupportSkill().generate(CoachSkillContext(1, {"event_type": "chat.frustration_detected", "payload": {"text": "我感觉自己很差"}}, snapshot, {})),
            await PlanningRescueSkill().generate(CoachSkillContext(1, {"event_type": "plan.day_started_without_plan", "payload": {}}, snapshot, {})),
            await MinimumNextStepSkill().generate(CoachSkillContext(1, base_event, snapshot, {})),
            await ReflectionPromptSkill().generate(CoachSkillContext(1, {"event_type": "pomodoro.completed", "payload": {"task_name": "英语阅读"}}, snapshot, {})),
        ]
        self.assertEqual(results[0].route, "/review")
        self.assertTrue(results[1].requires_confirmation)
        self.assertEqual(results[1].draft["intent"], "add_daily_plan_items")
        self.assertEqual(results[2].route, "/review")
        self.assertEqual(results[3].suggested_action["type"], "ask_reflection")

    def test_phase2_skills_are_registered(self):
        skill_ids = {item["id"] for item in coach_skill_registry.list()}
        self.assertTrue(
            {
                "frustration_support",
                "planning_rescue",
                "minimum_next_step",
                "reflection_prompt",
            }.issubset(skill_ids)
        )

    async def test_context_retriever_returns_only_user_scoped_sources(self):
        owner_id = await self._create_user("ctx_owner")
        other_id = await self._create_user("ctx_other")
        async with self.sessionmaker() as session:
            session.add_all(
                [
                    Note(user_id=owner_id, title="线性代数复习", content="矩阵秩和线性相关容易混淆", note_type="review"),
                    Note(user_id=other_id, title="线性代数他人笔记", content="不应该被检索到", note_type="review"),
                    UserMemory(user_id=owner_id, memory_key="algebra_style", memory_value="线性代数需要先做小题再总结", category="style", status="active"),
                    UserMemory(user_id=other_id, memory_key="other_memory", memory_value="线性代数别人的记忆", category="style", status="active"),
                ]
            )
            await session.commit()

        event = {"event_type": "chat.overload_detected", "payload": {"text": "线性代数任务太多了"}}
        snapshot = {"tasks": {"today_tasks": [{"title": "线性代数复习"}]}, "review": {"due_review_items": []}}
        async with self.sessionmaker() as session:
            ctx = await retrieve_coach_context(session, owner_id, event, snapshot)

        titles = {source["title"] for source in ctx["sources"]}
        self.assertIn("线性代数复习", titles)
        self.assertIn("algebra_style", titles)
        self.assertNotIn("线性代数他人笔记", titles)
        self.assertIn("不可信上下文", ctx["wrapped_context"])

    async def test_skill_explainability_includes_retrieved_sources(self):
        snapshot = {
            "tasks": {"today_tasks": []},
            "review": {"due_review_count": 0},
            "coach_context": {
                "query_terms": ["英语"],
                "sources": [{"type": "note", "id": 1, "title": "英语复盘", "route": "/notes"}],
            },
        }
        result = await LowMotivationSkill().generate(
            CoachSkillContext(
                user_id=1,
                event={"event_type": "chat.low_motivation_detected", "payload": {"text": "英语学不进去"}},
                snapshot=snapshot,
                policy={},
            )
        )
        self.assertEqual(result.explainability["sources"][0]["title"], "英语复盘")

    async def test_feedback_updates_later_policy_context(self):
        user_id = await self._create_user("feedback")
        async with self.sessionmaker() as session:
            nudge = await create_coach_nudge(
                session,
                user_id,
                event_id=None,
                skill_id="restart_after_interruption",
                policy={"channel": "in_app_nudge", "priority": "medium", "reason": "policy_allowed"},
                result=await LowMotivationSkill().generate(
                    CoachSkillContext(
                        user_id=user_id,
                        event={"event_type": "chat.low_motivation_detected", "payload": {}},
                        snapshot={"tasks": {"today_tasks": []}, "review": {"due_review_count": 0}},
                        policy={},
                    )
                ),
            )
            await record_coach_feedback(session, user_id, nudge["id"], "too_disruptive")
            await session.commit()

        async with self.sessionmaker() as session:
            stored = (await session.execute(select(CoachNudge).where(CoachNudge.id == nudge["id"]))).scalar_one()
            feedback = await list_recent_coach_feedback(session, user_id)

        self.assertEqual(stored.status, "dismissed")
        self.assertEqual(feedback[0]["outcome"], "too_disruptive")
        self.assertEqual(feedback[0]["skill_id"], "restart_after_interruption")

    async def test_learning_stats_count_shown_and_feedback(self):
        user_id = await self._create_user("learning_stats")
        async with self.sessionmaker() as session:
            event = await record_coach_event(
                session,
                user_id,
                "pomodoro.interrupted",
                "pomodoro",
                {"task_name": "Math"},
            )
            nudge = await create_coach_nudge(
                session,
                user_id,
                event_id=event["id"],
                skill_id="restart_after_interruption",
                policy={"channel": "in_app_nudge", "priority": "medium", "reason": "policy_allowed"},
                result=await LowMotivationSkill().generate(
                    CoachSkillContext(
                        user_id=user_id,
                        event={"event_type": "chat.low_motivation_detected", "payload": {}},
                        snapshot={"tasks": {"today_tasks": []}, "review": {"due_review_count": 0}},
                        policy={},
                    )
                ),
            )
            await mark_coach_nudge_shown(session, user_id, nudge["id"])
            await mark_coach_nudge_shown(session, user_id, nudge["id"])
            feedback_result = await record_coach_feedback(session, user_id, nudge["id"], "too_disruptive")
            await session.commit()

        async with self.sessionmaker() as session:
            stored = (await session.execute(select(CoachSkillStats).where(CoachSkillStats.user_id == user_id))).scalar_one()
            stats = await list_skill_stats(session, user_id)

        self.assertEqual(stored.skill_id, "restart_after_interruption")
        self.assertEqual(stored.channel, "in_app_nudge")
        self.assertEqual(stored.event_type, "pomodoro.interrupted")
        self.assertEqual(stored.shown_count, 1)
        self.assertEqual(stored.too_disruptive_count, 1)
        self.assertLess(stored.recent_score, 0)
        self.assertEqual(stats[0]["too_disruptive_count"], 1)
        self.assertEqual(feedback_result["learning_stats"]["too_disruptive_count"], 1)

    async def test_action_lifecycle_records_started_and_abandoned_once(self):
        user_id = await self._create_user("action_lifecycle")
        async with self.sessionmaker() as session:
            nudge = await create_coach_nudge(
                session,
                user_id,
                event_id=None,
                skill_id="minimum_next_step",
                policy={"channel": "agent_panel", "priority": "medium", "reason": "policy_allowed"},
                result=await MinimumNextStepSkill().generate(
                    CoachSkillContext(
                        user_id=user_id,
                        event={"event_type": "chat.overload_detected", "payload": {"text": "任务太多"}},
                        snapshot={"tasks": {"today_tasks": []}, "review": {"due_review_count": 0}},
                        policy={},
                    )
                ),
            )
            await mark_coach_nudge_shown(session, user_id, nudge["id"])
            accepted = await record_coach_feedback(session, user_id, nudge["id"], "accepted")
            started = await record_coach_feedback(session, user_id, nudge["id"], "started")
            duplicate_started = await record_coach_feedback(session, user_id, nudge["id"], "started")
            abandoned = await record_coach_feedback(session, user_id, nudge["id"], "abandoned")
            duplicate_abandoned = await record_coach_feedback(session, user_id, nudge["id"], "abandoned")
            await session.commit()

        async with self.sessionmaker() as session:
            stored = (await session.execute(select(CoachNudge).where(CoachNudge.id == nudge["id"]))).scalar_one()
            stats = (await session.execute(select(CoachSkillStats).where(CoachSkillStats.user_id == user_id))).scalar_one()
            events = (await session.execute(
                select(LearningEvent.event_type).where(LearningEvent.user_id == user_id)
            )).scalars().all()

        self.assertEqual(accepted["status"], "accepted")
        self.assertEqual(started["status"], "started")
        self.assertTrue(duplicate_started["idempotent"])
        self.assertEqual(abandoned["status"], "abandoned")
        self.assertTrue(duplicate_abandoned["idempotent"])
        self.assertEqual(stored.status, "abandoned")
        self.assertEqual(stats.accepted_count, 1)
        self.assertEqual(stats.started_count, 1)
        self.assertEqual(stats.abandoned_count, 1)
        self.assertIn(CanonicalEventType.COACH_NUDGE_STARTED, events)
        self.assertIn(CanonicalEventType.COACH_NUDGE_ABANDONED, events)

    async def test_real_pomodoro_completion_closes_the_coach_attempt_with_evidence(self):
        user_id = await self._create_user("action_attribution")
        async with self.sessionmaker() as session:
            nudge = await create_coach_nudge(
                session,
                user_id,
                event_id=None,
                skill_id="restart_after_interruption",
                policy={"channel": "in_app_nudge", "priority": "medium", "reason": "policy_allowed"},
                result=await LowMotivationSkill().generate(
                    CoachSkillContext(
                        user_id=user_id,
                        event={"event_type": "chat.low_motivation_detected", "payload": {}},
                        snapshot={"tasks": {"today_tasks": []}, "review": {"due_review_count": 0}},
                        policy={},
                    )
                ),
            )
            await mark_coach_nudge_shown(session, user_id, nudge["id"])
            started = await start_coach_action_attempt(session, user_id, nudge["id"])
            attempt_id = started["attempt"]["id"]
            pomodoro_started = await record_learning_event(
                session,
                user_id,
                CanonicalEventType.POMODORO_STARTED,
                source="test",
                payload={"pomodoro_id": 99, "coach_action_attempt_id": attempt_id},
            )
            await bind_coach_attempt_to_domain_event(
                session,
                user_id,
                attempt_id,
                event_id=int(pomodoro_started["id"]),
                event_type=CanonicalEventType.POMODORO_STARTED,
            )
            pomodoro_completed = await record_learning_event(
                session,
                user_id,
                CanonicalEventType.POMODORO_COMPLETED,
                source="test",
                payload={"pomodoro_id": 99, "duration": 25, "coach_action_attempt_id": attempt_id},
                duration=25 * 60,
            )
            completed = await bind_coach_attempt_to_domain_event(
                session,
                user_id,
                attempt_id,
                event_id=int(pomodoro_completed["id"]),
                event_type=CanonicalEventType.POMODORO_COMPLETED,
                outcome="completed",
            )
            duplicate = await bind_coach_attempt_to_domain_event(
                session,
                user_id,
                attempt_id,
                event_id=int(pomodoro_completed["id"]),
                event_type=CanonicalEventType.POMODORO_COMPLETED,
                outcome="completed",
            )
            await session.commit()

        async with self.sessionmaker() as session:
            stored_nudge = await session.get(CoachNudge, nudge["id"])
            stored_attempt = await session.get(CoachActionAttempt, attempt_id)
            stats = (await session.execute(
                select(CoachSkillStats).where(CoachSkillStats.user_id == user_id)
            )).scalar_one()
            replay = await get_coach_nudge_replay(session, user_id, nudge["id"])

        self.assertFalse(started["idempotent"])
        self.assertEqual(completed["attempt"]["status"], "completed")
        self.assertTrue(duplicate["idempotent"])
        self.assertEqual(stored_nudge.status, "completed")
        self.assertEqual(stored_attempt.status, "completed")
        self.assertEqual(stored_attempt.outcome_source, "domain_event")
        self.assertEqual(stored_attempt.linked_event_id, int(pomodoro_completed["id"]))
        self.assertEqual(stats.shown_count, 1)
        self.assertEqual(stats.accepted_count, 1)
        self.assertEqual(stats.started_count, 1)
        self.assertEqual(stats.completed_count, 1)
        self.assertEqual(replay["attempts"][0]["id"], attempt_id)
        self.assertIn(CanonicalEventType.POMODORO_STARTED, [item["event_type"] for item in replay["timeline"]])
        self.assertIn(CanonicalEventType.POMODORO_COMPLETED, [item["event_type"] for item in replay["timeline"]])
        completed_lifecycle = [
            item for item in replay["timeline"]
            if item["event_type"] == CanonicalEventType.COACH_NUDGE_COMPLETED
        ]
        self.assertEqual(completed_lifecycle[0]["payload"]["attribution"]["method"], "domain_event")

    async def test_confirmed_plan_draft_closes_the_coach_attempt_with_evidence(self):
        user_id = await self._create_user("plan_action_attribution")
        today = date.today().isoformat()
        async with self.sessionmaker() as session:
            nudge = await create_coach_nudge(
                session,
                user_id,
                event_id=None,
                skill_id="planning_rescue",
                policy={"channel": "in_app_nudge", "priority": "medium", "reason": "policy_allowed"},
                result=await PlanningRescueSkill().generate(
                    CoachSkillContext(
                        user_id=user_id,
                        event={"event_type": "app.evaluate", "payload": {}},
                        snapshot={
                            "date": today,
                            "tasks": {"today_tasks": []},
                            "daily_plan": {"has_content": False},
                            "review": {"due_review_count": 0},
                        },
                        policy={},
                    )
                ),
            )
            await mark_coach_nudge_shown(session, user_id, nudge["id"])
            started = await start_coach_action_attempt(session, user_id, nudge["id"])
            attempt_id = started["attempt"]["id"]
            nudge_row = await session.get(CoachNudge, nudge["id"])
            write_result = await execute_agent_write_draft(
                session,
                user_id,
                "add_daily_plan_items",
                dict(nudge_row.draft or {}),
            )
            plan = (write_result.get("created") or {}).get("plan") or {}
            plan_event = await record_learning_event(
                session,
                user_id,
                "daily_plan.updated",
                source="test",
                payload={
                    "date": plan.get("date"),
                    "coach_nudge_id": nudge["id"],
                    "coach_action_attempt_id": attempt_id,
                },
            )
            completed = await bind_coach_attempt_to_domain_event(
                session,
                user_id,
                attempt_id,
                event_id=int(plan_event["id"]),
                event_type="daily_plan.updated",
                outcome="completed",
                reason="draft_confirmed",
            )
            await session.commit()

        async with self.sessionmaker() as session:
            stored_nudge = await session.get(CoachNudge, nudge["id"])
            stored_attempt = await session.get(CoachActionAttempt, attempt_id)
            plan_row = await session.scalar(
                select(DailyPlan).where(DailyPlan.user_id == user_id, DailyPlan.date == plan["date"])
            )

        self.assertTrue(started["attempt"]["id"])
        self.assertEqual(completed["attempt"]["status"], "completed")
        self.assertEqual(stored_nudge.status, "completed")
        self.assertEqual(stored_attempt.outcome_source, "domain_event")
        self.assertEqual(stored_attempt.linked_event_type, "daily_plan.updated")
        self.assertIsNotNone(plan_row)
        self.assertIn("[ ]", plan_row.content)

    def test_policy_suppresses_learned_disruptive_proactive_nudges(self):
        now = datetime.now()
        event = {"event_type": "pomodoro.interrupted", "source": "pomodoro", "severity": "info", "payload": {}}
        snapshot = {
            "generated_at": now.isoformat(),
            "review": {"due_review_count": 0},
            "risk_flags": {},
            "coach": {"today_nudge_count": 0, "last_nudge_at": None},
        }
        prefs = default_coach_preferences()
        skill_stats = [
            {
                "skill_id": "restart_after_interruption",
                "channel": "in_app_nudge",
                "event_type": "pomodoro.interrupted",
                "shown_count": 2,
                "too_disruptive_count": 2,
                "recent_score": -2.5,
            }
        ]

        blocked = evaluate_coach_policy(event, snapshot, prefs, [], skill_stats)

        self.assertFalse(blocked["should_intervene"])
        self.assertEqual(blocked["reason"], "learned_disruption_feedback")

    async def test_recorded_learning_stats_feed_policy(self):
        user_id = await self._create_user("policy_learning")
        async with self.sessionmaker() as session:
            event = await record_coach_event(
                session,
                user_id,
                "pomodoro.interrupted",
                "pomodoro",
                {"task_name": "Math"},
            )
            for index in range(2):
                nudge = await create_coach_nudge(
                    session,
                    user_id,
                    event_id=event["id"],
                    skill_id="restart_after_interruption",
                    policy={"channel": "in_app_nudge", "priority": "medium", "reason": "policy_allowed"},
                    result=await LowMotivationSkill().generate(
                        CoachSkillContext(
                            user_id=user_id,
                            event={"event_type": "chat.low_motivation_detected", "payload": {"index": index}},
                            snapshot={"tasks": {"today_tasks": []}, "review": {"due_review_count": 0}},
                            policy={},
                        )
                    ),
                )
                await mark_coach_nudge_shown(session, user_id, nudge["id"])
                await record_coach_feedback(session, user_id, nudge["id"], "too_disruptive")
            await session.commit()

        async with self.sessionmaker() as session:
            skill_stats = await get_policy_skill_stats(session, user_id)

        policy = evaluate_coach_policy(
            {"event_type": "pomodoro.interrupted", "source": "pomodoro", "severity": "info", "payload": {}},
            {
                "generated_at": datetime.now().isoformat(),
                "review": {"due_review_count": 0},
                "risk_flags": {},
                "coach": {"today_nudge_count": 0, "last_nudge_at": None},
            },
            default_coach_preferences(),
            [],
            skill_stats,
        )
        self.assertFalse(policy["should_intervene"])
        self.assertEqual(policy["reason"], "learned_disruption_feedback")

    async def test_snooze_feedback_records_snooze_until(self):
        user_id = await self._create_user("snooze")
        async with self.sessionmaker() as session:
            nudge = await create_coach_nudge(
                session,
                user_id,
                event_id=None,
                skill_id="restart_after_interruption",
                policy={"channel": "in_app_nudge", "priority": "medium", "reason": "policy_allowed"},
                result=await LowMotivationSkill().generate(
                    CoachSkillContext(
                        user_id=user_id,
                        event={"event_type": "chat.low_motivation_detected", "payload": {}},
                        snapshot={"tasks": {"today_tasks": []}, "review": {"due_review_count": 0}},
                        policy={},
                    )
                ),
            )
            await record_coach_feedback(session, user_id, nudge["id"], "later")
            await session.commit()

        async with self.sessionmaker() as session:
            stored = (await session.execute(select(CoachNudge).where(CoachNudge.id == nudge["id"]))).scalar_one()
            feedback = await list_recent_coach_feedback(session, user_id)

        self.assertEqual(stored.status, "snoozed")
        self.assertEqual(feedback[0]["outcome"], "later")
        self.assertIsNotNone(feedback[0].get("snooze_until"))

    async def test_accepted_and_completed_feedback_are_idempotent(self):
        user_id = await self._create_user("idempotent_feedback")
        async with self.sessionmaker() as session:
            nudge = await create_coach_nudge(
                session,
                user_id,
                event_id=None,
                skill_id="association_recall",
                policy={"channel": "agent_panel", "priority": "medium", "reason": "explicit_association_request"},
                result=await LowMotivationSkill().generate(
                    CoachSkillContext(
                        user_id=user_id,
                        event={"event_type": "app.evaluate", "payload": {}},
                        snapshot={"tasks": {"today_tasks": []}, "review": {"due_review_count": 0}},
                        policy={},
                    )
                ),
            )
            first_accepted = await record_coach_feedback(session, user_id, nudge["id"], "accepted")
            duplicate_accepted = await record_coach_feedback(session, user_id, nudge["id"], "accepted")
            first_completed = await record_coach_feedback(session, user_id, nudge["id"], "completed")
            duplicate_completed = await record_coach_feedback(session, user_id, nudge["id"], "completed")
            await session.commit()

        async with self.sessionmaker() as session:
            stored = (
                await session.execute(select(CoachNudge).where(CoachNudge.id == nudge["id"]))
            ).scalar_one()
            stats = (
                await session.execute(
                    select(CoachSkillStats).where(
                        CoachSkillStats.user_id == user_id,
                        CoachSkillStats.skill_id == "association_recall",
                    )
                )
            ).scalar_one()
            feedback = await list_recent_coach_feedback(session, user_id)

        self.assertEqual(stored.status, "completed")
        self.assertFalse(first_accepted.get("idempotent", False))
        self.assertTrue(duplicate_accepted["idempotent"])
        self.assertFalse(first_completed.get("idempotent", False))
        self.assertTrue(duplicate_completed["idempotent"])
        self.assertEqual(stats.accepted_count, 1)
        self.assertEqual(stats.completed_count, 1)
        self.assertEqual(len(feedback), 2)

    async def test_shown_event_cannot_revert_a_completed_nudge(self):
        user_id = await self._create_user("shown_after_completion")
        async with self.sessionmaker() as session:
            nudge = await create_coach_nudge(
                session,
                user_id,
                event_id=None,
                skill_id="association_recall",
                policy={"channel": "agent_panel", "priority": "medium", "reason": "explicit_association_request"},
                result=await LowMotivationSkill().generate(
                    CoachSkillContext(
                        user_id=user_id,
                        event={"event_type": "app.evaluate", "payload": {}},
                        snapshot={"tasks": {"today_tasks": []}, "review": {"due_review_count": 0}},
                        policy={},
                    )
                ),
            )
            await record_coach_feedback(session, user_id, nudge["id"], "completed")
            shown = await mark_coach_nudge_shown(session, user_id, nudge["id"])
            await session.commit()

        self.assertEqual(shown["status"], "completed")

    async def test_phase5_workflows_are_user_scoped_and_durable(self):
        owner_id = await self._create_user("workflow_owner")
        other_id = await self._create_user("workflow_other")
        async with self.sessionmaker() as session:
            workflow = await start_coach_workflow(
                session,
                owner_id,
                "weekly_review_planning",
                state={"week": "2026-W25"},
                pending_draft={"intent": "add_daily_plan_items"},
            )
            reused = await start_coach_workflow(
                session,
                owner_id,
                "weekly_review_planning",
                state={"ignored": True},
            )
            other = await start_coach_workflow(session, other_id, "weekly_review_planning")
            await session.commit()

        self.assertEqual(workflow["id"], reused["id"])
        self.assertNotEqual(workflow["id"], other["id"])

        async with self.sessionmaker() as session:
            owner_items = await list_coach_workflows(session, owner_id)
            other_items = await list_coach_workflows(session, other_id)
            advanced = await advance_coach_workflow(
                session,
                owner_id,
                workflow["id"],
                action="advance",
                payload={"confirmed": False},
            )
            completed = await advance_coach_workflow(
                session,
                owner_id,
                workflow["id"],
                action="complete",
                status="completed",
                payload={"user_confirmed": True},
            )
            with self.assertRaises(ValueError):
                await advance_coach_workflow(session, owner_id, workflow["id"], action="advance")

        self.assertEqual(len(owner_items), 1)
        self.assertEqual(len(other_items), 1)
        self.assertEqual(advanced["current_step"], "draft_plan")
        self.assertEqual(completed["status"], "completed")
        self.assertIsNotNone(completed["completed_at"])


if __name__ == "__main__":
    unittest.main()
