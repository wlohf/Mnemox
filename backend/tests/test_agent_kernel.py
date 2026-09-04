"""AgentKernel 多步工具循环测试（决策 D4）。"""
import json
import tempfile
import unittest
from datetime import datetime, timedelta
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from pydantic import ValidationError
from sqlalchemy import select
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.agent_kernel import (
    build_kernel_system_prompt,
    parse_kernel_decision,
    run_agent_kernel,
)
from app.agents.manager import agent_manager
from app.config import settings
from app.database import Base
from app.models.agent import AgentActionConfirmation, AgentExecutionLog, AgentJob
from app.models.goal import Goal, Task
from app.models.learning_event import LearningEvent
from app.models.note import Note
from app.models.user import User
from app.routers.agent import (
    AgentKernelActionConfirmRequest,
    AgentKernelRunRequest,
    AgentTaskTriggerRequest,
    cancel_agent_job,
    confirm_kernel_job_action,
    draft_kernel_job_action,
    get_agent_job_replay,
    prepare_kernel_job,
    run_kernel,
    stream_agent_job_events,
    trigger_agent_task,
)
from app.services.agent_job_recovery_service import recover_expired_agent_kernel_jobs
from app.services.agent_budget_service import get_agent_kernel_daily_budget

FINISH_REPLY = json.dumps(
    {
        "action": "finish",
        "strategy": "先清最旧复习，再做一轮短专注",
        "fallback_plan": "只做10分钟启动",
        "next_actions": [
            {
                "id": "a1",
                "title": "完成1条最旧复习",
                "reason": "复习积压最高",
                "action_type": "review",
                "priority": "high",
                "estimated_minutes": 15,
                "route": "/review",
            }
        ],
    },
    ensure_ascii=False,
)


class ScriptedProvider:
    """按脚本依次返回回复，并记录每次收到的 messages。"""

    def __init__(self, replies):
        self.replies = list(replies)
        self.calls: list[list[dict]] = []

    async def chat(self, messages=None, system_prompt=None, temperature=None, **kwargs):
        self.calls.append(list(messages or []))
        if not self.replies:
            raise AssertionError("脚本回复已耗尽")
        return self.replies.pop(0)


class ReportedUsageProvider(ScriptedProvider):
    def __init__(self, replies, usages):
        super().__init__(replies)
        self.usages = list(usages)
        self.last_usage = {}

    async def chat(self, messages=None, system_prompt=None, temperature=None, **kwargs):
        reply = await super().chat(
            messages=messages,
            system_prompt=system_prompt,
            temperature=temperature,
            **kwargs,
        )
        self.last_usage = self.usages.pop(0) if self.usages else {}
        return reply

    def get_last_usage(self):
        return dict(self.last_usage)


class FailingProvider:
    async def chat(self, **kwargs):
        raise RuntimeError("provider-secret-detail")


class _KernelTestBase(unittest.IsolatedAsyncioTestCase):
    async def asyncSetUp(self):
        self.tmpdir = tempfile.TemporaryDirectory()
        db_path = Path(self.tmpdir.name) / "kernel.sqlite3"
        self.engine = create_async_engine(f"sqlite+aiosqlite:///{db_path}", future=True)
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


class DecisionParsingTests(unittest.TestCase):
    def test_parses_plain_and_fenced_json(self):
        obj = {"action": "finish", "next_actions": []}
        self.assertEqual(parse_kernel_decision(json.dumps(obj)), obj)
        self.assertEqual(parse_kernel_decision(f"```json\n{json.dumps(obj)}\n```"), obj)
        self.assertEqual(parse_kernel_decision(f"前置说明\n{json.dumps(obj)}\n后缀"), obj)

    def test_invalid_output_returns_none(self):
        self.assertIsNone(parse_kernel_decision("抱歉，我不能"))
        self.assertIsNone(parse_kernel_decision(""))
        self.assertIsNone(parse_kernel_decision("[1,2,3]"))

    def test_system_prompt_lists_all_tools_and_safety_rule(self):
        prompt = build_kernel_system_prompt()
        for tool in ("search_notes", "concept_neighborhood", "find_associations", "context_retrieve"):
            self.assertIn(tool, prompt)
        self.assertIn("不可信", prompt)

    def test_kernel_confirmation_body_rejects_client_draft_content(self):
        with self.assertRaises(ValidationError):
            AgentKernelActionConfirmRequest(
                draft_id="server-issued-draft",
                draft={"title": "客户端试图替换草案"},
            )


