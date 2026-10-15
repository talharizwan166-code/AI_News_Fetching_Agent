from src.fetcher import Article
from src.config import DB_PATH
from src.database import get_published_normalized_urls
from src.utils import normalize_url, normalize_title, strip_html


def deduplicate(articles: list[Article]) -> list[Article]:
    """
    Remove duplicates within the batch using normalized URLs and titles.
    """
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[Article] = []

    for article in articles:
        norm_url = normalize_url(article.url)
        norm_title = normalize_title(article.title)

        if norm_url in seen_urls or norm_title in seen_titles:
            continue

        seen_urls.add(norm_url)
        seen_titles.add(norm_title)
        unique.append(article)

    return unique


def filter_published(
    articles: list[Article], *, db_path: str = DB_PATH, read_only: bool = False,
) -> list[Article]:
    """
    Remove articles that have already been published (using normalized URL comparison).
    """
    published_normalized = get_published_normalized_urls(db_path, read_only=read_only)

    filtered = []
    for article in articles:
        norm_url = normalize_url(article.url)
        if norm_url in published_normalized:
            continue
        filtered.append(article)

    return filtered
