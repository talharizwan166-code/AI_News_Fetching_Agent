from unittest.mock import Mock, patch

import pytest

from src.check_feeds import check_feed, main


@pytest.mark.parametrize("body, content_type, healthy", [
    (b"<html><body>Access denied</body></html>", "text/html", False),
    (b"<html>Error</html>", "application/rss+xml", False),
    (b"<?xml version='1.0'?><error>Unavailable</error>", "application/xml", False),
    (b"<rss version='2.0'><channel><title>Feed</title></channel></rss>", "text/html", True),
    (b"<feed xmlns='http://www.w3.org/2005/Atom'><title>Feed</title></feed>", "application/atom+xml", True),
])
def test_feed_health_checks_content_not_just_http_200(body, content_type, healthy):
    response = Mock(status_code=200, content=body, headers={"Content-Type": content_type})
    with patch("src.check_feeds.requests.get", return_value=response):
        name, actual, message, _ = check_feed("Source", "https://example.com/rss", 10)
    assert name == "Source"
    assert actual is healthy
    assert ("not a usable RSS/Atom feed" in message) is (not healthy)


@pytest.mark.parametrize("argument", ["--timeout", "--workers"])
def test_health_cli_rejects_nonpositive_limits_before_fetching(monkeypatch, argument):
    monkeypatch.setattr("sys.argv", ["check_feeds", argument, "0"])
    with patch("src.check_feeds.requests.get") as fetch, pytest.raises(SystemExit) as caught:
        main()
    assert caught.value.code == 2
    fetch.assert_not_called()
