from app.services.web_search import parse_bing_html, parse_bing_rss, parse_duckduckgo_html


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
