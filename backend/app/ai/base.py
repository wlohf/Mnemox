"""AI 提供商基类"""
from abc import ABC, abstractmethod
from typing import List, Dict, AsyncIterator


class AIProvider(ABC):
    """AI 提供商统一接口"""
    
    def __init__(self, api_key: str, model: str):
        self.api_key = api_key
        self.model = model
    
    @abstractmethod
    async def chat(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = None,
        temperature: float = 0.7
    ) -> str:
        """
        同步对话
        
        Args:
            messages: 对话消息列表 [{"role": "user", "content": "..."}, ...]
            system_prompt: 系统提示词
            temperature: 温度参数（0-1）
            
        Returns:
            AI 的回复内容
        """
        pass
    
    @abstractmethod
    async def chat_stream(
        self, 
        messages: List[Dict[str, str]], 
        system_prompt: str = None,
        temperature: float = 0.7
    ) -> AsyncIterator[str]:
        """
        流式对话
        
        Args:
            messages: 对话消息列表
            system_prompt: 系统提示词
            temperature: 温度参数
            
        Yields:
            AI 回复的文本块
        """
        pass
