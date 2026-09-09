from unittest.mock import patch, MagicMock
from src.fetcher import fetch_feed, fetch_all_feeds, Article


def _mock_feed(entries):
    feed = MagicMock()
    feed.bozo = False
    feed.entries = entries
    return feed


def test_fetch_feed_parses_entries():
    entries = [
        {"title": "AI Breakthrough", "link": "https://example.com/1", "summary": "Great news"},
        {"title": "New Model", "link": "https://example.com/2", "summary": "Impressive"},
    ]
    with patch("src.fetcher.feedparser.parse", return_value=_mock_feed(entries)):
        articles = fetch_feed("TestSource", "https://fake.rss")
    assert len(articles) == 2
    assert articles[0].title == "AI Breakthrough"
    assert articles[0].source == "TestSource"


def test_fetch_feed_skips_entries_without_link():
    entries = [
        {"title": "No Link Article"},
        {"title": "Has Link", "link": "https://example.com/1"},
    ]
    with patch("src.fetcher.feedparser.parse", return_value=_mock_feed(entries)):
        articles = fetch_feed("Src", "https://fake.rss")
    assert len(articles) == 1


def test_fetch_feed_handles_exception():
    with patch("src.fetcher.feedparser.parse", side_effect=Exception("Network error")):
        articles = fetch_feed("Src", "https://fake.rss")
    assert articles == []


def test_fetch_feed_handles_bozo_with_no_entries():
    feed = MagicMock()
    feed.bozo = True
    feed.entries = []
    feed.bozo_exception = "Bad XML"
    with patch("src.fetcher.feedparser.parse", return_value=feed):
        articles = fetch_feed("Src", "https://fake.rss")
    assert articles == []


def test_fetch_all_feeds_aggregates():
    entries_a = [{"title": "A1", "link": "https://a.com/1"}]
    entries_b = [{"title": "B1", "link": "https://b.com/1"}]

    def mock_parse(url, **kwargs):
        if "a.com" in url:
            return _mock_feed(entries_a)
        return _mock_feed(entries_b)

    feeds = {"SourceA": "https://a.com/rss", "SourceB": "https://b.com/rss"}
    with patch("src.fetcher.feedparser.parse", side_effect=mock_parse):
        articles = fetch_all_feeds(feeds)
    assert len(articles) == 2
    sources = {a.source for a in articles}
    assert sources == {"SourceA", "SourceB"}
