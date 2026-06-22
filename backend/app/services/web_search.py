"""Small provider-agnostic web search helper used when the LLM provider has no hosted search tool."""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse
import xml.etree.ElementTree as ET

import httpx


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str = ""
    source_provider: str = "local"
    score: float | None = None
    published_date: str | None = None


@dataclass
class SearchProviderSettings:
    enabled: bool = False
    provider: str = "auto"
    tavily_api_key: str = ""
    tavily_search_depth: str = "advanced"
    tavily_max_results: int = 8
    tavily_chunks_per_source: int = 3
    tavily_include_answer: bool = False
    tavily_include_raw_content: bool = False
    timeout_seconds: float = 12.0
    fallback_enabled: bool = True


class _DuckDuckGoHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[WebSearchResult] = []
        self._current: dict[str, str] | None = None
        self._capture: str | None = None
        self._capture_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = set(attr.get("class", "").split())

        if tag == "a" and "result__a" in classes:
            self._finish_current()
            self._current = {"title": "", "url": _clean_result_url(attr.get("href", "")), "snippet": ""}
            self._capture = "title"
            self._capture_depth = 1
            return

        if self._current is not None and "result__snippet" in classes:
            self._capture = "snippet"
            self._capture_depth = 1
            return

        if self._capture:
            self._capture_depth += 1

    def handle_endtag(self, _tag: str) -> None:
        if not self._capture:
            return
        self._capture_depth -= 1
        if self._capture_depth <= 0:
            self._capture = None
            self._capture_depth = 0

    def handle_data(self, data: str) -> None:
        if self._current is None or not self._capture:
            return
        text = " ".join(data.split())
        if not text:
            return
        previous = self._current.get(self._capture, "")
        self._current[self._capture] = f"{previous} {text}".strip()

    def close(self) -> None:
        super().close()
        self._finish_current()

    def _finish_current(self) -> None:
        if not self._current:
            return
        title = self._current.get("title", "").strip()
        url = self._current.get("url", "").strip()
        snippet = self._current.get("snippet", "").strip()
        if title and url.startswith(("http://", "https://")):
            self.results.append(WebSearchResult(title=title, url=url, snippet=snippet, source_provider="duckduckgo"))
        self._current = None
        self._capture = None
        self._capture_depth = 0


def _clean_result_url(raw_url: str) -> str:
    if raw_url.startswith("//"):
        raw_url = f"https:{raw_url}"
    parsed = urlparse(raw_url)
    query = parse_qs(parsed.query)
    if "uddg" in query and query["uddg"]:
        return unquote(query["uddg"][0])
    return raw_url


def parse_duckduckgo_html(html: str, limit: int = 5) -> list[WebSearchResult]:
    parser = _DuckDuckGoHTMLParser()
    parser.feed(html)
    parser.close()
    return _dedupe_results(parser.results)[:limit]


class _BingHTMLParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.results: list[WebSearchResult] = []
        self._current: dict[str, str] | None = None
        self._li_depth = 0
        self._capture: str | None = None
        self._capture_depth = 0

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attr = {key: value or "" for key, value in attrs}
        classes = set(attr.get("class", "").split())

        if tag == "li" and "b_algo" in classes:
            self._finish_current()
            self._current = {"title": "", "url": "", "snippet": ""}
            self._li_depth = 1
            return

        if self._current is None:
            return

        if tag == "li":
            self._li_depth += 1

        if tag == "a" and not self._current.get("url"):
            href = attr.get("href", "").strip()
            if href.startswith(("http://", "https://")):
                self._current["url"] = _clean_result_url(href)
                self._capture = "title"
                self._capture_depth = 1
                return

        if tag == "p":
            self._capture = "snippet"
            self._capture_depth = 1
            return

        if self._capture:
            self._capture_depth += 1

    def handle_endtag(self, tag: str) -> None:
        if self._current is not None and tag == "li":
            self._li_depth -= 1
            if self._li_depth <= 0:
                self._finish_current()
                return

        if not self._capture:
            return
        self._capture_depth -= 1
        if self._capture_depth <= 0:
            self._capture = None
            self._capture_depth = 0

    def handle_data(self, data: str) -> None:
        if self._current is None or not self._capture:
            return
        text = " ".join(data.split())
        if not text:
            return
        previous = self._current.get(self._capture, "")
        self._current[self._capture] = f"{previous} {text}".strip()

    def close(self) -> None:
        super().close()
        self._finish_current()

    def _finish_current(self) -> None:
        if not self._current:
            return
        title = self._current.get("title", "").strip()
        url = self._current.get("url", "").strip()
        snippet = self._current.get("snippet", "").strip()
        if title and url.startswith(("http://", "https://")):
            self.results.append(WebSearchResult(title=title, url=url, snippet=snippet, source_provider="bing"))
        self._current = None
        self._capture = None
        self._capture_depth = 0
        self._li_depth = 0


def parse_bing_html(html: str, limit: int = 5) -> list[WebSearchResult]:
    parser = _BingHTMLParser()
    parser.feed(html)
    parser.close()
    return _dedupe_results(parser.results)[:limit]


def parse_bing_rss(xml_text: str, limit: int = 5) -> list[WebSearchResult]:
    try:
        root = ET.fromstring(xml_text)
    except ET.ParseError:
        return []

    results: list[WebSearchResult] = []
    for item in root.findall("./channel/item"):
        title = " ".join((item.findtext("title", default="") or "").split())
        url = (item.findtext("link", default="") or "").strip()
        snippet = " ".join((item.findtext("description", default="") or "").split())
        if title and url.startswith(("http://", "https://")):
            results.append(WebSearchResult(title=title, url=_clean_result_url(url), snippet=snippet, source_provider="bing"))
    return _dedupe_results(results)[:limit]


