"""Search cache helpers for app-layer web search."""
from __future__ import annotations

from dataclasses import asdict, fields
from datetime import datetime, timedelta
from hashlib import sha256
from typing import Awaitable, Callable, Iterable
import json

from sqlalchemy import select
from sqlalchemy.ext.asyncio import AsyncSession

from app.models.search_cache import WebSearchCache
from app.services.search_quality import enhance_search_results
from app.services.web_search import SearchProviderSettings, WebSearchResult


SearchFunc = Callable[..., Awaitable[list[WebSearchResult]]]

REALTIME_QUERY_MARKERS = (
    "今天",
    "昨日",
    "昨天",
    "明天",
    "现在",
    "当前",
    "最近",
    "近期",
    "最新",
    "新闻",
    "价格",
    "股价",
    "汇率",
    "天气",
    "版本",
    "发布",
    "更新",
    "today",
    "yesterday",
    "tomorrow",
    "current",
    "recent",
    "latest",
    "news",
    "price",
    "stock",
    "weather",
    "release",
    "version",
)


def normalize_search_query(query: str) -> str:
    return " ".join((query or "").strip().lower().split())


def search_cache_ttl(query: str) -> timedelta:
    normalized = normalize_search_query(query)
    if any(marker in normalized for marker in REALTIME_QUERY_MARKERS):
        return timedelta(minutes=15)
    return timedelta(hours=6)


def _settings_quality_key(settings: SearchProviderSettings | dict | None, limit: int, mode: str) -> tuple[str, str, str]:
    if isinstance(settings, dict):
        allowed = SearchProviderSettings.__dataclass_fields__
        settings = SearchProviderSettings(**{key: value for key, value in settings.items() if key in allowed})
    provider = getattr(settings, "provider", None) or "auto"
    depth = getattr(settings, "tavily_search_depth", None) or "advanced"
    max_results = getattr(settings, "tavily_max_results", None) or limit
    chunks = getattr(settings, "tavily_chunks_per_source", None) or 3
    include_answer = int(bool(getattr(settings, "tavily_include_answer", False)))
    include_raw = int(bool(getattr(settings, "tavily_include_raw_content", False)))
    fallback = int(bool(getattr(settings, "fallback_enabled", True)))
    quality_key = (
        f"limit={limit}|mode={mode}|provider={provider}|depth={depth}|"
        f"max={max_results}|chunks={chunks}|answer={include_answer}|raw={include_raw}|fallback={fallback}"
    )
    return mode, provider, quality_key


def build_search_cache_hash(query: str, *, mode: str, provider: str, quality_key: str) -> str:
    normalized = normalize_search_query(query)
    return sha256(f"{normalized}\n{mode}\n{provider}\n{quality_key}".encode("utf-8")).hexdigest()


def _result_to_dict(result: WebSearchResult) -> dict:
    data = asdict(result)
    return data


def _result_from_dict(data: dict) -> WebSearchResult | None:
    allowed = {field.name for field in fields(WebSearchResult)}
    try:
        return WebSearchResult(**{key: value for key, value in data.items() if key in allowed})
    except Exception:
        return None


def _serialize_results(results: Iterable[WebSearchResult]) -> str:
    return json.dumps([_result_to_dict(item) for item in results], ensure_ascii=False)


def _deserialize_results(raw: str) -> list[WebSearchResult]:
    try:
        data = json.loads(raw or "[]")
    except Exception:
        return []
    if not isinstance(data, list):
        return []
    results: list[WebSearchResult] = []
    for item in data:
        if not isinstance(item, dict):
            continue
        result = _result_from_dict(item)
        if result:
            results.append(result)
    return enhance_search_results(results)


async def get_cached_search_results(
    db: AsyncSession,
    user_id: int,
    query: str,
    *,
    mode: str,
    provider: str,
    quality_key: str,
) -> list[WebSearchResult] | None:
    try:
        query_hash = build_search_cache_hash(query, mode=mode, provider=provider, quality_key=quality_key)
        result = await db.execute(
            select(WebSearchCache)
            .where(
                WebSearchCache.user_id == user_id,
                WebSearchCache.query_hash == query_hash,
                WebSearchCache.expires_at > datetime.now(),
            )
            .order_by(WebSearchCache.created_at.desc(), WebSearchCache.id.desc())
            .limit(1)
        )
        row = result.scalar_one_or_none()
        if not isinstance(row, WebSearchCache):
            return None
        return _deserialize_results(row.results_json)
    except Exception:
        return None


async def store_search_results(
    db: AsyncSession,
    user_id: int,
    query: str,
    results: list[WebSearchResult],
    *,
    mode: str,
    provider: str,
    quality_key: str,
) -> None:
    if not results:
        return
    try:
        now = datetime.now()
        query_hash = build_search_cache_hash(query, mode=mode, provider=provider, quality_key=quality_key)
        normalized_query = normalize_search_query(query)
        existing = await db.execute(
            select(WebSearchCache)
            .where(WebSearchCache.user_id == user_id, WebSearchCache.query_hash == query_hash)
            .order_by(WebSearchCache.id.desc())
            .limit(1)
        )
        row = existing.scalar_one_or_none()
        if not isinstance(row, WebSearchCache):
            row = WebSearchCache(user_id=user_id, query_hash=query_hash)
            db.add(row)

        row.normalized_query = normalized_query
        row.mode = mode
        row.provider = provider
        row.quality_key = quality_key
        row.results_json = _serialize_results(results)
        row.source_count = len(results)
        row.created_at = now
        row.expires_at = now + search_cache_ttl(query)
        await db.flush()
    except Exception:
        return


async def search_web_with_cache(
    query: str,
    *,
    db: AsyncSession | None,
    user_id: int | None,
    limit: int = 5,
    settings: SearchProviderSettings | dict | None = None,
    mode: str = "auto",
    timeout: float = 8.0,
    search_func: SearchFunc | None = None,
) -> list[WebSearchResult]:
    if search_func is None:
        from app.services.web_search import search_web as search_func

    cache_mode, cache_provider, quality_key = _settings_quality_key(settings, limit, mode)
    if db is not None and user_id is not None:
        cached = await get_cached_search_results(
            db,
            int(user_id),
            query,
            mode=cache_mode,
            provider=cache_provider,
            quality_key=quality_key,
        )
        if cached is not None:
            return cached[:limit]

    results = await search_func(query, limit=limit, timeout=timeout, settings=settings)
    results = enhance_search_results(results, limit=limit)
    if db is not None and user_id is not None and results:
        await store_search_results(
            db,
            int(user_id),
            query,
            results,
            mode=cache_mode,
            provider=cache_provider,
            quality_key=quality_key,
        )
    return results
