import logging
from dataclasses import dataclass, field
from datetime import datetime, timezone

import feedparser

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


def fetch_feed(name: str, url: str, timeout: int = FETCH_TIMEOUT_SECONDS) -> list[Article]:
    try:
        feed = feedparser.parse(url, request_headers={"User-Agent": "AINewsAgent/1.0"})
        if feed.bozo and not feed.entries:
            logger.warning("Feed %s returned an error: %s", name, feed.bozo_exception)
            return []

        articles = []
        for entry in feed.entries:
            link = entry.get("link", "")
            title = entry.get("title", "")
            if not link or not title:
                continue

            pub_date = ""
            if "published_parsed" in entry and entry.published_parsed:
                pub_date = datetime(*entry.published_parsed[:6], tzinfo=timezone.utc).isoformat()

            summary = entry.get("summary", "")

            articles.append(Article(
                title=title.strip(),
                url=link.strip(),
                source=name,
                summary=summary,
                published_at=pub_date,
            ))

        logger.info("Fetched %d articles from %s", len(articles), name)
        return articles

    except Exception as exc:
        logger.error("Failed to fetch feed %s: %s", name, exc)
        return []


def fetch_all_feeds(
    feeds: dict[str, str] | None = None,
    timeout: int = FETCH_TIMEOUT_SECONDS,
) -> list[Article]:
    if feeds is None:
        feeds = RSS_FEEDS

    all_articles: list[Article] = []
    for name, url in feeds.items():
        articles = fetch_feed(name, url, timeout)
        all_articles.extend(articles)

    logger.info("Total articles fetched: %d", len(all_articles))
    return all_articles
