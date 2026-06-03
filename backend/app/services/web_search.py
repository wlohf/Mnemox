"""Small provider-agnostic web search helper used when the LLM provider has no hosted search tool."""
from __future__ import annotations

from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Iterable
from urllib.parse import parse_qs, unquote, urlparse

import httpx


@dataclass
class WebSearchResult:
    title: str
    url: str
    snippet: str = ""


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
            self.results.append(WebSearchResult(title=title, url=url, snippet=snippet))
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


async def search_web(query: str, *, limit: int = 5, timeout: float = 8.0) -> list[WebSearchResult]:
    """Search the public web without relying on a model-provider hosted search tool."""
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
        response = await client.get("https://html.duckduckgo.com/html/", params={"q": clean_query})
        response.raise_for_status()
    return parse_duckduckgo_html(response.text, limit=limit)
