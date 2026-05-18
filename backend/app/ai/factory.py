"""AI 提供商工厂"""
from typing import Optional
from sqlalchemy.ext.asyncio import AsyncSession
from sqlalchemy import select
from app.ai.base import AIProvider
from app.config import settings
from app.utils.secret_crypto import decrypt_secret


class AIProviderFactory:
    """AI 提供商工厂类"""

    @staticmethod
    def _resolve_provider_kind(provider_name: str, base_url: str = "", model: str = "") -> str:
        name = provider_name.lower()
        if name in ("openai", "deepseek", "qwen"):
            return "openai"
        if name == "claude":
            return "claude"
        if name == "gemini":
            return "gemini"

        if name.startswith("anthropic-") or name.startswith("claude-"):
            return "claude"
        if name.startswith("gemini-"):
            return "gemini"
        if name.startswith("openai-") or name.startswith("deepseek-") or name.startswith("qwen-"):
            return "openai"

        base = (base_url or "").lower()
        if "/v1/messages" in base:
            return "claude"
        if "/v1beta/models" in base:
            return "gemini"

        if "claude" in (model or "").lower():
            return "claude"
        if "gemini" in (model or "").lower():
            return "gemini"

        return "openai"

    @staticmethod
    def create_provider_from_settings(
        provider_name: str,
        api_key: str,
        model: str,
        base_url: str = "",
    ) -> AIProvider:
        """根据参数直接创建提供商实例（供 test 接口和数据库查询使用）"""
        kind = AIProviderFactory._resolve_provider_kind(provider_name, base_url, model)

        if kind == "openai":
            from app.ai.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=api_key,
                model=model,
                base_url=base_url or None,
            )
        elif kind == "claude":
            from app.ai.claude_provider import ClaudeProvider
            return ClaudeProvider(
                api_key=api_key,
                model=model,
                base_url=base_url or None,
            )
        elif kind == "gemini":
            from app.ai.gemini_provider import GeminiProvider
            return GeminiProvider(
                api_key=api_key,
                model=model,
            )
        else:
            from app.ai.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=api_key,
                model=model,
                base_url=base_url or None,
            )

    @staticmethod
    async def create_provider(
        provider_name: Optional[str] = None,
        model: Optional[str] = None,
        scenario: Optional[str] = None,
        db: Optional[AsyncSession] = None,
        user_id: Optional[int] = None,
    ) -> AIProvider:
        """
        创建 AI 提供商实例

        有 user_id 时优先从数据库读取当前用户的提供商配置，回退到 .env 配置。

        Args:
            provider_name: 提供商名称，为 None 时使用当前用户激活的提供商或 .env 默认值
            db: 可选的数据库会话
            user_id: 当前用户 ID；未提供时不会查询用户级数据库配置

        Returns:
            AI 提供商实例
        """
        # 只有提供 user_id 时才读取用户级数据库配置，避免跨用户误用激活提供商。
        if db is not None and user_id is not None:
            from app.models.ai_settings import AIProviderSetting

            resolved_provider_name = provider_name

            if not resolved_provider_name and scenario:
                from app.models.ai_routing import AIRoutingSetting

                route_query = select(AIRoutingSetting).where(
                    AIRoutingSetting.scenario == scenario,
                    AIRoutingSetting.user_id == user_id,
                )
                route_result = await db.execute(route_query)
                route_row = route_result.scalar_one_or_none()
                if route_row and route_row.provider_name:
                    resolved_provider_name = route_row.provider_name
                if route_row and route_row.model and not model:
                    model = route_row.model

            if resolved_provider_name:
                provider_query = select(AIProviderSetting).where(
                    AIProviderSetting.provider_name == resolved_provider_name.lower(),
                    AIProviderSetting.user_id == user_id,
                )
                result = await db.execute(provider_query)
                row = result.scalar_one_or_none()
            else:
                active_query = select(AIProviderSetting).where(
                    AIProviderSetting.is_active == True,
                    AIProviderSetting.user_id == user_id,
                )
                result = await db.execute(active_query)
                row = result.scalar_one_or_none()

            if row:
                if not row.enabled:
                    raise ValueError(f"{row.display_name or row.provider_name} 已禁用")
                api_key = decrypt_secret(row.api_key)
                if not api_key:
                    raise ValueError(f"{row.display_name or row.provider_name} API Key 未配置")
                return AIProviderFactory.create_provider_from_settings(
                    provider_name=row.provider_name,
                    api_key=api_key,
                    model=model or row.model,
                    base_url=row.base_url,
                )

        # 回退到 .env 配置
        if provider_name is None:
            provider_name = settings.DEFAULT_AI_PROVIDER

        provider_name = provider_name.lower()

        if provider_name == "openai":
            if not settings.OPENAI_API_KEY:
                raise ValueError("OpenAI API Key 未配置")
            from app.ai.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=settings.OPENAI_API_KEY,
                model=model or settings.OPENAI_MODEL,
                base_url=settings.OPENAI_BASE_URL if settings.OPENAI_BASE_URL != "https://api.openai.com/v1" else None
            )

        elif provider_name == "claude":
            if not settings.CLAUDE_API_KEY:
                raise ValueError("Claude API Key 未配置")
            from app.ai.claude_provider import ClaudeProvider
            return ClaudeProvider(
                api_key=settings.CLAUDE_API_KEY,
                model=model or settings.CLAUDE_MODEL,
                base_url=settings.CLAUDE_BASE_URL if hasattr(settings, 'CLAUDE_BASE_URL') else None
            )

        elif provider_name == "gemini":
            if not settings.GEMINI_API_KEY:
                raise ValueError("Gemini API Key 未配置")
            from app.ai.gemini_provider import GeminiProvider
            return GeminiProvider(
                api_key=settings.GEMINI_API_KEY,
                model=model or settings.GEMINI_MODEL
            )

        elif provider_name == "deepseek":
            if not settings.DEEPSEEK_API_KEY:
                raise ValueError("DeepSeek API Key 未配置")
            from app.ai.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=settings.DEEPSEEK_API_KEY,
                model=model or settings.DEEPSEEK_MODEL,
                base_url=settings.DEEPSEEK_BASE_URL,
            )

        elif provider_name == "qwen":
            if not settings.QWEN_API_KEY:
                raise ValueError("Qwen API Key 未配置")
            from app.ai.openai_provider import OpenAIProvider
            return OpenAIProvider(
                api_key=settings.QWEN_API_KEY,
                model=model or settings.QWEN_MODEL,
                base_url=settings.QWEN_BASE_URL,
            )

        else:
            raise ValueError(f"不支持的 AI 提供商: {provider_name}")


async def get_ai_provider(db: AsyncSession = None) -> AIProvider:
    """获取 AI 提供商实例（依赖注入）"""
    return await AIProviderFactory.create_provider(db=db)
