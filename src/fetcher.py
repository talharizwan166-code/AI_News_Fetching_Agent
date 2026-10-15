import logging
from dataclasses import dataclass, field
from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Optional
from urllib.parse import urlsplit

import feedparser
import requests

from src.config import RSS_FEEDS, FETCH_TIMEOUT_SECONDS

logger = logging.getLogger(__name__)


@dataclass
class Article:
    title: str
    url: str
    source: str
    summary: str = ""
    published_at: str = ""
    score: float = 0.0
    extra: dict = field(default_factory=dict)


def _parse_entry(entry, source: str) -> Optional[Article]:
    """Parse a single feed entry into an Article."""
    if not isinstance(entry, Mapping):
        return None
    link = entry.get("link", "")
    title = entry.get("title", "")
    if not isinstance(link, str) or not isinstance(title, str) or not link.strip() or not title.strip():
        return None
    link, title = link.strip(), title.strip()
    try:
        parsed_link = urlsplit(link)
        if parsed_link.scheme not in ("http", "https") or not parsed_link.netloc:
            return None
    except ValueError:
        return None

    pub_date = ""
    published = entry.get("published_parsed") or entry.get("updated_parsed")
    if published:
        try:
            pub_date = datetime(*published[:6], tzinfo=timezone.utc).isoformat()
        except (ValueError, TypeError, OverflowError):
            pass

    summary = entry.get("summary", "") or entry.get("description", "")
    if not isinstance(summary, str):
        summary = ""

    return Article(
        title=title,
        url=link,
        source=source,
        summary=summary,
        published_at=pub_date,
    )


def fetch_feed(name: str, url: str, timeout: int = FETCH_TIMEOUT_SECONDS) -> list[Article]:
    """
    Fetch a single RSS feed using requests, then parse with feedparser.
    Returns empty list on any error (network, parse, timeout) - never raises.
    """
    logger.debug("Fetching feed: %s (%s)", name, url)

    try:
        # Fetch with requests (handles timeout, redirects, SSL)
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "AINewsAgent/1.0"},
        )
        resp.raise_for_status()
        content = resp.content

    except requests.Timeout:
        logger.warning("Feed %s timed out after %ds", name, timeout)
        return []
    except requests.RequestException as exc:
        logger.warning("Feed %s request failed: %s", name, exc)
        return []
    except Exception as exc:
        logger.warning("Feed %s unexpected error: %s", name, exc)
        return []

    # Parse with feedparser
    try:
        feed = feedparser.parse(content)
    except Exception as exc:
        logger.warning("Feed %s parse error: %s", name, exc)
        return []

    if feed.bozo and not feed.entries:
        logger.warning("Feed %s returned parse error: %s", name, feed.bozo_exception)
        return []

    articles = []
    for entry in feed.entries:
        article = _parse_entry(entry, name)
        if article:
            articles.append(article)

    logger.info("Fetched %d articles from %s", len(articles), name)
    return articles


def fetch_all_feeds(
    feeds: dict[str, str] | None = None,
    timeout: int = FETCH_TIMEOUT_SECONDS,
) -> list[Article]:
    """Fetch all feeds. One failed feed never stops the run."""
    if feeds is None:
        feeds = RSS_FEEDS

    all_articles: list[Article] = []
    for name, url in feeds.items():
        articles = fetch_feed(name, url, timeout)
        all_articles.extend(articles)

    logger.info("Total articles fetched: %d from %d feeds", len(all_articles), len(feeds))
    return all_articles
