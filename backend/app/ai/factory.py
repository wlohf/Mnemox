"""AI 提供商工厂"""
from typing import Optional
from app.ai.base import AIProvider
from app.ai.openai_provider import OpenAIProvider
from app.ai.claude_provider import ClaudeProvider
from app.ai.gemini_provider import GeminiProvider
from app.config import settings


class AIProviderFactory:
    """AI 提供商工厂类"""
    
    @staticmethod
    def create_provider(provider_name: Optional[str] = None) -> AIProvider:
        """
        创建 AI 提供商实例
        
        Args:
            provider_name: 提供商名称 (openai, claude, gemini, qwen)
                          如果为 None，使用配置文件中的默认提供商
        
        Returns:
            AI 提供商实例
        
        Raises:
            ValueError: 如果提供商名称无效或 API Key 未配置
        """
        if provider_name is None:
            provider_name = settings.DEFAULT_AI_PROVIDER
        
        provider_name = provider_name.lower()
        
        if provider_name == "openai":
            if not settings.OPENAI_API_KEY:
                raise ValueError("OpenAI API Key 未配置")
            return OpenAIProvider(
                api_key=settings.OPENAI_API_KEY,
                model=settings.OPENAI_MODEL,
                base_url=settings.OPENAI_BASE_URL if settings.OPENAI_BASE_URL != "https://api.openai.com/v1" else None
            )
        
        elif provider_name == "claude":
            if not settings.CLAUDE_API_KEY:
                raise ValueError("Claude API Key 未配置")
            return ClaudeProvider(
                api_key=settings.CLAUDE_API_KEY,
                model=settings.CLAUDE_MODEL,
                base_url=settings.CLAUDE_BASE_URL if hasattr(settings, 'CLAUDE_BASE_URL') else None
            )
        
        elif provider_name == "gemini":
            if not settings.GEMINI_API_KEY:
                raise ValueError("Gemini API Key 未配置")
            return GeminiProvider(
                api_key=settings.GEMINI_API_KEY,
                model=settings.GEMINI_MODEL
            )
        
        elif provider_name == "qwen":
            # TODO: 实现 Qwen 提供商
            raise NotImplementedError("Qwen 提供商尚未实现")
        
        else:
            raise ValueError(f"不支持的 AI 提供商: {provider_name}")


# 全局 AI 服务实例（使用默认配置）
def get_ai_provider() -> AIProvider:
    """获取 AI 提供商实例（依赖注入）"""
    return AIProviderFactory.create_provider()
