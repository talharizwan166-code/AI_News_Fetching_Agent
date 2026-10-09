from unittest.mock import patch, MagicMock
from src.fetcher import fetch_feed, fetch_all_feeds, Article


def _mock_feed(entries):
    feed = MagicMock()
    feed.bozo = False
    feed.entries = entries
    return feed


def _mock_response(content_bytes: bytes, status_code: int = 200):
    resp = MagicMock()
    resp.content = content_bytes
    resp.status_code = status_code
    resp.raise_for_status = MagicMock()
    if status_code >= 400:
        import requests
        resp.raise_for_status.side_effect = requests.HTTPError(f"{status_code} Error")
    return resp


def test_fetch_feed_parses_entries():
    entries = [
        {"title": "AI Breakthrough", "link": "https://example.com/1", "summary": "Great news"},
        {"title": "New Model", "link": "https://example.com/2", "summary": "Impressive"},
    ]
    mock_feed = _mock_feed(entries)
    with patch("src.fetcher.feedparser.parse", return_value=mock_feed) as mock_parse:
        with patch("src.fetcher.requests.get", return_value=_mock_response(b"fake rss content")):
            articles = fetch_feed("TestSource", "https://fake.rss")
    assert len(articles) == 2
    assert articles[0].title == "AI Breakthrough"
    assert articles[0].source == "TestSource"
    mock_parse.assert_called_once()


def test_fetch_feed_skips_entries_without_link():
    entries = [
        {"title": "No Link Article"},
        {"title": "Has Link", "link": "https://example.com/1"},
    ]
    mock_feed = _mock_feed(entries)
    with patch("src.fetcher.feedparser.parse", return_value=mock_feed):
        with patch("src.fetcher.requests.get", return_value=_mock_response(b"fake rss content")):
            articles = fetch_feed("Src", "https://fake.rss")
    assert len(articles) == 1
    assert articles[0].title == "Has Link"


def test_fetch_feed_handles_exception():
    with patch("src.fetcher.requests.get", side_effect=Exception("Network error")):
        articles = fetch_feed("Src", "https://fake.rss")
    assert articles == []


def test_fetch_feed_handles_timeout():
    import requests
    with patch("src.fetcher.requests.get", side_effect=requests.Timeout("Timeout")):
        articles = fetch_feed("Src", "https://fake.rss")
    assert articles == []


def test_fetch_feed_handles_http_error():
    import requests
    with patch("src.fetcher.requests.get", side_effect=requests.HTTPError("404 Not Found")):
        articles = fetch_feed("Src", "https://fake.rss")
    assert articles == []


def test_fetch_feed_handles_bozo_with_no_entries():
    feed = MagicMock()
    feed.bozo = True
    feed.entries = []
    feed.bozo_exception = "Bad XML"
    with patch("src.fetcher.feedparser.parse", return_value=feed):
        with patch("src.fetcher.requests.get", return_value=_mock_response(b"bad xml")):
            articles = fetch_feed("Src", "https://fake.rss")
    assert articles == []


def test_fetch_all_feeds_aggregates():
    entries_a = [{"title": "A1", "link": "https://a.com/1"}]
    entries_b = [{"title": "B1", "link": "https://b.com/1"}]

    mock_feed_a = _mock_feed(entries_a)
    mock_feed_b = _mock_feed(entries_b)

    def mock_parse(content, **kwargs):
        # feedparser.parse receives the content bytes, not URL
        # We need to differentiate based on call order or content
        if mock_parse.call_count == 1:
            return mock_feed_a
        return mock_feed_b

    mock_parse.call_count = 0

    def counting_parse(content, **kwargs):
        mock_parse.call_count += 1
        return mock_parse(content, **kwargs)

    feeds = {"SourceA": "https://a.com/rss", "SourceB": "https://b.com/rss"}
    with patch("src.fetcher.feedparser.parse", side_effect=counting_parse):
        with patch("src.fetcher.requests.get", return_value=_mock_response(b"fake rss content")):
            articles = fetch_all_feeds(feeds)
    assert len(articles) == 2
    sources = {a.source for a in articles}
    assert sources == {"SourceA", "SourceB"}