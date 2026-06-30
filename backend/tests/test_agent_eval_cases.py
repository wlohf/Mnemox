import json
import os
import tempfile
import unittest
from datetime import date, datetime
from pathlib import Path
from typing import Any
from unittest.mock import patch

from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.base import AgentRunContext
from app.agents.chat_agent import ChatAgent
from app.database import Base
from app.models.coach import CoachSkillStats
from app.models.daily_plan import DailyPlan
from app.models.goal import Goal, Task
from app.models.learning_event import LearningEvent
from app.models.memory import UserMemory
from app.models.note import Note, NoteLink
from app.models.user import User
from app.services.agent_service import _heuristic_write_intent, build_agent_write_draft, execute_agent_write_draft
from app.services.coach_policy_engine import default_coach_preferences, evaluate_coach_policy
from app.services.goal_context_service import build_goal_context


FIXTURE_PATH = Path(__file__).parent / "fixtures" / "agent_eval_cases.json"


def _load_fixture() -> dict[str, Any]:
    return json.loads(FIXTURE_PATH.read_text(encoding="utf-8"))


def _today() -> date:
    return date.fromisoformat(_load_fixture()["defaults"]["today"])


def _now() -> datetime:
    return datetime.fromisoformat(_load_fixture()["defaults"]["now"])


class FixedEvalDate(date):
    @classmethod
    def today(cls) -> date:
        return _today()


def _assert_contains(testcase: unittest.TestCase, haystack: list[str], needles: list[str] | None) -> None:
    for needle in needles or []:
        testcase.assertIn(needle, haystack)


def _assert_excludes(testcase: unittest.TestCase, haystack: list[str], needles: list[str] | None) -> None:
    for needle in needles or []:
        testcase.assertNotIn(needle, haystack)