class KernelLoopTests(_KernelTestBase):
    async def test_immediate_finish_returns_sanitized_actions(self):
        # Arrange
        user_id = await self._create_user("kernel_finish_user")
        provider = ScriptedProvider([FINISH_REPLY])

        # Act
        async with self.sessionmaker() as session:
            result = await run_agent_kernel(session, user_id, provider)

        # Assert
        self.assertEqual(result.status, "completed")
        self.assertEqual(len(result.next_actions), 1)
        self.assertEqual(result.next_actions[0]["source"], "llm")
        self.assertEqual(result.strategy, "先清最旧复习，再做一轮短专注")
        self.assertEqual(result.steps[-1].kind, "finish")

    async def test_action_ids_are_route_safe_and_unique(self):
        user_id = await self._create_user("kernel_action_id_user")
        provider = ScriptedProvider(
            [
                json.dumps(
                    {
                        "action": "finish",
                        "next_actions": [
                            {
                                "id": "practice/matrix",
                                "title": "练习一",
                                "reason": "证据一",
                                "action_type": "practice",
                            },
                            {
                                "id": "practice/matrix",
                                "title": "练习二",
                                "reason": "证据二",
                                "action_type": "practice",
                            },
                        ],
                    }
                )
            ]
        )

        async with self.sessionmaker() as session:
            result = await run_agent_kernel(session, user_id, provider)

        self.assertEqual(
            [action["id"] for action in result.next_actions],
            ["practice_matrix", "practice_matrix_2"],
        )

    async def test_tool_call_executes_and_feeds_wrapped_observation(self):
        # Arrange：用户有一条笔记，内核先查笔记再收束
        user_id = await self._create_user("kernel_tool_user")
        async with self.sessionmaker() as session:
            session.add(Note(user_id=user_id, title="贝叶斯笔记", content="条件概率是基础"))
            await session.commit()

        provider = ScriptedProvider(
            [
                json.dumps(
                    {"action": "tool", "tool": "search_notes", "args": {"query": "贝叶斯", "limit": 3}, "thought": "先看笔记"}
                ),
                FINISH_REPLY,
            ]
        )

        # Act
        async with self.sessionmaker() as session:
            result = await run_agent_kernel(session, user_id, provider)

        # Assert
        self.assertEqual(result.status, "completed")
        tool_steps = [s for s in result.steps if s.kind == "tool"]
        self.assertEqual(len(tool_steps), 1)
        self.assertEqual(tool_steps[0].tool, "search_notes")
        self.assertIn("贝叶斯笔记", tool_steps[0].observation_preview)
        # 第二次调用的 messages 中，工具结果必须被不可信上下文包装
        second_call_text = "\n".join(m["content"] for m in provider.calls[1])
        self.assertIn("untrusted_context", second_call_text)
        self.assertIn("贝叶斯笔记", second_call_text)

    async def test_unknown_tool_gets_error_observation_and_loop_continues(self):
        # Arrange
        user_id = await self._create_user("kernel_unknown_user")
        provider = ScriptedProvider(
            [
                json.dumps({"action": "tool", "tool": "delete_everything", "args": {}, "thought": "试试"}),
                FINISH_REPLY,
            ]
        )

        # Act
        async with self.sessionmaker() as session:
            result = await run_agent_kernel(session, user_id, provider)

        # Assert：未知（含写入类）工具不会被执行，循环继续并正常收束
        self.assertEqual(result.status, "completed")
        second_call_text = "\n".join(m["content"] for m in provider.calls[1])
        self.assertIn("未知工具", second_call_text)

    async def test_repeated_format_errors_abort_gracefully(self):
        # Arrange
        user_id = await self._create_user("kernel_badfmt_user")
        provider = ScriptedProvider(["不是JSON", "还不是JSON", "依然不是"])

        # Act
        async with self.sessionmaker() as session:
            result = await run_agent_kernel(session, user_id, provider)

        # Assert
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "format_error_limit")
        self.assertEqual(result.next_actions, [])

    async def test_provider_failure_returns_failed_without_raising(self):
        # Arrange
        user_id = await self._create_user("kernel_down_user")

        # Act
        async with self.sessionmaker() as session:
            result = await run_agent_kernel(session, user_id, FailingProvider())

        # Assert
        self.assertEqual(result.status, "failed")
        self.assertEqual(result.error, "model_error")
        self.assertNotIn("provider-secret-detail", result.error)
        self.assertEqual(result.usage["model_calls"], 1)
        self.assertEqual(result.usage["unreconciled_calls"], 1)

    async def test_provider_reported_usage_and_configured_cost_are_reconciled(self):
        user_id = await self._create_user("kernel_actual_usage_user")
        provider = ReportedUsageProvider(
            [FINISH_REPLY],
            [
                {
                    "provider": "openai-custom",
                    "model": "gpt-test",
                    "input_tokens": 120,
                    "output_tokens": 30,
                    "total_tokens": 150,
                    "configured_cost_usd": 0.00123,
                }
            ],
        )

        async with self.sessionmaker() as session:
            result = await run_agent_kernel(session, user_id, provider)

        self.assertEqual(result.status, "completed")
        self.assertEqual(result.usage["usage_source"], "provider")
        self.assertEqual(result.usage["actual_input_tokens"], 120)
        self.assertEqual(result.usage["actual_output_tokens"], 30)
        self.assertEqual(result.usage["actual_total_tokens"], 150)
        self.assertEqual(result.usage["actual_usage_calls"], 1)
        self.assertEqual(result.usage["unreconciled_calls"], 0)
        self.assertAlmostEqual(result.usage["configured_cost_usd"], 0.00123)
        self.assertEqual(result.usage["provider"], "openai-custom")
        self.assertEqual(result.usage["model"], "gpt-test")

    async def test_estimated_token_budget_blocks_before_provider_call(self):
        user_id = await self._create_user("kernel_token_budget_user")
        provider = ScriptedProvider([FINISH_REPLY])

        async with self.sessionmaker() as session:
            result = await run_agent_kernel(
                session,
                user_id,
                provider,
                max_estimated_tokens=512,
            )

        self.assertEqual(result.status, "fallback")
        self.assertEqual(result.error, "cost_budget_exceeded")
        self.assertEqual(result.usage["budget_reason"], "estimated_token_limit")
        self.assertEqual(result.usage["model_calls"], 0)
        self.assertEqual(provider.calls, [])

    async def test_model_call_budget_is_persisted_and_enforced_on_resume(self):
        user_id = await self._create_user("kernel_call_budget_user")
        provider = ScriptedProvider(
            [json.dumps({"action": "tool", "tool": "get_profile", "args": {}, "thought": "先看画像"})]
        )
        checkpoints: list[dict] = []

        async def collect_progress(step, checkpoint):
            if checkpoint is not None:
                checkpoints.append(checkpoint)

        async with self.sessionmaker() as session:
            first = await run_agent_kernel(
                session,
                user_id,
                provider,
                max_model_calls=1,
                on_progress=collect_progress,
            )

        self.assertEqual(first.status, "fallback")
        self.assertEqual(first.error, "cost_budget_exceeded")
        self.assertEqual(first.usage["budget_reason"], "model_call_limit")
        self.assertEqual(first.usage["model_calls"], 1)
        self.assertEqual(checkpoints[-1]["usage"]["model_calls"], 1)

        resumed_provider = ScriptedProvider([FINISH_REPLY])
        async with self.sessionmaker() as session:
            resumed = await run_agent_kernel(
                session,
                user_id,
                resumed_provider,
                max_model_calls=1,
                resume_checkpoint=checkpoints[-1],
            )

        self.assertEqual(resumed.status, "fallback")
        self.assertEqual(resumed.error, "cost_budget_exceeded")
        self.assertEqual(resumed.usage["budget_reason"], "model_call_limit")
        self.assertEqual(resumed_provider.calls, [])

    async def test_checkpoint_resumes_with_prior_tool_context_and_next_step(self):
        user_id = await self._create_user("kernel_checkpoint_user")
        tool_reply = json.dumps(
            {"action": "tool", "tool": "get_profile", "args": {}, "thought": "先看画像"}
        )
        first_provider = ScriptedProvider([tool_reply])
        checkpoints: list[dict] = []

        async def collect_progress(step, checkpoint):
            if checkpoint is not None:
                checkpoints.append(checkpoint)

        async with self.sessionmaker() as session:
            first = await run_agent_kernel(
                session,
                user_id,
                first_provider,
                on_progress=collect_progress,
            )

        self.assertEqual(first.status, "failed")
        self.assertEqual(first.error, "model_error")
        self.assertEqual(checkpoints[-1]["next_step_index"], 2)
        checkpoint_text = "\n".join(item["content"] for item in checkpoints[-1]["messages"])
        self.assertIn("untrusted_context", checkpoint_text)

        resumed_provider = ScriptedProvider([FINISH_REPLY])
        async with self.sessionmaker() as session:
            resumed = await run_agent_kernel(
                session,
                user_id,
                resumed_provider,
                resume_checkpoint=checkpoints[-1],
            )

        self.assertEqual(resumed.status, "completed")
        self.assertEqual(resumed.steps[0].index, 2)
        resumed_context = "\n".join(item["content"] for item in resumed_provider.calls[0])
        self.assertIn("untrusted_context", resumed_context)

    async def test_cooperative_cancellation_stops_before_the_next_provider_step(self):
        user_id = await self._create_user("kernel_cancel_user")
        provider = ScriptedProvider(
            [json.dumps({"action": "tool", "tool": "get_profile", "args": {}, "thought": "先看画像"})]
        )
        checks = iter([False, True])

        async def should_cancel():
            return next(checks)

        async with self.sessionmaker() as session:
            result = await run_agent_kernel(
                session,
                user_id,
                provider,
                should_cancel=should_cancel,
            )

        self.assertEqual(result.status, "cancelled")
        self.assertEqual(result.error, "cancelled_by_user")
        self.assertEqual([step.kind for step in result.steps], ["cancelled"])
        self.assertEqual(len(provider.calls), 1)

    async def test_tool_failure_never_reaches_the_next_model_call(self):
        user_id = await self._create_user("kernel_tool_failure_user")
        provider = ScriptedProvider(
            [
                json.dumps({"action": "tool", "tool": "get_profile", "args": {}, "thought": "check"}),
                FINISH_REPLY,
            ]
        )

        async with self.sessionmaker() as session:
            with patch(
                "app.agents.agent_kernel._execute_tool",
                new=AsyncMock(side_effect=RuntimeError("tool-secret-detail")),
            ):
                result = await run_agent_kernel(session, user_id, provider)

        self.assertEqual(result.status, "completed")
        second_call_text = "\n".join(message["content"] for message in provider.calls[1])
        self.assertNotIn("tool-secret-detail", second_call_text)
        self.assertNotIn("tool-secret-detail", result.steps[0].observation_preview)

    async def test_provider_setup_failure_returns_a_public_reason_code(self):
        user_id = await self._create_user("kernel_provider_setup_user")
        current_user = User(
            id=user_id,
            username="kernel_provider_setup_user",
            email="kernel_provider_setup_user@example.com",
            hashed_password="hash",
            is_active=True,
        )

        async with self.sessionmaker() as session:
            with patch(
                "app.ai.factory.AIProviderFactory.create_provider",
                new=AsyncMock(side_effect=RuntimeError("provider-setup-secret")),
            ):
                response = await run_kernel(
                    AgentKernelRunRequest(),
                    db=session,
                    current_user=current_user,
                )

        self.assertEqual(response["status"], "fallback")
        self.assertEqual(response["reason"], "ai_provider_unavailable")
        self.assertEqual(response["error"], "ai_provider_unavailable")
        self.assertEqual(response["fallback"]["source"], "rules")
        self.assertTrue(response["next_actions"])
        self.assertEqual(response["next_actions"][0]["source"], "rules_fallback")
        self.assertNotIn("provider-setup-secret", str(response))
        self.assertIsNotNone(response["job_id"])
        async with self.sessionmaker() as session:
            job = await session.get(AgentJob, response["job_id"])
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.scenario, "agent_kernel_v1")
        self.assertEqual(job.result["reason"], "ai_provider_unavailable")

        async with self.sessionmaker() as session:
            draft = await draft_kernel_job_action(
                response["job_id"],
                response["next_actions"][0]["id"],
                db=session,
                current_user=current_user,
            )
        self.assertEqual(draft["action"]["source"], "rules_fallback")

    async def test_model_failure_returns_actionable_rules_fallback_and_keeps_retryable_job(self):
        user_id = await self._create_user("kernel_model_fallback_user")
        current_user = User(
            id=user_id,
            username="kernel_model_fallback_user",
            email="kernel_model_fallback_user@example.com",
            hashed_password="hash",
            is_active=True,
        )

        async with self.sessionmaker() as session:
            with patch(
                "app.ai.factory.AIProviderFactory.create_provider",
                new=AsyncMock(return_value=FailingProvider()),
            ):
                response = await run_kernel(
                    AgentKernelRunRequest(),
                    db=session,
                    current_user=current_user,
                )

        self.assertEqual(response["status"], "fallback")
        self.assertEqual(response["error"], "model_error")
        self.assertTrue(response["next_actions"])
        async with self.sessionmaker() as session:
            job = await session.get(AgentJob, response["job_id"])
            logs = (
                await session.execute(
                    select(AgentExecutionLog).where(AgentExecutionLog.job_id == response["job_id"])
                )
            ).scalars().all()
        self.assertEqual(job.status, "failed")
        self.assertEqual(job.result["status"], "fallback")
        self.assertIn("fallback", [log.status for log in logs])

    async def test_daily_budget_aggregates_per_attempt_usage_without_double_counting_resume(self):
        user_id = await self._create_user("kernel_daily_usage_user")
        now = datetime(2026, 8, 31, 12, 0, 0)
        async with self.sessionmaker() as session:
            session.add_all(
                [
                    AgentJob(
                        id="daily-usage-first",
                        user_id=user_id,
                        agent="kernel",
                        task="run",
                        status="completed",
                        scenario="agent_kernel_v1",
                        run_key="kernel:daily-usage-first",
                        result={
                            "usage": {
                                "model_calls": 2,
                                "estimated_total_tokens": 1000,
                                "run_model_calls": 2,
                                "run_estimated_total_tokens": 1000,
                                "run_actual_usage_calls": 2,
                                "run_actual_total_tokens": 800,
                                "run_configured_cost_usd": 0.004,
                            }
                        },
                        # A prepared job may be created before midnight but
                        # must consume the day on which it actually starts.
                        created_at=now - timedelta(hours=13),
                        started_at=now - timedelta(hours=2),
                    ),
                    AgentJob(
                        id="daily-usage-resume",
                        user_id=user_id,
                        agent="kernel",
                        task="run",
                        status="failed",
                        scenario="agent_kernel_v1",
                        run_key="kernel:daily-usage-resume",
                        result={
                            "usage": {
                                "model_calls": 3,
                                "estimated_total_tokens": 1500,
                                "run_model_calls": 1,
                                "run_estimated_total_tokens": 500,
                                "run_actual_usage_calls": 1,
                                "run_actual_total_tokens": 420,
                                "run_configured_cost_usd": 0.002,
                            }
                        },
                        created_at=now - timedelta(hours=1),
                    ),
                ]
            )
            await session.commit()

        async with self.sessionmaker() as session:
            budget = await get_agent_kernel_daily_budget(
                session,
                user_id,
                model_call_limit=30,
                estimated_token_limit=128000,
                now=now,
            )

        self.assertEqual(budget["model_calls"], 3)
        self.assertEqual(budget["estimated_tokens"], 1500)
        self.assertEqual(budget["actual_usage_calls"], 3)
        self.assertEqual(budget["actual_tokens"], 1220)
        self.assertAlmostEqual(budget["configured_cost_usd"], 0.006)
        self.assertEqual(budget["remaining_model_calls"], 27)

    async def test_daily_budget_exhaustion_blocks_before_provider_setup(self):
        user_id = await self._create_user("kernel_daily_limit_user")
        current_user = User(
            id=user_id,
            username="kernel_daily_limit_user",
            email="kernel_daily_limit_user@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            session.add(
                AgentJob(
                    id="daily-limit-prior",
                    user_id=user_id,
                    agent="kernel",
                    task="run",
                    status="completed",
                    scenario="agent_kernel_v1",
                    run_key="kernel:daily-limit-prior",
                    result={
                        "usage": {
                            "run_model_calls": 3,
                            "run_estimated_total_tokens": 1000,
                        }
                    },
                    created_at=datetime.utcnow(),
                )
            )
            await session.commit()

        provider_factory = AsyncMock(return_value=ScriptedProvider([FINISH_REPLY]))
        async with self.sessionmaker() as session:
            with (
                patch.object(settings, "AGENT_KERNEL_DAILY_MODEL_CALLS_PER_USER", 3),
                patch.object(settings, "AGENT_KERNEL_DAILY_ESTIMATED_TOKENS_PER_USER", 128000),
                patch("app.ai.factory.AIProviderFactory.create_provider", new=provider_factory),
            ):
                response = await run_kernel(
                    AgentKernelRunRequest(),
                    db=session,
                    current_user=current_user,
                )

        self.assertEqual(response["status"], "fallback")
        self.assertEqual(response["error"], "daily_cost_budget_exceeded")
        self.assertEqual(response["usage"]["budget_reason"], "daily_model_call_limit")
        self.assertEqual(response["fallback"]["source"], "rules")
        self.assertTrue(response["next_actions"])
        provider_factory.assert_not_awaited()
        async with self.sessionmaker() as session:
            job = await session.get(AgentJob, response["job_id"])
            logs = (
                await session.execute(
                    select(AgentExecutionLog).where(AgentExecutionLog.job_id == response["job_id"])
                )
            ).scalars().all()
        self.assertEqual(job.status, "failed")
        self.assertEqual([log.status for log in logs], ["budget_exceeded"])

    async def test_daily_remaining_budget_caps_run_and_blocks_parallel_job(self):
        user_id = await self._create_user("kernel_daily_remaining_user")
        current_user = User(
            id=user_id,
            username="kernel_daily_remaining_user",
            email="kernel_daily_remaining_user@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            session.add(
                AgentJob(
                    id="daily-remaining-prior",
                    user_id=user_id,
                    agent="kernel",
                    task="run",
                    status="completed",
                    scenario="agent_kernel_v1",
                    run_key="kernel:daily-remaining-prior",
                    result={
                        "usage": {
                            "run_model_calls": 29,
                            "run_estimated_total_tokens": 1000,
                        }
                    },
                    created_at=datetime.utcnow(),
                )
            )
            await session.commit()

        async with self.sessionmaker() as session:
            with (
                patch.object(settings, "AGENT_KERNEL_DAILY_MODEL_CALLS_PER_USER", 30),
                patch.object(settings, "AGENT_KERNEL_DAILY_ESTIMATED_TOKENS_PER_USER", 128000),
                patch(
                    "app.ai.factory.AIProviderFactory.create_provider",
                    new=AsyncMock(return_value=ScriptedProvider([FINISH_REPLY])),
                ),
            ):
                response = await run_kernel(
                    AgentKernelRunRequest(),
                    db=session,
                    current_user=current_user,
                )

        self.assertEqual(response["status"], "completed")
        self.assertEqual(response["usage"]["model_call_limit"], 1)
        self.assertEqual(response["usage"]["run_model_calls"], 1)
        self.assertEqual(response["usage"]["daily_budget"]["remaining_model_calls"], 0)

        async with self.sessionmaker() as session:
            session.add_all(
                [
                    AgentJob(
                        id="parallel-active",
                        user_id=user_id,
                        agent="kernel",
                        task="run",
                        status="running",
                        scenario="agent_kernel_v1",
                        run_key="kernel:parallel-active",
                    ),
                    AgentJob(
                        id="parallel-pending",
                        user_id=user_id,
                        agent="kernel",
                        task="run",
                        status="pending",
                        scenario="agent_kernel_v1",
                        run_key="kernel:parallel-pending",
                        payload={"max_steps": 6},
                    ),
                ]
            )
            await session.commit()

        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as context:
                await run_kernel(
                    AgentKernelRunRequest(prepared_job_id="parallel-pending"),
                    db=session,
                    current_user=current_user,
                )
        self.assertEqual(context.exception.status_code, 409)
        self.assertEqual(context.exception.detail, "agent_kernel_run_already_active")

    async def test_failed_kernel_job_can_resume_with_inherited_objective_and_replay(self):
        user_id = await self._create_user("kernel_resume_user")
        current_user = User(
            id=user_id,
            username="kernel_resume_user",
            email="kernel_resume_user@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            with patch(
                "app.ai.factory.AIProviderFactory.create_provider",
                new=AsyncMock(side_effect=RuntimeError("offline")),
            ):
                first = await run_kernel(
                    AgentKernelRunRequest(objective="检查复习积压"),
                    db=session,
                    current_user=current_user,
                )

        async with self.sessionmaker() as session:
            with patch(
                "app.ai.factory.AIProviderFactory.create_provider",
                new=AsyncMock(return_value=ScriptedProvider([FINISH_REPLY])),
            ):
                resumed = await run_kernel(
                    AgentKernelRunRequest(resume_from_job_id=first["job_id"]),
                    db=session,
                    current_user=current_user,
                )
                replay = await get_agent_job_replay(
                    resumed["job_id"],
                    db=session,
                    current_user=current_user,
                )

        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(replay["job"]["resumed_from_job_id"], first["job_id"])
        self.assertEqual(replay["job"]["attempt_count"], 2)
        self.assertEqual(replay["job"]["payload"]["objective"], "检查复习积压")
        self.assertEqual([item["status"] for item in replay["logs"]], ["started", "finish"])

    async def test_failed_kernel_job_resumes_from_durable_checkpoint(self):
        user_id = await self._create_user("kernel_durable_resume_user")
        current_user = User(
            id=user_id,
            username="kernel_durable_resume_user",
            email="kernel_durable_resume_user@example.com",
            hashed_password="hash",
            is_active=True,
        )
        tool_reply = json.dumps(
            {"action": "tool", "tool": "get_profile", "args": {}, "thought": "先看画像"}
        )
        async with self.sessionmaker() as session:
            with patch(
                "app.ai.factory.AIProviderFactory.create_provider",
                new=AsyncMock(return_value=ScriptedProvider([tool_reply])),
            ):
                first = await run_kernel(
                    AgentKernelRunRequest(objective="生成基于画像的复习计划"),
                    db=session,
                    current_user=current_user,
                )

        self.assertEqual(first["status"], "fallback")
        self.assertEqual(first["fallback"]["source"], "rules")
        self.assertTrue(first["next_actions"])
        async with self.sessionmaker() as session:
            first_job = await session.get(AgentJob, first["job_id"])
            first_payload = agent_manager._job_to_dict(first_job)
        self.assertEqual(first_job.checkpoint["next_step_index"], 2)
        self.assertTrue(first_payload["recoverable"])
        self.assertEqual(first_payload["checkpoint_step"], 1)
        self.assertIsNone(first_job.lease_owner)
        self.assertIsNone(first_job.lease_expires_at)

        resumed_provider = ScriptedProvider([FINISH_REPLY])
        async with self.sessionmaker() as session:
            prepared = await prepare_kernel_job(
                AgentKernelRunRequest(resume_from_job_id=first["job_id"]),
                db=session,
                current_user=current_user,
            )
            prepared_job = await session.get(AgentJob, prepared["job"]["id"])
            self.assertEqual(prepared_job.checkpoint["usage"]["model_calls"], 1)
            self.assertEqual(prepared_job.checkpoint["usage"]["run_model_calls"], 0)
            with patch(
                "app.ai.factory.AIProviderFactory.create_provider",
                new=AsyncMock(return_value=resumed_provider),
            ):
                resumed = await run_kernel(
                    AgentKernelRunRequest(prepared_job_id=prepared["job"]["id"]),
                    db=session,
                    current_user=current_user,
                )
                replay = await get_agent_job_replay(
                    resumed["job_id"],
                    db=session,
                    current_user=current_user,
                )

        self.assertEqual(resumed["status"], "completed")
        self.assertEqual(resumed["steps"][0]["index"], 2)
        self.assertEqual(replay["job"]["payload"]["resume_mode"], "checkpoint")
        self.assertEqual(replay["logs"][0]["metadata"]["checkpoint_step"], 1)
        self.assertEqual(resumed["usage"]["model_calls"], 2)
        self.assertEqual(replay["job"]["result"]["usage"]["model_calls"], 2)
        resumed_context = "\n".join(item["content"] for item in resumed_provider.calls[0])
        self.assertIn("untrusted_context", resumed_context)

    async def test_startup_recovery_reclaims_only_expired_leases(self):
        user_id = await self._create_user("kernel_recovery_user")
        now = datetime.utcnow().replace(microsecond=0)
        checkpoint = {
            "version": 1,
            "next_step_index": 2,
            "format_errors": 0,
            "messages": [{"role": "user", "content": "目标：恢复测试"}],
            "usage": {
                "model_calls": 1,
                "estimated_input_tokens": 200,
                "estimated_output_tokens": 20,
                "estimated_total_tokens": 220,
                "run_model_calls": 1,
                "run_estimated_total_tokens": 220,
            },
        }
        async with self.sessionmaker() as session:
            session.add_all(
                [
                    AgentJob(
                        id="expired-running",
                        user_id=user_id,
                        agent="kernel",
                        task="run",
                        status="running",
                        scenario="agent_kernel_v1",
                        run_key="kernel:expired-running",
                        lease_owner="dead-owner",
                        lease_expires_at=now - timedelta(seconds=1),
                        checkpoint=checkpoint,
                        result={"status": "running", "steps": [{"index": 1}]},
                    ),
                    AgentJob(
                        id="expired-cancelling",
                        user_id=user_id,
                        agent="kernel",
                        task="run",
                        status="cancelling",
                        scenario="agent_kernel_v1",
                        run_key="kernel:expired-cancelling",
                        cancel_requested_at=now - timedelta(seconds=2),
                        lease_owner="dead-owner-2",
                        lease_expires_at=now - timedelta(seconds=1),
                        checkpoint=checkpoint,
                        result={"status": "running", "steps": []},
                    ),
                    AgentJob(
                        id="active-running",
                        user_id=user_id,
                        agent="kernel",
                        task="run",
                        status="running",
                        scenario="agent_kernel_v1",
                        run_key="kernel:active-running",
                        lease_owner="live-owner",
                        lease_expires_at=now + timedelta(minutes=1),
                    ),
                    AgentJob(
                        id="legacy-running",
                        user_id=user_id,
                        agent="kernel",
                        task="run",
                        status="running",
                        scenario="agent_kernel_v1",
                        run_key="kernel:legacy-running",
                        lease_owner=None,
                        lease_expires_at=None,
                    ),
                ]
            )
            await session.commit()

        async with self.sessionmaker() as session:
            recovered = await recover_expired_agent_kernel_jobs(session, now=now)
            await session.commit()

        self.assertEqual(recovered, 2)
        async with self.sessionmaker() as session:
            expired = await session.get(AgentJob, "expired-running")
            cancelling = await session.get(AgentJob, "expired-cancelling")
            active = await session.get(AgentJob, "active-running")
            legacy = await session.get(AgentJob, "legacy-running")
            logs = await session.execute(
                select(AgentExecutionLog)
                .where(AgentExecutionLog.job_id.in_(("expired-running", "expired-cancelling")))
                .order_by(AgentExecutionLog.job_id)
            )

        self.assertEqual(expired.status, "failed")
        self.assertEqual(expired.result["error"], "process_interrupted")
        self.assertEqual(expired.result["usage"]["run_model_calls"], 1)
        self.assertTrue(agent_manager._job_to_dict(expired)["recoverable"])
        self.assertIsNone(expired.lease_owner)
        self.assertIsNone(expired.lease_expires_at)
        self.assertEqual(cancelling.status, "cancelled")
        self.assertEqual(cancelling.result["reason"], "cancelled_by_user")
        self.assertEqual(active.status, "running")
        self.assertEqual(active.lease_owner, "live-owner")
        self.assertEqual(legacy.status, "running")
        self.assertEqual([item.status for item in logs.scalars().all()], ["cancelled", "interrupted"])

    async def test_kernel_action_requires_durable_confirmation_and_executes_once(self):
        user_id = await self._create_user("kernel_action_owner")
        other_id = await self._create_user("kernel_action_other")
        async with self.sessionmaker() as session:
            goal = Goal(user_id=user_id, title="线代冲刺", status="active")
            session.add(goal)
            await session.flush()
            goal_id = int(goal.id)
            session.add(
                AgentJob(
                    id="kernel-action-job",
                    user_id=user_id,
                    agent="kernel",
                    task="run",
                    status="completed",
                    scenario="agent_kernel_v1",
                    run_key="kernel:kernel-action-job",
                    result={
                        "status": "completed",
                        "steps": [],
                        "next_actions": [
                            {
                                "id": "practice-matrix",
                                "title": "练习矩阵秩",
                                "reason": "最近错题集中在矩阵秩",
                                "action_type": "practice",
                                "priority": "high",
                                "estimated_minutes": 15,
                                "route": "/wrong-questions",
                            },
                            {
                                "id": "review-due",
                                "title": "清理到期复习",
                                "reason": "有到期复习需要处理",
                                "action_type": "review",
                                "priority": "medium",
                                "estimated_minutes": 10,
                                "route": "/review",
                            },
                        ],
                    },
                )
            )
            await session.commit()

        owner = User(
            id=user_id,
            username="kernel_action_owner",
            email="kernel_action_owner@example.com",
            hashed_password="hash",
            is_active=True,
        )
        other = User(
            id=other_id,
            username="kernel_action_other",
            email="kernel_action_other@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as context:
                await draft_kernel_job_action(
                    "kernel-action-job",
                    "practice-matrix",
                    db=session,
                    current_user=other,
                )
            self.assertEqual(context.exception.status_code, 404)

        async with self.sessionmaker() as session:
            draft = await draft_kernel_job_action(
                "kernel-action-job",
                "practice-matrix",
                db=session,
                current_user=owner,
            )
            repeated_draft = await draft_kernel_job_action(
                "kernel-action-job",
                "practice-matrix",
                db=session,
                current_user=owner,
            )
            task_count_before = len((await session.execute(select(Task))).scalars().all())

        self.assertTrue(draft["requires_confirmation"])
        self.assertEqual(draft["draft"]["goal_id"], goal_id)
        self.assertEqual(draft["draft_id"], repeated_draft["draft_id"])
        self.assertEqual(task_count_before, 0)

        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as context:
                await confirm_kernel_job_action(
                    "kernel-action-job",
                    "practice-matrix",
                    AgentKernelActionConfirmRequest(draft_id=draft["draft_id"]),
                    db=session,
                    current_user=other,
                )
            self.assertEqual(context.exception.status_code, 404)

        async with self.sessionmaker() as session:
            first = await confirm_kernel_job_action(
                "kernel-action-job",
                "practice-matrix",
                AgentKernelActionConfirmRequest(draft_id=draft["draft_id"]),
                db=session,
                current_user=owner,
            )
        async with self.sessionmaker() as session:
            repeated = await confirm_kernel_job_action(
                "kernel-action-job",
                "practice-matrix",
                AgentKernelActionConfirmRequest(draft_id=draft["draft_id"]),
                db=session,
                current_user=owner,
            )
            tasks = (await session.execute(select(Task))).scalars().all()
            events = (
                await session.execute(
                    select(LearningEvent)
                    .where(LearningEvent.user_id == user_id)
                    .order_by(LearningEvent.event_type)
                )
            ).scalars().all()
            receipt = await session.get(AgentActionConfirmation, draft["draft_id"])
            job = await session.get(AgentJob, "kernel-action-job")
            logs = (
                await session.execute(
                    select(AgentExecutionLog)
                    .where(AgentExecutionLog.job_id == "kernel-action-job")
                    .order_by(AgentExecutionLog.created_at, AgentExecutionLog.id)
                )
            ).scalars().all()

        self.assertEqual(first["status"], "created")
        self.assertFalse(first["idempotent"])
        self.assertTrue(repeated["idempotent"])
        self.assertEqual(repeated["created_task"]["id"], first["created_task"]["id"])
        self.assertEqual(len(tasks), 1)
        self.assertEqual(receipt.status, "completed")
        self.assertEqual(job.result["action_executions"]["practice-matrix"]["task_id"], tasks[0].id)
        self.assertEqual([event.event_type for event in events], ["agent.action_feedback", "task.created"])
        self.assertCountEqual([log.status for log in logs], ["drafted", "confirmed"])

    async def test_kernel_navigation_action_uses_confirmation_receipt_without_writing_task(self):
        user_id = await self._create_user("kernel_navigation_owner")
        owner = User(
            id=user_id,
            username="kernel_navigation_owner",
            email="kernel_navigation_owner@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            session.add(
                AgentJob(
                    id="kernel-navigation-job",
                    user_id=user_id,
                    agent="kernel",
                    task="run",
                    status="completed",
                    scenario="agent_kernel_v1",
                    run_key="kernel:kernel-navigation-job",
                    result={
                        "status": "completed",
                        "steps": [],
                        "next_actions": [
                            {
                                "id": "review-now",
                                "title": "开始复习",
                                "reason": "现在有到期复习",
                                "action_type": "review",
                                "priority": "high",
                                "estimated_minutes": 10,
                                "route": "/review",
                            }
                        ],
                    },
                )
            )
            await session.commit()

        async with self.sessionmaker() as session:
            draft = await draft_kernel_job_action(
                "kernel-navigation-job",
                "review-now",
                db=session,
                current_user=owner,
            )
            result = await confirm_kernel_job_action(
                "kernel-navigation-job",
                "review-now",
                AgentKernelActionConfirmRequest(draft_id=draft["draft_id"]),
                db=session,
                current_user=owner,
            )
            task_count = len((await session.execute(select(Task))).scalars().all())

        self.assertFalse(draft["requires_confirmation"])
        self.assertEqual(result["status"], "navigated")
        self.assertEqual(result["route"], "/review")
        self.assertEqual(task_count, 0)

    async def test_kernel_action_rejects_stale_goal_without_consuming_confirmation(self):
        user_id = await self._create_user("kernel_stale_goal_owner")
        owner = User(
            id=user_id,
            username="kernel_stale_goal_owner",
            email="kernel_stale_goal_owner@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            goal = Goal(user_id=user_id, title="即将暂停的目标", status="active")
            session.add(goal)
            await session.flush()
            session.add(
                AgentJob(
                    id="kernel-stale-goal-job",
                    user_id=user_id,
                    agent="kernel",
                    task="run",
                    status="completed",
                    scenario="agent_kernel_v1",
                    run_key="kernel:kernel-stale-goal-job",
                    result={
                        "status": "completed",
                        "next_actions": [
                            {
                                "id": "stale-plan",
                                "title": "完成一个计划切片",
                                "reason": "推进当前目标",
                                "action_type": "plan",
                                "priority": "medium",
                                "estimated_minutes": 15,
                                "route": "/goals",
                            }
                        ],
                    },
                )
            )
            await session.commit()

        async with self.sessionmaker() as session:
            draft = await draft_kernel_job_action(
                "kernel-stale-goal-job",
                "stale-plan",
                db=session,
                current_user=owner,
            )
        async with self.sessionmaker() as session:
            goal = await session.get(Goal, draft["draft"]["goal_id"])
            goal.status = "paused"
            await session.commit()

        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as context:
                await confirm_kernel_job_action(
                    "kernel-stale-goal-job",
                    "stale-plan",
                    AgentKernelActionConfirmRequest(draft_id=draft["draft_id"]),
                    db=session,
                    current_user=owner,
                )
            self.assertEqual(context.exception.status_code, 409)

        async with self.sessionmaker() as session:
            receipt = await session.get(AgentActionConfirmation, draft["draft_id"])
            tasks = (await session.execute(select(Task))).scalars().all()
        self.assertEqual(receipt.status, "prepared")
        self.assertEqual(tasks, [])

    async def test_job_cancellation_is_user_scoped_and_persisted(self):
        user_id = await self._create_user("kernel_cancel_owner")
        other_id = await self._create_user("kernel_cancel_other")
        async with self.sessionmaker() as session:
            job = AgentJob(
                id="cancel-job",
                user_id=user_id,
                agent="kernel",
                task="run",
                status="running",
                scenario="agent_kernel_v1",
                run_key="kernel:cancel-job",
            )
            session.add(job)
            await session.commit()

        owner = User(id=user_id, username="owner", email="owner@example.com", hashed_password="hash", is_active=True)
        other = User(id=other_id, username="other", email="other@example.com", hashed_password="hash", is_active=True)
        async with self.sessionmaker() as session:
            with self.assertRaises(HTTPException) as context:
                await cancel_agent_job("cancel-job", db=session, current_user=other)
            self.assertEqual(context.exception.status_code, 404)
            with self.assertRaises(HTTPException) as stream_context:
                await stream_agent_job_events("cancel-job", db=session, current_user=other)
            self.assertEqual(stream_context.exception.status_code, 404)
            response = await cancel_agent_job("cancel-job", db=session, current_user=owner)

        self.assertTrue(response["changed"])
        self.assertEqual(response["job"]["status"], "cancelling")
        async with self.sessionmaker() as session:
            duplicate = await cancel_agent_job("cancel-job", db=session, current_user=owner)
        self.assertFalse(duplicate["changed"])
        async with self.sessionmaker() as session:
            job = await session.get(AgentJob, "cancel-job")
            logs = await session.execute(
                select(AgentExecutionLog).where(AgentExecutionLog.job_id == "cancel-job")
            )
        self.assertIsNotNone(job.cancel_requested_at)
        self.assertEqual(logs.scalar_one().status, "cancelling")

    async def test_prepared_job_is_visible_before_model_call_and_runs_once(self):
        user_id = await self._create_user("kernel_prepared_user")
        current_user = User(
            id=user_id,
            username="kernel_prepared_user",
            email="kernel_prepared_user@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            prepared = await prepare_kernel_job(
                AgentKernelRunRequest(objective="检查今日证据"),
                db=session,
                current_user=current_user,
            )
            job_id = prepared["job"]["id"]
            self.assertEqual(prepared["job"]["status"], "pending")

            with patch(
                "app.ai.factory.AIProviderFactory.create_provider",
                new=AsyncMock(return_value=ScriptedProvider([FINISH_REPLY])),
            ):
                result = await run_kernel(
                    AgentKernelRunRequest(prepared_job_id=job_id),
                    db=session,
                    current_user=current_user,
                )

            self.assertEqual(result["job_id"], job_id)
            self.assertEqual(result["status"], "completed")
            with self.assertRaises(HTTPException) as context:
                await run_kernel(
                    AgentKernelRunRequest(prepared_job_id=job_id),
                    db=session,
                    current_user=current_user,
                )
            self.assertEqual(context.exception.status_code, 409)

        async with self.sessionmaker() as session:
            with patch("app.routers.agent.async_session_maker", self.sessionmaker):
                response = await stream_agent_job_events(
                    job_id,
                    db=session,
                    current_user=current_user,
                )
                chunks = [chunk async for chunk in response.body_iterator]

        stream_text = "".join(
            chunk.decode("utf-8") if isinstance(chunk, bytes) else chunk for chunk in chunks
        )
        self.assertEqual(response.media_type, "text/event-stream")
        self.assertIn("event: snapshot", stream_text)
        self.assertIn("event: log", stream_text)
        self.assertIn('"status":"finish"', stream_text)
        self.assertIn("event: terminal", stream_text)
        self.assertIn('"status":"completed"', stream_text)

    async def test_pending_prepared_job_can_be_cancelled_before_model_call(self):
        user_id = await self._create_user("kernel_pending_cancel_user")
        current_user = User(
            id=user_id,
            username="kernel_pending_cancel_user",
            email="kernel_pending_cancel_user@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            prepared = await prepare_kernel_job(
                AgentKernelRunRequest(),
                db=session,
                current_user=current_user,
            )
            job_id = prepared["job"]["id"]
            cancelled = await cancel_agent_job(job_id, db=session, current_user=current_user)

        self.assertTrue(cancelled["changed"])
        self.assertEqual(cancelled["job"]["status"], "cancelled")
        async with self.sessionmaker() as session:
            logs = await session.execute(
                select(AgentExecutionLog).where(AgentExecutionLog.job_id == job_id)
            )
        self.assertEqual(logs.scalar_one().status, "cancelled")

    async def test_job_event_stream_follows_new_logs_until_terminal_state(self):
        user_id = await self._create_user("kernel_live_stream_user")
        current_user = User(
            id=user_id,
            username="kernel_live_stream_user",
            email="kernel_live_stream_user@example.com",
            hashed_password="hash",
            is_active=True,
        )
        async with self.sessionmaker() as session:
            prepared = await prepare_kernel_job(
                AgentKernelRunRequest(),
                db=session,
                current_user=current_user,
            )
            job_id = prepared["job"]["id"]

        with (
            patch("app.routers.agent.async_session_maker", self.sessionmaker),
            patch("app.routers.agent.AGENT_JOB_EVENT_POLL_SECONDS", 0.001),
        ):
            async with self.sessionmaker() as session:
                response = await stream_agent_job_events(
                    job_id,
                    db=session,
                    current_user=current_user,
                )
            iterator = response.body_iterator
            first = await anext(iterator)
            self.assertIn("event: snapshot", first)
            self.assertIn('"status":"pending"', first)

            async with self.sessionmaker() as session:
                job = await session.get(AgentJob, job_id)
                job.status = "completed"
                job.finished_at = job.created_at
                session.add(
                    AgentExecutionLog(
                        id="live-stream-log",
                        user_id=user_id,
                        job_id=job_id,
                        agent="kernel",
                        status="finish",
                        message="streamed finish",
                    )
                )
                await session.commit()

            second = await anext(iterator)
            third = await anext(iterator)
            self.assertIn("event: log", second)
            self.assertIn("streamed finish", second)
            self.assertIn("event: terminal", third)
            self.assertIn('"status":"completed"', third)
            with self.assertRaises(StopAsyncIteration):
                await anext(iterator)

    async def test_task_trigger_hides_unexpected_error_details(self):
        user_id = await self._create_user("kernel_trigger_failure_user")
        current_user = User(
            id=user_id,
            username="kernel_trigger_failure_user",
            email="kernel_trigger_failure_user@example.com",
            hashed_password="hash",
            is_active=True,
        )

        async with self.sessionmaker() as session:
            with patch(
                "app.routers.agent.agent_manager.trigger",
                new=AsyncMock(side_effect=RuntimeError("agent-trigger-secret")),
            ):
                with self.assertRaises(HTTPException) as context:
                    await trigger_agent_task(
                        AgentTaskTriggerRequest(agent="review"),
                        db=session,
                        current_user=current_user,
                    )

        self.assertEqual(context.exception.status_code, 500)
        self.assertEqual(context.exception.detail, "agent_execution_failed")
        self.assertNotIn("agent-trigger-secret", str(context.exception.detail))

    async def test_max_steps_exhaustion_forces_final_finish(self):
        # Arrange：模型一直调用工具，步数耗尽后被强制收束
        user_id = await self._create_user("kernel_exhaust_user")
        tool_reply = json.dumps(
            {"action": "tool", "tool": "get_profile", "args": {}, "thought": "再看看"}
        )
        provider = ScriptedProvider([tool_reply, tool_reply, FINISH_REPLY])

        # Act
        async with self.sessionmaker() as session:
            result = await run_agent_kernel(session, user_id, provider, max_steps=2)

        # Assert
        self.assertEqual(result.status, "completed")
        self.assertEqual(len([s for s in result.steps if s.kind == "tool"]), 2)
        self.assertEqual(len(result.next_actions), 1)


if __name__ == "__main__":
    unittest.main()
