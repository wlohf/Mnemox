"""Conversational study agent."""
from __future__ import annotations

from app.agents.base import BaseAgent


class ChatAgent(BaseAgent):
    name = "chat"
    description = "面向学习问答、概念解释和苏格拉底式追问的通用学习助手"

    async def run(self, payload: dict) -> dict:
        message = str(payload.get("message") or "").strip()
        if not message:
            return {"reply": "请先输入你想讨论的学习问题。", "fallback": True}

        try:
            reply = await self._chat(
                prompt=message,
                system_prompt=(
                    "你是耐心的学习教练。请先给出清晰解释，再用 1-2 个问题引导用户主动回忆。"
                    "回答使用中文，结构化、简洁。"
                ),
                scenario="agent_chat",
                temperature=0.5,
            )
            return {"reply": reply, "fallback": False}
        except Exception as exc:
            return {
                "reply": "AI 尚未配置或当前不可用。你可以先在 AI 设置中配置 API Key；我已保留你的问题。",
                "error": str(exc),
                "fallback": True,
            }
