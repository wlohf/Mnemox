"""AI 提供商基类"""
from abc import ABC, abstractmethod
from decimal import Decimal, InvalidOperation
from typing import List, Dict, AsyncIterator, Optional, Any


class AIProvider(ABC):
    """AI 提供商统一接口"""
    
    def __init__(
        self,
        api_key: str,
        model: str,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
        input_price_per_million: Optional[float] = None,
        output_price_per_million: Optional[float] = None,
        provider_name: Optional[str] = None,
    ):
        self.api_key = api_key
        self.model = model
        self.max_context_tokens = max_context_tokens
        self.max_output_tokens = max_output_tokens or 4096
        self.provider_name = (provider_name or self.__class__.__name__).strip()
        self.input_price_per_million = self._price_decimal(input_price_per_million)
        self.output_price_per_million = self._price_decimal(output_price_per_million)
        self._last_usage: Dict[str, Any] = {}

    @staticmethod
    def _price_decimal(value: Optional[float]) -> Optional[Decimal]:
        if value is None:
            return None
        try:
            price = Decimal(str(value))
        except (InvalidOperation, TypeError, ValueError):
            return None
        return price if price >= 0 else None

    @staticmethod
    def _usage_int(value: Any) -> int:
        try:
            return max(0, int(value or 0))
        except (TypeError, ValueError):
            return 0

    def clear_last_usage(self) -> None:
        """Discard a previous response's accounting before a new request."""
        self._last_usage = {}

    def record_last_usage(
        self,
        *,
        input_tokens: Any,
        output_tokens: Any,
        total_tokens: Any = None,
        source: str = "provider",
    ) -> None:
        """Store one provider-reported usage record without retaining prompts."""
        input_count = self._usage_int(input_tokens)
        output_count = self._usage_int(output_tokens)
        total_count = self._usage_int(total_tokens) or input_count + output_count
        if total_count <= 0:
            self._last_usage = {}
            return

        cost: Optional[Decimal] = None
        if self.input_price_per_million is not None and self.output_price_per_million is not None:
            cost = (
                self.input_price_per_million * Decimal(input_count)
                + self.output_price_per_million * Decimal(output_count)
            ) / Decimal(1_000_000)

        self._last_usage = {
            "source": source,
            "provider": self.provider_name,
            "model": self.model,
            "input_tokens": input_count,
            "output_tokens": output_count,
            "total_tokens": total_count,
            "configured_cost_usd": float(cost.quantize(Decimal("0.00000001"))) if cost is not None else None,
            "pricing_configured": cost is not None,
        }

    def get_last_usage(self) -> Dict[str, Any]:
        """Return a detached usage snapshot for the most recent completed call."""
        return dict(self._last_usage)

    def supports_web_search(self) -> bool:
        """Whether this provider can answer with web search enabled."""
        return False

    def supports_structured_output(self) -> bool:
        """Whether the provider exposes a native strict-schema response mode."""
        return False

    async def chat_structured(
        self,
        messages: List[Dict[str, str]],
        response_model: Any,
        system_prompt: str = None,
        temperature: float = 0.1,
    ) -> Any:
        """Optional native structured-output call; normal chat stays unchanged."""
        raise NotImplementedError("structured output is not supported by this provider")
    
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
