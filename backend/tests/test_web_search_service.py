import unittest
from unittest.mock import AsyncMock, patch

import httpx

from app.services.web_search import (
    SearchProviderSettings,
    parse_bing_html,
    parse_bing_rss,
    parse_duckduckgo_html,
    search_web,
)


def test_parse_duckduckgo_html_extracts_result_links():
    html = """
    <html><body>
      <div class="result">
        <a class="result__a" href="/l/?kh=-1&amp;uddg=https%3A%2F%2Fexample.com%2Fpost">
          Example Result
        </a>
        <a class="result__snippet">A concise summary of the page.</a>
      </div>
    </body></html>
    """

    results = parse_duckduckgo_html(html)

    assert len(results) == 1
    assert results[0].title == "Example Result"
    assert results[0].url == "https://example.com/post"
    assert results[0].snippet == "A concise summary of the page."


def test_parse_bing_html_extracts_result_links():
    html = """
    <html><body>
      <ol id="b_results">
        <li class="b_algo">
          <h2><a href="https://example.com/bing">Bing Result</a></h2>
          <div class="b_caption"><p>A concise Bing summary.</p></div>
        </li>
      </ol>
    </body></html>
    """

    results = parse_bing_html(html)

    assert len(results) == 1
    assert results[0].title == "Bing Result"
    assert results[0].url == "https://example.com/bing"
    assert results[0].snippet == "A concise Bing summary."


def test_parse_bing_rss_extracts_result_links():
    xml = """
    <rss version="2.0">
      <channel>
        <item>
          <title>Bing RSS Result</title>
          <link>https://example.com/rss</link>
          <description>A concise RSS summary.</description>
        </item>
      </channel>
    </rss>
    """

    results = parse_bing_rss(xml)

    assert len(results) == 1
    assert results[0].title == "Bing RSS Result"
    assert results[0].url == "https://example.com/rss"
    assert results[0].snippet == "A concise RSS summary."


class WebSearchProviderTests(unittest.IsolatedAsyncioTestCase):
    async def test_search_web_uses_tavily_first_when_enabled(self):
        settings = SearchProviderSettings(
            enabled=True,
            provider="tavily",
            tavily_api_key="tvly-test",
            tavily_max_results=8,
            tavily_search_depth="advanced",
            tavily_chunks_per_source=3,
            fallback_enabled=True,
        )

        async def fake_tavily(*args, **kwargs):
            return [
                {
                    "title": "Tavily Result",
                    "url": "https://example.com/tavily",
                    "snippet": "Structured Tavily snippet",
                    "source_provider": "tavily",
                }
            ]

        with patch("app.services.web_search._search_tavily", AsyncMock(side_effect=fake_tavily)) as tavily_mock:
            results = await search_web("mnemox latest", settings=settings, limit=5)

        self.assertEqual(results[0].title, "Tavily Result")
        self.assertEqual(results[0].source_provider, "tavily")
        tavily_mock.assert_awaited_once()

    async def test_search_web_falls_back_to_local_search_when_tavily_fails(self):
        settings = SearchProviderSettings(
            enabled=True,
            provider="tavily",
            tavily_api_key="tvly-test",
            fallback_enabled=True,
        )

        duckduckgo_response = httpx.Response(
            200,
            text="""
            <html><body>
              <a class="result__a" href="/l/?uddg=https%3A%2F%2Fexample.com%2Ffallback">Fallback Result</a>
              <a class="result__snippet">Local fallback snippet.</a>
            </body></html>
            """,
            request=httpx.Request("GET", "https://html.duckduckgo.com/html/"),
        )

        class FakeClient:
            async def __aenter__(self):
                return self

            async def __aexit__(self, exc_type, exc, tb):
                return False

            async def get(self, *_args, **_kwargs):
                return duckduckgo_response

        with (
            patch("app.services.web_search._search_tavily", AsyncMock(side_effect=httpx.HTTPError("boom"))),
            patch("app.services.web_search.httpx.AsyncClient", return_value=FakeClient()),
        ):
            results = await search_web("mnemox latest", settings=settings, limit=5)

        self.assertEqual(results[0].title, "Fallback Result")
        self.assertEqual(results[0].source_provider, "duckduckgo")
