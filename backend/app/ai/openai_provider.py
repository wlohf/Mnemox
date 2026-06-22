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

LOCAL_WEB_SEARCH_RESPONSE_TOOL = {
    "type": "function",
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
        "additionalProperties": False,
    },
    "strict": True,
}

LOCAL_WEB_SEARCH_INSTRUCTION = (
    "\n\n【联网搜索工具】\n"
    "用户已开启联网搜索。遇到最新信息、实时资料、网页事实或你不确定的内容时，"
    "请调用 web_search 工具。不要声称已经搜索，除非工具结果支持。"
    "引用网页信息时请附上对应 URL。"
)

DEFAULT_RESPONSES_INSTRUCTIONS = "你是一个有帮助的 AI 助手。"


class OpenAIProvider(AIProvider):
    """OpenAI (GPT-4, GPT-3.5) 提供商"""
    
    def __init__(
        self,
        api_key: str,
        model: str = "gpt-4",
        base_url: Optional[str] = None,
        max_context_tokens: Optional[int] = None,
        max_output_tokens: Optional[int] = None,
    ):
        super().__init__(
            api_key,
            model,
            max_context_tokens=max_context_tokens,
            max_output_tokens=max_output_tokens,
        )
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

    def _responses_instructions(self, instructions: Optional[str]) -> str:
        text = (instructions or "").strip()
        return text or DEFAULT_RESPONSES_INSTRUCTIONS

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

    def _response_tool_call_name(self, tool_call: Any) -> str:
        return str(self._get_attr_or_key(tool_call, "name", ""))

    def _response_tool_call_arguments(self, tool_call: Any) -> str:
        return str(self._get_attr_or_key(tool_call, "arguments", "{}") or "{}")

    def _response_tool_call_id(self, tool_call: Any) -> str:
        return str(
            self._get_attr_or_key(tool_call, "call_id", None)
            or self._get_attr_or_key(tool_call, "id", "")
        )

    def _latest_user_text(self, messages: List[Dict[str, Any]]) -> str:
        for msg in reversed(messages):
            if msg.get("role") != "user":
                continue
            content = msg.get("content")
            if isinstance(content, list):
                text_parts = [
                    str(part.get("text", ""))
                    for part in content
                    if isinstance(part, dict) and part.get("type") == "text"
                ]
                return " ".join(text_parts)
            return str(content or "")
        return ""

    def _should_force_local_web_search(self, messages: List[Dict[str, Any]]) -> bool:
        text = self._latest_user_text(messages).lower()
        if not text.strip():
            return False

        triggers = (
            "最新",
            "今天",
            "昨日",
            "昨天",
            "明天",
            "现在",
            "当前",
            "近期",
            "最近",
            "新闻",
            "搜索",
            "联网",
            "查一下",
            "查下",
            "网上",
            "官网",
            "价格",
            "股价",
            "汇率",
            "天气",
            "版本",
            "发布",
            "更新",
            "latest",
            "current",
            "today",
            "yesterday",
            "tomorrow",
            "recent",
            "news",
            "price",
            "stock",
            "weather",
            "release",
            "version",
            "search",
            "web",
        )
        return any(trigger in text for trigger in triggers)

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
        if (
            "instructions are required" in text
            or "missing required parameter: instructions" in text
        ):
            return True
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

    def _looks_like_responses_unsupported_error(self, exc: Exception) -> bool:
        text = str(exc).lower()
        response_markers = ("responses", "/responses", "response api", "response_api")
        hosted_search_markers = (
            "web_search",
            "web search",
            "web_search_call",
            "search_context_size",
        )
        tool_param_markers = (
            "tools",
            "tool_choice",
            "include",
        )
        unsupported_markers = (
            "404",
            "not found",
            "unsupported",
            "not support",
            "does not support",
            "unknown endpoint",
            "unrecognized",
            "connection error",
            "connecterror",
            "api connection",
            "upstream_error",
            "upstream request failed",
            "不支持",
        )
        instructions_required_markers = (
            "instructions are required",
            "missing required parameter: instructions",
        )
        if any(marker in text for marker in instructions_required_markers):
            return True
        if any(
            marker in text
            for marker in (
                "connection error",
                "connecterror",
                "api connection",
                "upstream_error",
                "upstream request failed",
            )
        ):
            return True
        if any(marker in text for marker in unsupported_markers) and any(
            marker in text for marker in hosted_search_markers
        ):
            return True
        if any(marker in text for marker in unsupported_markers) and any(
            marker in text for marker in tool_param_markers
        ):
            return True
        return any(marker in text for marker in response_markers) and any(
            marker in text for marker in unsupported_markers
        )

    def _merge_response_function_call_item(
        self,
        function_calls: Dict[int, Dict[str, Any]],
        output_index: Any,
        item: Any,
    ) -> None:
        try:
            index = int(output_index)
        except (TypeError, ValueError):
            index = len(function_calls)

        current = function_calls.setdefault(
            index,
            {
                "type": "function_call",
                "id": "",
                "call_id": "",
                "name": "",
                "arguments": "",
            },
        )

        item_type = self._get_attr_or_key(item, "type", None)
        if item_type:
            current["type"] = str(item_type)
        item_id = self._get_attr_or_key(item, "id", None)
        if item_id:
            current["id"] = str(item_id)
        call_id = self._get_attr_or_key(item, "call_id", None)
        if call_id:
            current["call_id"] = str(call_id)
        name = self._get_attr_or_key(item, "name", None)
        if name:
            current["name"] = str(name)
        arguments = self._get_attr_or_key(item, "arguments", None)
        if arguments:
            current["arguments"] = str(arguments)

    def _merge_response_function_call_delta(
        self,
        function_calls: Dict[int, Dict[str, Any]],
        output_index: Any,
        delta: Any,
    ) -> None:
        try:
            index = int(output_index)
        except (TypeError, ValueError):
            index = len(function_calls)

        current = function_calls.setdefault(
            index,
            {
                "type": "function_call",
                "id": "",
                "call_id": "",
                "name": "",
                "arguments": "",
            },
        )
        if delta:
            current["arguments"] += str(delta)

    def _finalize_response_function_calls(self, function_calls: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
        finalized: List[Dict[str, Any]] = []
        for index in sorted(function_calls):
            call = function_calls[index]
            if not call.get("call_id"):
                call["call_id"] = call.get("id") or f"call_{index}"
            finalized.append(call)
        return finalized

    def _response_function_call_output_item(self, tool_call: Any, output: str) -> Dict[str, Any]:
        return {
            "type": "function_call_output",
            "call_id": self._response_tool_call_id(tool_call),
            "output": output,
        }

    async def _collect_responses_tool_stream(
        self,
        input_items: List[Dict[str, Any]],
        instructions: Optional[str],
        temperature: float,
        tool_choice: Any,
    ) -> tuple[str, List[Dict[str, Any]]]:
        function_calls: Dict[int, Dict[str, Any]] = {}
        content_parts: List[str] = []

        async with self.client.responses.stream(
            model=self.model,
            input=cast(Any, input_items),
            instructions=self._responses_instructions(instructions),
            temperature=temperature,
            max_output_tokens=self.max_output_tokens,
            tools=cast(Any, [LOCAL_WEB_SEARCH_RESPONSE_TOOL]),
            tool_choice=tool_choice,
        ) as stream:
            async for event in stream:
                event_type = getattr(event, "type", None)
                if event_type == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        content_parts.append(str(delta))
                    continue

                if event_type == "response.output_item.added":
                    item = getattr(event, "item", None)
                    if self._get_attr_or_key(item, "type", None) == "function_call":
                        self._merge_response_function_call_item(
                            function_calls,
                            getattr(event, "output_index", None),
                            item,
                        )
                    continue

                if event_type == "response.function_call_arguments.delta":
                    self._merge_response_function_call_delta(
                        function_calls,
                        getattr(event, "output_index", None),
                        getattr(event, "delta", ""),
                    )
                    continue

                if event_type in {"response.function_call_arguments.done", "response.output_item.done"}:
                    item = getattr(event, "item", None)
                    if self._get_attr_or_key(item, "type", None) == "function_call":
                        self._merge_response_function_call_item(
                            function_calls,
                            getattr(event, "output_index", None),
                            item,
                        )
                    else:
                        arguments = getattr(event, "arguments", None)
                        if arguments is not None:
                            try:
                                index = int(getattr(event, "output_index", None))
                            except (TypeError, ValueError):
                                index = len(function_calls)
                            current = function_calls.setdefault(
                                index,
                                {
                                    "type": "function_call",
                                    "id": "",
                                    "call_id": "",
                                    "name": "web_search",
                                    "arguments": "",
                                },
                            )
                            current["arguments"] = str(arguments)

        return "".join(content_parts), self._finalize_response_function_calls(function_calls)

    async def _stream_responses_content(
        self,
        input_items: List[Dict[str, Any]],
        instructions: Optional[str],
        temperature: float,
    ) -> AsyncIterator[str]:
        async with self.client.responses.stream(
            model=self.model,
            input=cast(Any, input_items),
            instructions=self._responses_instructions(instructions),
            temperature=temperature,
            max_output_tokens=self.max_output_tokens,
        ) as stream:
            async for event in stream:
                if getattr(event, "type", None) == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield str(delta)

    async def _stream_responses_hosted_web_search(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str],
        temperature: float,
    ) -> AsyncIterator[str]:
        input_items = self._responses_input(messages)
        tool_choice: Any = (
            {"type": "web_search"}
            if self._should_force_local_web_search(messages)
            else "auto"
        )
        async with self.client.responses.stream(
            model=self.model,
            input=cast(Any, input_items),
            instructions=self._responses_instructions(system_prompt),
            temperature=temperature,
            max_output_tokens=self.max_output_tokens,
            tools=[{"type": "web_search"}],
            tool_choice=tool_choice,
            include=["web_search_call.action.sources"],
        ) as stream:
            async for event in stream:
                if getattr(event, "type", None) == "response.output_text.delta":
                    delta = getattr(event, "delta", "")
                    if delta:
                        yield str(delta)

    def _merge_stream_tool_call_delta(
        self,
        tool_calls: Dict[int, Dict[str, Any]],
        tool_call_delta: Any,
    ) -> None:
        raw_index = self._get_attr_or_key(tool_call_delta, "index", None)
        try:
            index = int(raw_index)
        except (TypeError, ValueError):
            index = len(tool_calls)

        current = tool_calls.setdefault(
            index,
            {
                "id": "",
                "type": "function",
                "function": {"name": "", "arguments": ""},
            },
        )

        tool_id = self._get_attr_or_key(tool_call_delta, "id", None)
        if tool_id:
            current["id"] = str(tool_id)

        tool_type = self._get_attr_or_key(tool_call_delta, "type", None)
        if tool_type:
            current["type"] = str(tool_type)

        function = self._get_attr_or_key(tool_call_delta, "function", None)
        if not function:
            return

        name = self._get_attr_or_key(function, "name", None)
        if name:
            current["function"]["name"] = str(name)

        arguments = self._get_attr_or_key(function, "arguments", None)
        if arguments:
            current["function"]["arguments"] += str(arguments)

    def _finalize_stream_tool_calls(self, tool_calls: Dict[int, Dict[str, Any]]) -> List[Dict[str, Any]]:
        finalized: List[Dict[str, Any]] = []
        for index in sorted(tool_calls):
            tool_call = tool_calls[index]
            if not tool_call.get("id"):
                tool_call["id"] = f"call_{index}"
            finalized.append(tool_call)
        return finalized

    async def _collect_chat_completion_tool_stream(
        self,
        conversation: List[Dict[str, Any]],
        temperature: float,
        tool_choice: Any,
    ) -> tuple[str, List[Dict[str, Any]]]:
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=cast(Any, conversation),
            temperature=temperature,
            max_tokens=self.max_output_tokens,
            tools=cast(Any, [LOCAL_WEB_SEARCH_TOOL]),
            tool_choice=tool_choice,
            stream=True,
        )

        content_parts: List[str] = []
        tool_call_deltas: Dict[int, Dict[str, Any]] = {}
        async for chunk in stream:
            choices = self._get_attr_or_key(chunk, "choices", []) or []
            if not choices:
                continue
            delta = self._get_attr_or_key(choices[0], "delta", {})
            content = self._get_attr_or_key(delta, "content", None)
            if content:
                content_parts.append(str(content))
            for tool_call_delta in self._get_attr_or_key(delta, "tool_calls", []) or []:
                self._merge_stream_tool_call_delta(tool_call_deltas, tool_call_delta)

        return "".join(content_parts), self._finalize_stream_tool_calls(tool_call_deltas)

    async def _stream_chat_completion_content(
        self,
        conversation: List[Dict[str, Any]],
        temperature: float,
    ) -> AsyncIterator[str]:
        stream = await self.client.chat.completions.create(
            model=self.model,
            messages=cast(Any, conversation),
            temperature=temperature,
            max_tokens=self.max_output_tokens,
            stream=True,
        )

        async for chunk in stream:
            choices = self._get_attr_or_key(chunk, "choices", []) or []
            if not choices:
                continue
            delta = self._get_attr_or_key(choices[0], "delta", {})
            content = self._get_attr_or_key(delta, "content", None)
            if content:
                yield str(content)
    
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
            max_tokens=self.max_output_tokens,
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
            max_tokens=self.max_output_tokens,
            stream=True
        )
        
        async for chunk in stream:
            choices = self._get_attr_or_key(chunk, "choices", []) or []
            if not choices:
                continue
            delta = self._get_attr_or_key(choices[0], "delta", {})
            content = self._get_attr_or_key(delta, "content", None)
            if content:
                yield str(content)

    async def chat_stream_with_web_search(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        """Stream a response with web search.

        Try hosted Responses web search first, then fall back to local
        search executed by Mnemox through either Responses function tools
        or Chat Completions function tools.
        """
        try:
            async for chunk in self._stream_responses_hosted_web_search(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature,
            ):
                yield chunk
            return
        except Exception as exc:
            if not (
                self._looks_like_responses_unsupported_error(exc)
                or self._looks_like_tool_unsupported_error(exc)
            ):
                raise

        try:
            async for chunk in self._chat_stream_with_responses_local_web_search(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature,
            ):
                yield chunk
            return
        except Exception as exc:
            if not (
                self._looks_like_responses_unsupported_error(exc)
                or self._looks_like_tool_unsupported_error(exc)
            ):
                raise

        try:
            async for chunk in self._chat_stream_with_local_web_search(
                messages=messages,
                system_prompt=system_prompt,
                temperature=temperature,
            ):
                yield chunk
            return
        except Exception as exc:
            if not self._looks_like_tool_unsupported_error(exc):
                raise
            raise ValueError("当前供应商不支持工具调用联网搜索。") from exc

    async def _chat_stream_with_responses_local_web_search(
        self,
        messages: List[Dict[str, Any]],
        system_prompt: Optional[str] = None,
        temperature: float = 0.7,
    ) -> AsyncIterator[str]:
        effective_system_prompt = (system_prompt or "") + LOCAL_WEB_SEARCH_INSTRUCTION
        input_items = self._responses_input(messages)
        force_search = self._should_force_local_web_search(messages)
        tool_choice: Any = (
            {"type": "function", "name": "web_search"}
            if force_search
            else "auto"
        )
        content, tool_calls = await self._collect_responses_tool_stream(
            input_items=input_items,
            instructions=effective_system_prompt,
            temperature=temperature,
            tool_choice=tool_choice,
        )

        if not tool_calls:
            if force_search:
                raise ValueError("当前供应商不支持工具调用联网搜索。")
            if content:
                yield content
            return

        followup_input = [*input_items]
        assistant_output: List[Dict[str, Any]] = []
        if content:
            assistant_output.append(
                {
                    "type": "message",
                    "role": "assistant",
                    "content": [{"type": "output_text", "text": content}],
                }
            )
        assistant_output.extend(tool_calls)
        followup_input.extend(assistant_output)

        for tool_call in tool_calls:
            name = self._response_tool_call_name(tool_call)
            if name != "web_search":
                result = json.dumps({"error": f"未知工具：{name}"}, ensure_ascii=False)
            else:
                result = await self._run_local_web_search_tool(
                    self._response_tool_call_arguments(tool_call)
                )
            followup_input.append(self._response_function_call_output_item(tool_call, result))

        async for chunk in self._stream_responses_content(
            input_items=followup_input,
            instructions=effective_system_prompt,
            temperature=temperature,
        ):
            yield chunk

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
        force_search = self._should_force_local_web_search(messages)
        for round_index in range(max_tool_rounds):
            try:
                tool_choice: Any = (
                    {"type": "function", "function": {"name": "web_search"}}
                    if force_search and round_index == 0
                    else "auto"
                )
                content, tool_calls = await self._collect_chat_completion_tool_stream(
                    conversation,
                    temperature,
                    tool_choice,
                )
            except Exception as exc:
                if self._looks_like_tool_unsupported_error(exc):
                    raise ValueError("当前供应商不支持工具调用联网搜索。") from exc
                raise

            if not tool_calls:
                if force_search and round_index == 0:
                    raise ValueError("当前供应商不支持工具调用联网搜索。")
                if content:
                    yield str(content)
                return

            conversation.append(
                {
                    "role": "assistant",
                    "content": content or None,
                    "tool_calls": tool_calls,
                }
            )
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

            async for chunk in self._stream_chat_completion_content(conversation, temperature):
                yield chunk
            return

        conversation.append(
            {
                "role": "user",
                "content": "请基于已经获得的搜索结果给出最终回答，不要继续调用工具。",
            }
        )
        async for chunk in self._stream_chat_completion_content(conversation, temperature):
            yield chunk
