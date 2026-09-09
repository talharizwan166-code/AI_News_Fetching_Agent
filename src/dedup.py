import re
from src.fetcher import Article


def _normalize(text: str) -> str:
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", "", text)
    text = re.sub(r"\s+", " ", text)
    return text


def deduplicate(articles: list[Article]) -> list[Article]:
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[Article] = []

    for article in articles:
        url = article.url.strip().rstrip("/")
        norm_title = _normalize(article.title)

        if url in seen_urls or norm_title in seen_titles:
            continue

        seen_urls.add(url)
        seen_titles.add(norm_title)
        unique.append(article)

    return unique