class AgentEvalCasesTests(unittest.IsolatedAsyncioTestCase):
    @classmethod
    def setUpClass(cls):
        cls.fixture = _load_fixture()
        cls.cases = cls.fixture["cases"]

    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        self.db_path = Path(self.tmpdir.name) / "agent_eval_cases.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{self.db_path}", future=True)
        async with self.engine.begin() as conn:
            await conn.run_sync(Base.metadata.create_all)
        self.sessionmaker = async_sessionmaker(self.engine, expire_on_commit=False)

    async def asyncTearDown(self):
        await self.engine.dispose()
        self.tmpdir.cleanup()

    def test_fixture_has_required_coverage(self):
        self.assertGreaterEqual(len(self.cases), 30)
        categories = {case["category"] for case in self.cases}
        self.assertTrue(
            {
                "goal_creation",
                "daily_plan",
                "note_creation",
                "non_write_question",
                "duplicate_detection",
                "goal_context_selection",
                "memory_retrieval",
                "user_isolation",
                "prompt_injection",
                "coach_feedback_suppression",
            }.issubset(categories)
        )
        ids = [case["id"] for case in self.cases]
        self.assertEqual(len(ids), len(set(ids)))

    def test_heuristic_cases_are_deterministic_without_llm(self):
        for case in self.cases:
            if case["evaluator"] not in {"write_draft", "write_execute"} or case.get("seed"):
                continue
            with self.subTest(case=case["id"]):
                result = _heuristic_write_intent(case["message"], _today())
                self.assertEqual(result["intent"], case["expected"]["intent"])

    async def test_eval_cases(self):
        if os.environ.get("MNEMOX_AGENT_EVAL_USE_LLM") == "1":
            self.skipTest("LLM-assisted eval is intentionally manual; deterministic cases run when env var is unset.")

        for case in self.cases:
            with self.subTest(case=case["id"]):
                await self._run_case(case)

    async def _run_case(self, case: dict[str, Any]) -> None:
        async with self.sessionmaker() as session:
            user_id, key_maps = await self._seed_case(session, case["id"], case.get("seed") or {})
            evaluator = case["evaluator"]
            if evaluator == "write_draft":
                with patch("app.services.agent_service.date", FixedEvalDate):
                    result = await build_agent_write_draft(session, user_id, case["message"])
                self._assert_write_draft(case, result)
            elif evaluator == "write_execute":
                with patch("app.services.agent_service.date", FixedEvalDate):
                    draft = await build_agent_write_draft(session, user_id, case["message"])
                    result = await execute_agent_write_draft(session, user_id, draft["intent"], draft["draft"])
                await session.commit()
                self._assert_write_execute(case, draft, result)
            elif evaluator == "goal_context":
                goal_id = None
                input_data = case.get("input") or {}
                if input_data.get("goal_key"):
                    goal_id = key_maps["goals"][input_data["goal_key"]]
                result = await build_goal_context(session, user_id, goal_id=goal_id, now=_now())
                self._assert_goal_context(case, result)
            elif evaluator == "chat_tool":
                with patch("app.agents.chat_agent.date", FixedEvalDate):
                    result = await ChatAgent().call_tool(
                        AgentRunContext(db=session, user_id=user_id),
                        tool=case["tool"],
                        query=case.get("query") or "",
                        limit=5,
                    )
                self._assert_chat_tool(case, result)
            elif evaluator == "coach_policy":
                result = evaluate_coach_policy(
                    (case.get("input") or {}).get("event") or {},
                    self._policy_snapshot(),
                    default_coach_preferences(),
                    (case.get("input") or {}).get("recent_feedback") or [],
                    self._seeded_policy_stats(case.get("seed") or {}),
                )
                self._assert_coach_policy(case, result)
            else:
                self.fail(f"unsupported evaluator {evaluator!r}")

    async def _create_user(self, session, username: str) -> int:
        user = User(username=username, email=f"{username}@example.com", hashed_password="hash", is_active=True)
        session.add(user)
        await session.flush()
        return int(user.id)

    async def _seed_case(self, session, case_id: str, seed: dict[str, Any]) -> tuple[int, dict[str, dict[str, int]]]:
        suffix = "".join(ch if ch.isalnum() else "_" for ch in case_id)[:60]
        user_id = await self._create_user(session, f"owner_{suffix}")
        maps = {"goals": {}, "notes": {}}
        await self._seed_for_user(session, user_id, seed, maps)
        other_seed = seed.get("other_user")
        if isinstance(other_seed, dict):
            other_id = await self._create_user(session, f"other_{suffix}")
            other_maps = {"goals": {}, "notes": {}}
            await self._seed_for_user(session, other_id, other_seed, other_maps)
        await session.commit()
        return user_id, maps

    async def _seed_for_user(self, session, user_id: int, seed: dict[str, Any], maps: dict[str, dict[str, int]]) -> None:
        for item in seed.get("daily_plans") or []:
            session.add(DailyPlan(user_id=user_id, date=item["date"], content=item["content"]))

        for item in seed.get("goals") or []:
            goal = Goal(
                user_id=user_id,
                title=item["title"],
                description=item.get("description"),
                status=item.get("status", "active"),
                deadline=date.fromisoformat(item["deadline"]) if item.get("deadline") else None,
            )
            session.add(goal)
            await session.flush()
            if item.get("key"):
                maps["goals"][item["key"]] = int(goal.id)

        for item in seed.get("tasks") or []:
            goal_id = maps["goals"][item["goal_key"]]
            session.add(
                Task(
                    goal_id=goal_id,
                    title=item["title"],
                    description=item.get("description"),
                    task_type=item.get("task_type", "learn"),
                    planned_date=date.fromisoformat(item["planned_date"]) if item.get("planned_date") else None,
                    status=item.get("status", "pending"),
                )
            )

        for item in seed.get("notes") or []:
            note = Note(
                user_id=user_id,
                title=item["title"],
                content=item.get("content", ""),
                note_type=item.get("note_type", "general"),
                tags=json.dumps(item.get("tags", []), ensure_ascii=False),
            )
            session.add(note)
            await session.flush()
            if item.get("key"):
                maps["notes"][item["key"]] = int(note.id)

        for item in seed.get("note_links") or []:
            link_id = maps["goals"][item["goal_key"]] if item.get("goal_key") else int(item["link_id"])
            session.add(NoteLink(note_id=maps["notes"][item["note_key"]], link_type=item["link_type"], link_id=link_id))

        for item in seed.get("memories") or []:
            session.add(
                UserMemory(
                    user_id=user_id,
                    memory_key=item["key"],
                    memory_value=item["value"],
                    category=item.get("category", "preference"),
                    confidence=item.get("confidence", 0.7),
                    status=item.get("status", "active"),
                    memory_type=item.get("memory_type", "semantic"),
                )
            )

        for item in seed.get("events") or []:
            session.add(
                LearningEvent(
                    user_id=user_id,
                    event_type=item["event_type"],
                    event_category=item.get("event_category", "agent"),
                    source=item.get("source", "test"),
                    event_data=item.get("payload", {}),
                    goal_id=maps["goals"].get(item.get("goal_key")),
                    timestamp=_now(),
                )
            )

        for item in seed.get("coach_skill_stats") or []:
            session.add(
                CoachSkillStats(
                    user_id=user_id,
                    skill_id=item["skill_id"],
                    channel=item.get("channel", ""),
                    event_type=item.get("event_type", ""),
                    shown_count=item.get("shown_count", 0),
                    too_disruptive_count=item.get("too_disruptive_count", 0),
                    recent_score=item.get("recent_score", 0.0),
                )
            )

    def _assert_write_draft(self, case: dict[str, Any], result: dict[str, Any]) -> None:
        expected = case["expected"]
        self.assertEqual(result["intent"], expected["intent"])
        self.assertEqual(bool(result.get("requires_confirmation")), bool(expected.get("requires_confirmation", False)))
        draft = result.get("draft") or {}
        if "goal_title" in expected:
            self.assertEqual(draft.get("goal_title"), expected["goal_title"])
        if expected.get("existing_goal"):
            self.assertTrue(draft.get("existing_goal_id"))
        if "date" in expected:
            self.assertEqual(draft.get("date"), expected["date"])
        if "note_type" in expected:
            self.assertEqual(draft.get("note_type"), expected["note_type"])
        if "title_contains" in expected:
            self.assertIn(expected["title_contains"], draft.get("title", ""))
        if "content_contains" in expected:
            self.assertIn(expected["content_contains"], draft.get("content", ""))
        _assert_contains(self, [item.get("title") for item in draft.get("tasks") or []], expected.get("task_titles_include"))
        _assert_contains(self, [item.get("title") for item in draft.get("items") or []], expected.get("item_titles_include"))
        _assert_contains(self, draft.get("tags") or [], expected.get("tags_include"))

    def _assert_write_execute(self, case: dict[str, Any], draft: dict[str, Any], result: dict[str, Any]) -> None:
        expected = case["expected"]
        self.assertEqual(draft["intent"], expected["intent"])
        self.assertEqual(result["status"], expected["status"])
        created = result.get("created") or {}
        if expected.get("duplicate_note"):
            self.assertTrue((draft.get("draft") or {}).get("duplicate_note_id"))
        if "created_count" in expected:
            self.assertEqual(len(created.get("items") or []), expected["created_count"])
        if "skipped_count" in expected:
            skipped = created.get("skipped_items") or created.get("skipped_tasks") or []
            self.assertEqual(len(skipped), expected["skipped_count"])
        if "created_note_title_contains" in expected:
            self.assertIn(expected["created_note_title_contains"], (created.get("note") or {}).get("title", ""))

    def _assert_goal_context(self, case: dict[str, Any], result: dict[str, Any]) -> None:
        expected = case["expected"]
        active_goal = result.get("active_goal")
        self.assertEqual(active_goal.get("title") if active_goal else None, expected.get("active_goal_title"))
        focus = result.get("today_focus") or {}
        if "today_focus_title" in expected:
            self.assertEqual(focus.get("title"), expected["today_focus_title"])
        if "today_focus_action_id" in expected:
            self.assertEqual(focus.get("action_id"), expected["today_focus_action_id"])
        if "requires_confirmation" in expected:
            self.assertEqual(bool(focus.get("requires_confirmation")), expected["requires_confirmation"])
        note_titles = [item["title"] for item in ((result.get("supporting_context") or {}).get("notes") or [])]
        _assert_contains(self, note_titles, expected.get("note_titles_include"))
        _assert_excludes(self, note_titles, expected.get("note_titles_exclude"))

    def _assert_chat_tool(self, case: dict[str, Any], result: dict[str, Any]) -> None:
        expected = case["expected"]
        self.assertEqual(result["tool"], expected["tool"])
        items = result.get("items") or []
        titles = [item.get("title") for item in items]
        keys = [item.get("key") for item in items]
        values = [item.get("value_preview", "") for item in items]
        _assert_contains(self, titles, expected.get("item_titles_include"))
        _assert_excludes(self, titles, expected.get("item_titles_exclude"))
        _assert_contains(self, keys, expected.get("item_keys_include"))
        _assert_excludes(self, keys, expected.get("item_keys_exclude"))
        for value in expected.get("values_include") or []:
            self.assertTrue(any(value in item for item in values))
        if "profile_summary_contains" in expected:
            self.assertIn(expected["profile_summary_contains"], json.dumps(result.get("profile"), ensure_ascii=False))
        if "feedback_outcomes_include" in expected:
            outcomes = [item.get("outcome") for item in items]
            _assert_contains(self, outcomes, expected["feedback_outcomes_include"])
        if "feedback_reason_codes_include" in expected:
            reason_codes = [item.get("reason_code") for item in items]
            _assert_contains(self, reason_codes, expected["feedback_reason_codes_include"])

    def _assert_coach_policy(self, case: dict[str, Any], result: dict[str, Any]) -> None:
        expected = case["expected"]
        self.assertEqual(result.get("should_intervene"), expected["should_intervene"])
        for key in ("reason", "skill_id", "channel"):
            if key in expected:
                self.assertEqual(result.get(key), expected[key])

    def _policy_snapshot(self) -> dict[str, Any]:
        return {
            "generated_at": _now().isoformat(),
            "date": _today().isoformat(),
            "review": {"due_review_count": 0},
            "risk_flags": {},
            "coach": {"today_nudge_count": 0, "last_nudge_at": None},
        }

    def _seeded_policy_stats(self, seed: dict[str, Any]) -> list[dict[str, Any]]:
        return [
            {
                "skill_id": item["skill_id"],
                "channel": item.get("channel", ""),
                "event_type": item.get("event_type", ""),
                "shown_count": item.get("shown_count", 0),
                "too_disruptive_count": item.get("too_disruptive_count", 0),
                "recent_score": item.get("recent_score", 0.0),
            }
            for item in seed.get("coach_skill_stats") or []
        ]


if __name__ == "__main__":
    unittest.main()
