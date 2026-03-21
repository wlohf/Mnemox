"""Anthropic Claude 提供商实现"""
import re
import json
from typing import List, Dict, Any, AsyncIterator, Optional
import httpx
from app.ai.base import AIProvider


class ClaudeProvider(AIProvider):
    """Anthropic Claude 提供商"""

    def __init__(self, api_key: str, model: str = "claude-3-opus-20240229", base_url: Optional[str] = None):
        super().__init__(api_key, model)
        self.base_url = "https://api.anthropic.com"
        if base_url:
            self.base_url = base_url.rstrip("/")

    def _messages_url(self) -> str:
        if self.base_url.endswith("/v1/messages"):
            return self.base_url
        return f"{self.base_url}/v1/messages"

    def _headers(self) -> Dict[str, str]:
        return {
            "x-api-key": self.api_key,
            "anthropic-version": "2023-06-01",
            "content-type": "application/json",
        }

    def _supports_image_input(self) -> bool:
        model_name = (self.model or "").lower()
        return "claude" in model_name or "vision" in model_name

    def _convert_messages(self, messages: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
        """Convert OpenAI-format image_url blocks to Claude's image format."""
        converted = []
        for msg in messages:
            content = msg.get("content")
            if not isinstance(content, list):
                converted.append(msg)
                continue
            if not self._supports_image_input():
                text_parts = [
                    part.get("text", "")
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                text = "".join(text_parts).strip()
                if not text:
                    text = "[图片已省略：当前模型不支持图像输入]"
                converted.append({"role": msg.get("role"), "content": text})
                continue
            new_parts = []
            for part in content:
                if part.get("type") == "image_url":
                    url = (part.get("image_url") or {}).get("url", "")
                    # Parse data URI: data:<media_type>;base64,<data>
                    m = re.match(r"data:([^;]+);base64,(.+)", url, re.DOTALL)
                    if m:
                        new_parts.append({
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": m.group(1),
                                "data": m.group(2),
                            },
                        })
                    else:
                        # URL-based image — Claude supports url source type
                        new_parts.append({
                            "type": "image",
                            "source": {"type": "url", "url": url},
                        })
                else:
                    new_parts.append(part)
            converted.append({**msg, "content": new_parts})
        return converted

    async def chat(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> str:
        """同步对话"""
        converted_messages = self._convert_messages(messages)
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": converted_messages,
        }
        if system_prompt:
            payload["system"] = system_prompt

        async with httpx.AsyncClient(timeout=120.0) as client:
            response = await client.post(
                self._messages_url(),
                headers=self._headers(),
                json=payload,
            )
            response.raise_for_status()
            data = response.json()

        content = data.get("content") or []
        texts = [
            block.get("text", "")
            for block in content
            if isinstance(block, dict) and block.get("type") == "text"
        ]
        return "".join(texts)

    async def chat_stream(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7
    ) -> AsyncIterator[str]:
        """流式对话"""
        converted_messages = self._convert_messages(messages)
        payload: Dict[str, Any] = {
            "model": self.model,
            "max_tokens": 4096,
            "temperature": temperature,
            "messages": converted_messages,
            "stream": True,
        }
        if system_prompt:
            payload["system"] = system_prompt

        async with httpx.AsyncClient(timeout=120.0) as client:
            async with client.stream(
                "POST",
                self._messages_url(),
                headers=self._headers(),
                json=payload,
            ) as response:
                response.raise_for_status()
                async for line in response.aiter_lines():
                    if not line or not line.startswith("data:"):
                        continue

                    raw_data = line[len("data:"):].strip()
                    if not raw_data:
                        continue

                    try:
                        event = json.loads(raw_data)
                    except Exception:
                        continue

                    if event.get("type") == "content_block_delta":
                        delta = event.get("delta") or {}
                        if delta.get("type") == "text_delta":
                            text = delta.get("text", "")
                            if text:
                                yield text
