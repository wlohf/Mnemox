"""Helpers for loading and normalizing web search settings."""
from __future__ import annotations

from typing import Any

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search_settings import AISearchSettings
from app.utils.secret_crypto import decrypt_secret, encrypt_secret


SEARCH_MODES = {"auto", "tavily", "provider_hosted", "grok_summary", "local_fallback", "app_search"}
SEARCH_PROVIDERS = {"auto", "tavily", "local_fallback"}


def _clamp_int(value: Any, default: int, low: int, high: int) -> int:
    try:
        number = int(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def _clamp_float(value: Any, default: float, low: float, high: float) -> float:
    try:
        number = float(value)
    except (TypeError, ValueError):
        number = default
    return max(low, min(high, number))


def default_search_settings() -> dict[str, Any]:
    return {
        "enabled": False,
        "default_mode": "auto",
        "provider": "auto",
        "tavily_api_key": "",
        "tavily_api_key_masked": "",
        "tavily_search_depth": "advanced",
        "tavily_max_results": 8,
        "tavily_chunks_per_source": 3,
        "tavily_include_answer": False,
        "tavily_include_raw_content": False,
        "timeout_seconds": 12.0,
        "fallback_enabled": True,
        "updated_at": None,
    }


def mask_search_key(key: str) -> str:
    if not key:
        return ""
    if len(key) <= 8:
        return "****"
    return key[:3] + "****" + key[-4:]


def normalize_search_settings(data: dict[str, Any]) -> dict[str, Any]:
    base = default_search_settings()
    merged = {**base, **(data or {})}
    mode = str(merged.get("default_mode") or "auto").strip()
    provider = str(merged.get("provider") or "auto").strip()
    if mode not in SEARCH_MODES:
        mode = "auto"
    if provider not in SEARCH_PROVIDERS:
        provider = "auto"
    depth = str(merged.get("tavily_search_depth") or "advanced").strip().lower()
    if depth not in {"basic", "advanced"}:
        depth = "advanced"
    key = str(merged.get("tavily_api_key") or "").strip()
    return {
        **base,
        **merged,
        "enabled": bool(merged.get("enabled")),
        "default_mode": mode,
        "provider": provider,
        "tavily_api_key": key,
        "tavily_api_key_masked": mask_search_key(key),
        "tavily_search_depth": depth,
        "tavily_max_results": _clamp_int(merged.get("tavily_max_results"), 8, 1, 10),
        "tavily_chunks_per_source": _clamp_int(merged.get("tavily_chunks_per_source"), 3, 1, 5),
        "tavily_include_answer": bool(merged.get("tavily_include_answer")),
        "tavily_include_raw_content": bool(merged.get("tavily_include_raw_content")),
        "timeout_seconds": _clamp_float(merged.get("timeout_seconds"), 12.0, 2.0, 30.0),
        "fallback_enabled": bool(merged.get("fallback_enabled", True)),
    }


def search_settings_to_dict(row: AISearchSettings | None, *, include_secret: bool = True) -> dict[str, Any]:
    if not row:
        return default_search_settings()
    key = decrypt_secret(row.tavily_api_key) if include_secret else ""
    return normalize_search_settings(
        {
            "enabled": row.enabled,
            "default_mode": row.default_mode,
            "provider": row.provider,
            "tavily_api_key": key,
            "tavily_search_depth": row.tavily_search_depth,
            "tavily_max_results": row.tavily_max_results,
            "tavily_chunks_per_source": row.tavily_chunks_per_source,
            "tavily_include_answer": row.tavily_include_answer,
            "tavily_include_raw_content": row.tavily_include_raw_content,
            "timeout_seconds": row.timeout_seconds,
            "fallback_enabled": row.fallback_enabled,
            "updated_at": row.updated_at.isoformat() if row.updated_at else None,
        }
    )


async def get_or_create_search_settings(db: AsyncSession, user_id: int) -> AISearchSettings:
    result = await db.execute(select(AISearchSettings).where(AISearchSettings.user_id == user_id))
    row = result.scalar_one_or_none()
    if row:
        return row

    defaults = default_search_settings()
    row = AISearchSettings(
        user_id=user_id,
        enabled=defaults["enabled"],
        default_mode=defaults["default_mode"],
        provider=defaults["provider"],
        tavily_api_key="",
        tavily_search_depth=defaults["tavily_search_depth"],
        tavily_max_results=defaults["tavily_max_results"],
        tavily_chunks_per_source=defaults["tavily_chunks_per_source"],
        tavily_include_answer=defaults["tavily_include_answer"],
        tavily_include_raw_content=defaults["tavily_include_raw_content"],
        timeout_seconds=defaults["timeout_seconds"],
        fallback_enabled=defaults["fallback_enabled"],
    )
    db.add(row)
    await db.flush()
    await db.refresh(row)
    return row


async def get_search_settings_dict(db: AsyncSession, user_id: int) -> dict[str, Any]:
    row = await get_or_create_search_settings(db, user_id)
    return search_settings_to_dict(row)


async def update_search_settings(db: AsyncSession, user_id: int, patch: dict[str, Any]) -> dict[str, Any]:
    row = await get_or_create_search_settings(db, user_id)
    normalized_patch = normalize_search_settings({**search_settings_to_dict(row), **patch})

    row.enabled = normalized_patch["enabled"]
    row.default_mode = normalized_patch["default_mode"]
    row.provider = normalized_patch["provider"]
    if "tavily_api_key" in patch:
        row.tavily_api_key = encrypt_secret(normalized_patch["tavily_api_key"])
    row.tavily_search_depth = normalized_patch["tavily_search_depth"]
    row.tavily_max_results = normalized_patch["tavily_max_results"]
    row.tavily_chunks_per_source = normalized_patch["tavily_chunks_per_source"]
    row.tavily_include_answer = normalized_patch["tavily_include_answer"]
    row.tavily_include_raw_content = normalized_patch["tavily_include_raw_content"]
    row.timeout_seconds = normalized_patch["timeout_seconds"]
    row.fallback_enabled = normalized_patch["fallback_enabled"]
    await db.flush()
    await db.refresh(row)
    return search_settings_to_dict(row)
