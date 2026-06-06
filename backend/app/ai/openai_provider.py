"""OpenAI 提供商实现"""
import json
from typing import List, Dict, AsyncIterator, Any, Optional, cast

from openai import AsyncOpenAI
from app.ai.base import AIProvider
from app.services.web_search import search_web


LOCAL_WEB_SEARCH_TOOL = {
    "type": "function",
    "function": {
        "name": "web_search",
        "description": "当用户需要最新信息、实时网页资料或你不确定答案时，联网搜索公开网页。",
        "parameters": {
            "type": "object",
            "properties": {
                "query": {"type": "string", "description": "搜索关键词或问题"},
                "max_results": {
                    "type": "integer",
                    "description": "返回结果数量，默认 5，最多 10",
                },
            },
            "required": ["query"],
        },
    },
}

LOCAL_WEB_SEARCH_INSTRUCTION = (
    "\n\n【联网搜索工具】\n"
    "用户已开启联网搜索。遇到最新信息、实时资料、网页事实或你不确定的内容时，"
    "请调用 web_search 工具。不要声称已经搜索，除非工具结果支持。"
    "引用网页信息时请附上对应 URL。"
)


class OpenAIProvider(AIProvider):
    """OpenAI (GPT-4, GPT-3.5) 提供商"""
    
    def __init__(self, api_key: str, model: str = "gpt-4", base_url: Optional[str] = None):
        super().__init__(api_key, model)
        self.base_url = (base_url or "").rstrip("/")
        kwargs: Dict[str, Any] = {"api_key": api_key}
        if base_url:
            kwargs["base_url"] = base_url
        self.client = AsyncOpenAI(**kwargs)

    def _uses_official_openai_api(self) -> bool:
        return not self.base_url or self.base_url == "https://api.openai.com/v1"

    def supports_web_search(self) -> bool:
        # Official OpenAI uses hosted Responses API search. OpenAI-compatible
        # relays can use the app's local search function through chat tools.
        return True

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

    def _get_attr_or_key(self, value: Any, key: str, default: Any = None) -> Any:
        if isinstance(value, dict):
            return value.get(key, default)
        return getattr(value, key, default)

    def _tool_call_to_dict(self, tool_call: Any) -> Dict[str, Any]:
        function = self._get_attr_or_key(tool_call, "function", {})
        return {
            "id": self._get_attr_or_key(tool_call, "id", ""),
            "type": self._get_attr_or_key(tool_call, "type", "function"),
            "function": {
                "name": self._get_attr_or_key(function, "name", ""),
                "arguments": self._get_attr_or_key(function, "arguments", "{}"),
            },
        }

    def _assistant_message_to_dict(self, message: Any) -> Dict[str, Any]:
        payload: Dict[str, Any] = {
            "role": "assistant",
            "content": self._get_attr_or_key(message, "content"),
        }
        tool_calls = self._get_attr_or_key(message, "tool_calls") or []
        if tool_calls:
            payload["tool_calls"] = [self._tool_call_to_dict(tool_call) for tool_call in tool_calls]
        return payload

    def _tool_call_name(self, tool_call: Any) -> str:
        function = self._get_attr_or_key(tool_call, "function", {})
        return str(self._get_attr_or_key(function, "name", ""))

    def _tool_call_arguments(self, tool_call: Any) -> str:
        function = self._get_attr_or_key(tool_call, "function", {})
        return str(self._get_attr_or_key(function, "arguments", "{}") or "{}")

    async def _run_local_web_search_tool(self, arguments: str) -> str:
        try:
            args = json.loads(arguments or "{}")
        except json.JSONDecodeError:
            return json.dumps({"error": "工具参数不是有效 JSON。"}, ensure_ascii=False)

        query = str(args.get("query") or "").strip()
        if not query:
            return json.dumps({"error": "缺少搜索关键词 query。"}, ensure_ascii=False)

        try:
            max_results = int(args.get("max_results") or 5)
        except (TypeError, ValueError):
            max_results = 5
        max_results = max(1, min(max_results, 10))

        try:
            results = await search_web(query, limit=max_results)
        except Exception as exc:
            return json.dumps(
                {"query": query, "error": f"搜索失败：{exc}"},
                ensure_ascii=False,
            )

        return json.dumps(
            {
                "query": query,
                "results": [
                    {
                        "title": item.title,
                        "url": item.url,
                        "snippet": item.snippet,
                    }
                    for item in results
                ],
            },
            ensure_ascii=False,
        )

    def _looks_like_tool_unsupported_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        tool_markers = ("tool", "tools", "function", "tool_calls", "function_call")
        unsupported_markers = (
            "unsupported",
            "not support",
            "does not support",
            "unrecognized",
            "unknown parameter",
            "invalid parameter",
            "不支持",
        )
        return any(marker in text for marker in tool_markers) and any(
            marker in text for marker in unsupported_markers
        )
    
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
        """Stream a response with web search.

        Official OpenAI uses hosted Responses API search. OpenAI-compatible
        relay endpoints use Chat Completions function tools and execute the
        search locally in Mnemox.
        """
        if not self._uses_official_openai_api():
            async for chunk in self._chat_stream_with_local_web_search(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature,
            ):
                yield chunk
            return

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

    async def _chat_stream_with_local_web_search(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Use OpenAI-compatible function calling to search locally."""
        effective_system_prompt = (system_prompt or "") + LOCAL_WEB_SEARCH_INSTRUCTION
        conversation: List[Dict[str, Any]] = [{"role": "system", "content": effective_system_prompt}]
        conversation.extend(self._normalize_messages(messages))

        max_tool_rounds = 4
        for _ in range(max_tool_rounds):
            try:
                response = await self.client.chat.completions.create(
                    model=self.model,
                    messages=cast(Any, conversation),
                    temperature=temperature,
                    max_tokens=4096,
                    tools=cast(Any, [LOCAL_WEB_SEARCH_TOOL]),
                    tool_choice="auto",
                )
            except Exception as exc:
                if self._looks_like_tool_unsupported_error(exc):
                    raise ValueError("当前供应商不支持工具调用联网搜索。") from exc
                raise

            message = response.choices[0].message
            conversation.append(self._assistant_message_to_dict(message))
            tool_calls = self._get_attr_or_key(message, "tool_calls") or []
            if not tool_calls:
                content = self._get_attr_or_key(message, "content", "") or ""
                if content:
                    yield str(content)
                return

            for tool_call in tool_calls:
                name = self._tool_call_name(tool_call)
                if name != "web_search":
                    result = json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)
                else:
                    result = await self._run_local_web_search_tool(self._tool_call_arguments(tool_call))
                conversation.append(
                    {
                        "role": "tool",
                        "tool_call_id": self._get_attr_or_key(tool_call, "id", ""),
                        "name": name,
                        "content": result,
                    }
                )

        conversation.append(
            {
                "role": "user",
                "content": "请基于已经获得的搜索结果给出最终回答，不要继续调用工具。",
            }
        )
        response = await self.client.chat.completions.create(
            model=self.model,
            messages=cast(Any, conversation),
            temperature=temperature,
            max_tokens=4096,
        )
        content = response.choices[0].message.content or ""
        if content:
            yield content
