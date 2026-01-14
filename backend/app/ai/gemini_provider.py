"""Google Gemini 提供商实现"""
from typing import List, Dict, AsyncIterator
import google.generativeai as genai
from app.ai.base import AIProvider


class GeminiProvider(AIProvider):
    """Google Gemini 提供商"""
    
    def __init__(self, api_key: str, model: str = "gemini-pro"):
        super().__init__(api_key, model)
        genai.configure(api_key=api_key)
        self.model_instance = genai.GenerativeModel(model)
    
    def _convert_messages(self, messages: List[Dict[str, str]], system_prompt: str = None) -> str:
        """将消息格式转换为 Gemini 格式"""
        # Gemini 使用简单的文本格式
        conversation = []
        
        if system_prompt:
            conversation.append(f"System: {system_prompt}")
        
        for msg in messages:
            role = "User" if msg["role"] == "user" else "Assistant"
            conversation.append(f"{role}: {msg['content']}")
        
        return "\n\n".join(conversation)
    
    async def chat(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = None,
        temperature: float = 0.7
    ) -> str:
        """同步对话"""
        prompt = self._convert_messages(messages, system_prompt)
        
        response = await self.model_instance.generate_content_async(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature
            )
        )
        
        return response.text
    
    async def chat_stream(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = None,
        temperature: float = 0.7
    ) -> AsyncIterator[str]:
        """流式对话"""
        prompt = self._convert_messages(messages, system_prompt)
        
        response = await self.model_instance.generate_content_async(
            prompt,
            generation_config=genai.types.GenerationConfig(
                temperature=temperature
            ),
            stream=True
        )
        
        async for chunk in response:
            if chunk.text:
                yield chunk.text
