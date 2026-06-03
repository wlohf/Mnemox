from app.services.web_search import parse_duckduckgo_html


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
