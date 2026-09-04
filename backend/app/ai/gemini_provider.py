"""Google Gemini 提供商实现。"""
from typing import AsyncIterator, Dict, List, Optional

from google import genai
from google.genai import types

from app.ai.base import AIProvider


class GeminiProvider(AIProvider):
    """Google Gemini 提供商，基于新版 google-genai SDK。"""

    def __init__(
        self,
        api_key: str,
        model: str = "gemini-1.5-flash",
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        input_price_per_million: Optional[float] = None,
        output_price_per_million: Optional[float] = None,
        provider_name: Optional[str] = None,
    ):
        super().__init__(
            api_key,
            model,
            max_context_tokens=max_context_tokens,
            max_output_tokens=max_output_tokens,
            input_price_per_million=input_price_per_million,
            output_price_per_million=output_price_per_million,
            provider_name=provider_name,
        )
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
        self.clear_last_usage()
        response = await self.client.aio.models.generate_content(
            model=self.model,
            contents=self._convert_messages(messages),
            config=types.GenerateContentConfig(
                system_instruction=system_prompt,
                temperature=temperature,
                max_output_tokens=self.max_output_tokens,
            ),
        )
        usage = getattr(response, "usage_metadata", None)
        self.record_last_usage(
            input_tokens=getattr(usage, "prompt_token_count", 0),
            output_tokens=getattr(usage, "candidates_token_count", 0),
            total_tokens=getattr(usage, "total_token_count", 0),
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
                max_output_tokens=self.max_output_tokens,
            ),
        )
        async for chunk in stream:
            if chunk.text:
                yield chunk.text
