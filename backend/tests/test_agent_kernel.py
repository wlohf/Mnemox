"""AgentKernel 多步工具循环测试（决策 D4）。"""
import json
import tempfile
import unittest
from pathlib import Path
from unittest.mock import AsyncMock, patch

from fastapi import HTTPException
from sqlalchemy.ext.asyncio import async_sessionmaker, create_async_engine

from app.agents.agent_kernel import (
    build_kernel_system_prompt,
    parse_kernel_decision,
    run_agent_kernel,
)
from app.database import Base
from app.models.note import Note
from app.models.user import User
from app.routers.agent import (
    AgentKernelRunRequest,
    AgentTaskTriggerRequest,
    run_kernel,
    trigger_agent_task,
)

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

        self.assertEqual(response["status"], "unavailable")
        self.assertEqual(response["reason"], "ai_provider_unavailable")
        self.assertNotIn("provider-setup-secret", str(response))

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
