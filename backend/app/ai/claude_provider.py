"""Anthropic Claude 提供商实现"""
from typing import List, Dict, AsyncIterator
from anthropic import AsyncAnthropic
from app.ai.base import AIProvider


class ClaudeProvider(AIProvider):
    """Anthropic Claude 提供商"""
    
    def __init__(self, api_key: str, model: str = "claude-3-opus-20240229", base_url: str = None):
        super().__init__(api_key, model)
        kwargs = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncAnthropic(**kwargs)
    
    async def chat(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = None,
        temperature: float = 0.7
    ) -> str:
        """同步对话"""
        response = await self.client.messages.create(
            model=self.model,
            max_tokens=4096,
            temperature=temperature,
            system=system_prompt if system_prompt else "",
            messages=messages
        )
        
        return response.content[0].text
    
    async def chat_stream(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = None,
        temperature: float = 0.7
    ) -> AsyncIterator[str]:
        """流式对话"""
        async with self.client.messages.stream(
            model=self.model,
            max_tokens=4096,
            temperature=temperature,
            system=system_prompt if system_prompt else "",
            messages=messages
        ) as stream:
            async for text in stream.text_stream:
                yield text