def _dedupe_results(results: Iterable[WebSearchResult]) -> list[WebSearchResult]:
    seen: set[str] = set()
    unique: list[WebSearchResult] = []
    for result in results:
        key = result.url.rstrip("/")
        if key in seen:
            continue
        seen.add(key)
        unique.append(result)
    return unique


def _coerce_results(results: Iterable[WebSearchResult | dict]) -> list[WebSearchResult]:
    coerced: list[WebSearchResult] = []
    for item in results:
        if isinstance(item, WebSearchResult):
            coerced.append(item)
            continue
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        coerced.append(
            WebSearchResult(
                title=str(item.get("title") or url).strip(),
                url=url,
                snippet=str(item.get("snippet") or item.get("content") or "").strip(),
                source_provider=str(item.get("source_provider") or "local").strip() or "local",
            )
        )
    return coerced


async def _search_tavily(query: str, *, settings: SearchProviderSettings, limit: int) -> list[WebSearchResult]:
    clean_query = " ".join((query or "").split())
    if not clean_query or not settings.tavily_api_key:
        return []

    max_results = max(1, min(int(settings.tavily_max_results or limit or 8), 10))
    payload = {
        "query": clean_query,
        "search_depth": settings.tavily_search_depth if settings.tavily_search_depth in {"basic", "advanced"} else "advanced",
        "max_results": max_results,
        "chunks_per_source": max(1, min(int(settings.tavily_chunks_per_source or 3), 5)),
        "include_answer": bool(settings.tavily_include_answer),
        "include_raw_content": bool(settings.tavily_include_raw_content),
    }
    headers = {
        "Authorization": f"Bearer {settings.tavily_api_key}",
        "Content-Type": "application/json",
    }
    async with httpx.AsyncClient(timeout=settings.timeout_seconds or 12.0, follow_redirects=True) as client:
        response = await client.post("https://api.tavily.com/search", json=payload, headers=headers)
        response.raise_for_status()
        data = response.json()

    results: list[WebSearchResult] = []
    for item in data.get("results") or []:
        if not isinstance(item, dict):
            continue
        url = str(item.get("url") or "").strip()
        if not url.startswith(("http://", "https://")):
            continue
        score = item.get("score")
        try:
            score_value = float(score) if score is not None else None
        except (TypeError, ValueError):
            score_value = None
        results.append(
            WebSearchResult(
                title=str(item.get("title") or url).strip(),
                url=url,
                snippet=str(item.get("content") or item.get("snippet") or "").strip(),
                source_provider="tavily",
                score=score_value,
                published_date=str(item.get("published_date") or "").strip() or None,
            )
        )
    return _dedupe_results(results)[:limit]


async def _search_local_public_web(query: str, *, limit: int = 5, timeout: float = 8.0) -> list[WebSearchResult]:
    """Search DuckDuckGo, then Bing RSS/HTML, without requiring a key."""
    clean_query = " ".join((query or "").split())
    if not clean_query:
        return []

    headers = {
        "User-Agent": (
            "Mozilla/5.0 (Windows NT 10.0; Win64; x64) "
            "AppleWebKit/537.36 (KHTML, like Gecko) Chrome/125 Safari/537.36"
        )
    }
    async with httpx.AsyncClient(timeout=timeout, follow_redirects=True, headers=headers) as client:
        try:
            response = await client.get("https://html.duckduckgo.com/html/", params={"q": clean_query})
            response.raise_for_status()
            results = parse_duckduckgo_html(response.text, limit=limit)
            if results:
                return results
        except httpx.HTTPError:
            pass

        response = await client.get("https://www.bing.com/search", params={"q": clean_query, "format": "rss"})
        response.raise_for_status()
        results = parse_bing_rss(response.text, limit=limit)
        if results:
            return results

        response = await client.get("https://www.bing.com/search", params={"q": clean_query})
        response.raise_for_status()
        return parse_bing_html(response.text, limit=limit)


async def search_web(
    query: str,
    *,
    limit: int = 5,
    timeout: float = 8.0,
    settings: SearchProviderSettings | dict | None = None,
) -> list[WebSearchResult]:
    """Search using Tavily when configured, with DuckDuckGo/Bing as final fallback."""
    if isinstance(settings, dict):
        allowed = SearchProviderSettings.__dataclass_fields__
        settings = SearchProviderSettings(**{key: value for key, value in settings.items() if key in allowed})

    effective = settings or SearchProviderSettings(timeout_seconds=timeout, fallback_enabled=True)
    provider = (effective.provider or "auto").strip()
    should_try_tavily = (
        bool(effective.enabled)
        and bool(effective.tavily_api_key)
        and provider in {"auto", "tavily"}
    )

    if should_try_tavily:
        try:
            results = _coerce_results(await _search_tavily(query, settings=effective, limit=limit))
            if results:
                return results
            if provider == "tavily" and not effective.fallback_enabled:
                return []
        except Exception:
            if provider == "tavily" and not effective.fallback_enabled:
                raise

    if effective.fallback_enabled or provider in {"auto", "local_fallback"} or not should_try_tavily:
        return await _search_local_public_web(
            query,
            limit=limit,
            timeout=effective.timeout_seconds or timeout,
        )

    return []
