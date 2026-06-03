"""User-facing AI provider error messages."""
from __future__ import annotations

import json
from typing import Any

import httpx


def _status_code(exc: Exception) -> int | None:
    status = getattr(exc, "status_code", None)
    if isinstance(status, int):
        return status

    response = getattr(exc, "response", None)
    status = getattr(response, "status_code", None)
    if isinstance(status, int):
        return status
    return None


def _extract_error_message(exc: Exception) -> str:
    response = getattr(exc, "response", None)
    if response is not None:
        try:
            data: Any = response.json()
            detail = data.get("error") if isinstance(data, dict) else None
            if isinstance(detail, dict):
                message = detail.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
            message = data.get("message") if isinstance(data, dict) else None
            if isinstance(message, str) and message.strip():
                return message.strip()
        except Exception:
            text = getattr(response, "text", "") or ""
            if text.strip():
                return text.strip()

    text = str(exc).strip()
    if not text:
        return ""

    try:
        data = json.loads(text)
        if isinstance(data, dict):
            detail = data.get("error") or data.get("detail") or data.get("message")
            if isinstance(detail, dict):
                message = detail.get("message")
                if isinstance(message, str) and message.strip():
                    return message.strip()
            if isinstance(detail, str) and detail.strip():
                return detail.strip()
    except Exception:
        pass

    return text


def format_ai_provider_error(exc: Exception) -> str:
    """Translate low-level provider/SDK errors into concise UI copy."""
    text = _extract_error_message(exc)
    lower = text.lower()
    status = _status_code(exc)

    if isinstance(exc, (httpx.ConnectError, httpx.ConnectTimeout, httpx.ReadTimeout, httpx.PoolTimeout)):
        return "无法连接到 AI 服务。请检查 Base URL 是否正确，或稍后重试。"

    if status in (401, 403) or "invalid api key" in lower or "incorrect api key" in lower:
        return "API Key 不正确或没有权限。请检查当前供应商的 API Key。"

    if status == 404 or "model_not_found" in lower or "model not found" in lower:
        return "模型不存在或当前账号不能使用。请检查模型名称。"

    if status == 429 or "rate limit" in lower or "quota" in lower:
        return "AI 服务限流或额度不足。请稍后重试，或检查账号余额和配额。"

    if status in (500, 502, 503, 504):
        return "AI 服务暂时不可用。请稍后重试。"

    if (
        "has no attribute 'choices'" in lower
        or "has no attribute \"choices\"" in lower
        or "choices" in lower and "attribute" in lower
    ):
        return "供应商返回的数据格式不对。请检查 Base URL 是否是 OpenAI 兼容的 /v1 地址，模型是否支持聊天接口。"

    if "not valid json" in lower or "expecting value" in lower or "<html" in lower:
        return "供应商返回的不是有效 JSON。请检查 Base URL 是否填错，或中转站是否返回了网页错误。"

    if "api key 未配置" in lower:
        return text

    if text:
        return text
    return "AI 服务请求失败。请检查供应商配置后重试。"
