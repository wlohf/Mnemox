"""Google Gemini 提供商实现。"""
from typing import AsyncIterator, Dict, List

from google import genai
from google.genai import types

from app.ai.base import AIProvider


class GeminiProvider(AIProvider):
    """Google Gemini 提供商，基于新版 google-genai SDK。"""

    def __init__(self, api_key: str, model: str = "gemini-1.5-flash"):
        super().__init__(api_key, model)
        self.client = genai.Client(api_key=api_key)

    def _convert_messages(self, messages: List[Dict[str, str]]) -> str:
        conversation = []
        for msg in messages:
            role = "User" if msg.get("role") == "user" else "Assistant"
            conversation.append(f"{role}: {msg.get('content', '')}")
        return "\n\n".join(conversation)

    async def chat(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = None,
        temperature: float = 0.7,
    ) -> str:
        """同步对话。"""
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=self._convert_messages(messages),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
            ),
        )
        return response.text or ""

    async def chat_stream(
        self,
        messages: List[Dict[str, str]],
        system_prompt: str = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """流式对话。"""
        stream = await self.client.aio.models.generate_content_stream(
            model=self.model,
            contents=self._convert_messages(messages),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
            ),
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text
