"""OpenAI 提供商实现"""
from typing import List, Dict, AsyncIterator
from openai import AsyncOpenAI
from app.ai.base import AIProvider


class OpenAIProvider(AIProvider):
    """OpenAI (GPT-4, GPT-3.5) 提供商"""
    
    def __init__(self, api_key: str, model: str = "gpt-4", base_url: str = None):
        super().__init__(api_key, model)
        self.client = AsyncOpenAI(
            api_key=api_key,
            base_url=base_url
        )
    
    async def chat(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = None,
        temperature: float = 0.7
    ) -> str:
        """同步对话"""
        # 如果有系统提示词，添加到消息列表开头
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages
        
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature
        )
        
        return response.choices[0].message.content
    
    async def chat_stream(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = None,
        temperature: float = 0.7
    ) -> AsyncIterator[str]:
        """流式对话"""
        # 如果有系统提示词，添加到消息列表开头
        if system_prompt:
            messages = [{"role": "system", "content": system_prompt}] + messages
        
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=messages,
            temperature=temperature,
            stream=True
        )
        
        async for chunk in stream:
            if chunk.choices[0].delta.content:
                yield chunk.choices[0].delta.content
