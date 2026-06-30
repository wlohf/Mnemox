import tempfile
import unittest
from datetime import date, datetime, timedelta
from pathlib import Path

from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.database import Base
from app.models.coach import CoachNudge, CoachSkillStats
from app.models.goal import Goal, Task
from app.models.memory import UserMemory
from app.models.note import Note
from app.models.question import ReviewSchedule
from app.models.user import User
from app.services.coach_action_service import create_coach_nudge, mark_coach_nudge_shown
from app.services.coach_event_service import record_coach_event
from app.services.coach_feedback_service import list_recent_coach_feedback, record_coach_feedback
from app.services.coach_learning_service import get_policy_skill_stats, list_skill_stats
from app.services.coach_policy_engine import default_coach_preferences, evaluate_coach_policy
from app.services.coach_context_retriever import retrieve_coach_context
from app.services.coach_skills.base import CoachSkillContext
from app.services.coach_skills.frustration_support import FrustrationSupportSkill
from app.services.coach_skills.low_motivation import LowMotivationSkill
from app.services.coach_skills.minimum_next_step import MinimumNextStepSkill
from app.services.coach_skills.planning_rescue import PlanningRescueSkill
from app.services.coach_skills.reflection_prompt import ReflectionPromptSkill
from app.services.coach_skills.registry import coach_skill_registry
from app.services.coach_workflow_service import advance_coach_workflow, list_coach_workflows, start_coach_workflow
from app.services.learning_snapshot_service import build_learning_snapshot


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
