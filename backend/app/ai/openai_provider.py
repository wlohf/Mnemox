"""OpenAI 提供商实现"""
from typing import List, Dict, AsyncIterator, Any, Optional, cast
from openai import AsyncOpenAI
from app.ai.base import AIProvider


class OpenAIProvider(AIProvider):
    """OpenAI (GPT-4, GPT-3.5) 提供商"""
    
    def __init__(self, api_key: str, model: str = "gpt-4", base_url: Optional[str] = None):
        super().__init__(api_key, model)
        self.base_url = (base_url or "").rstrip("/")
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**kwargs)

    def supports_web_search(self) -> bool:
        return not self.base_url or self.base_url == "https://api.openai.com/v1"

    def _supports_image_input(self) -> bool:
        model_name = (self.model or "").lower()
        image_models = (
            "gpt-4o",
            "gpt-4.1",
            "gpt-4-vision",
            "gpt-4v",
            "gpt-4o-mini",
            "gpt-4.1-mini",
        )
        return any(token in model_name for token in image_models)

    def _normalize_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        if self._supports_image_input():
            return messages

        normalized: List[Dict[str, Any]] = []
        for msg in messages:
            content = msg.get("content")
            if isinstance(content, list):
                text_parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                text = "".join(text_parts).strip()
                if not text:
                    text = "[图片已省略：当前模型不支持图像输入]"
                normalized.append({"role": msg.get("role"), "content": text})
            else:
                normalized.append(msg)
        return normalized

    def _responses_input(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        input_items: List[Dict[str, Any]] = []
        for msg in messages:
            role = msg.get("role")
            content = msg.get("content")
            if isinstance(content, list):
                parts: List[Dict[str, Any]] = []
                for part in content:
                    if not isinstance(part, dict):
                        continue
                    if part.get("type") == "text":
                        parts.append({"type": "input_text", "text": part.get("text", "")})
                    elif part.get("type") == "image_url":
                        url = (part.get("image_url") or {}).get("url", "")
                        if url:
                            parts.append({"type": "input_image", "image_url": url, "detail": "auto"})
                if not parts:
                    parts.append({"type": "input_text", "text": ""})
                input_items.append({"type": "message", "role": role, "content": parts})
            else:
                input_items.append({
                    "type": "message",
                    "role": role,
                    "content": str(content or ""),
                })
        return input_items
    
    async def chat(
        self, 
        messages: List[Dict[str, Any]], 
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> str:
        """同步对话"""
        # 如果有系统提示词，添加到消息列表开头
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        normalized_messages = self._normalize_messages(messages)
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=cast(Any, normalized_messages),
            temperature=temperature,
            max_tokens=4096,
        )
        
        return response.choices[0].message.content or ""
    
    async def chat_stream(
        self, 
        messages: List[Dict[str, Any]], 
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> AsyncIterator[str]:
        """流式对话"""
        # 如果有系统提示词，添加到消息列表开头
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages

        normalized_messages = self._normalize_messages(messages)
        
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=cast(Any, normalized_messages),
            temperature=temperature,
            stream=True
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content

    async def chat_stream_with_web_search(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream a response using OpenAI Responses API hosted web search."""
        if not self.supports_web_search():
            raise ValueError("当前供应商不支持 OpenAI 内置联网搜索，请切换到官方 OpenAI。")

        input_items = self._responses_input(messages)
        async with self.client.responses.stream(
            model=self.model,
            input=cast(Any, input_items),
            instructions=system_prompt,
            temperature=temperature,
            max_output_tokens=4096,
            tools=[{"type": "web_search", "search_context_size": "medium"}],
            include=["web_search_call.action.sources"],
        ) as stream:
            async for event in stream:
                if getattr(event, "type", None) == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield delta
