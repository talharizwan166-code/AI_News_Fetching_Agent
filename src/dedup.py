import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse
from src.fetcher import Article
from src.database import get_published_urls


_UTM_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "fbclid", "gclid", "msclkid", "ref", "source", "mc_cid", "mc_eid",
}


def _normalize_url(url: str) -> str:
    """Normalize URL: strip utm_*/tracking params, fragments, lowercase, strip trailing slash."""
    if not url:
        return url

    parsed = urlparse(url.strip())

    # Strip fragment
    parsed = parsed._replace(fragment="")

    # Filter query params
    query_params = parse_qs(parsed.query, keep_blank_values=True)
    filtered = {
        k: v for k, v in query_params.items()
        if k.lower() not in _UTM_PARAMS
    }
    new_query = urlencode(filtered, doseq=True)
    parsed = parsed._replace(query=new_query)

    # Reconstruct, lowercase scheme and netloc, strip trailing slash from path
    normalized = urlunparse(parsed)
    normalized = normalized.rstrip("/")

    return normalized


def _normalize_title(text: str) -> str:
    """Normalize title for comparison: lowercase, strip punctuation, collapse whitespace."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


def deduplicate(articles: list[Article]) -> list[Article]:
    """
    Remove duplicates within the batch using normalized URLs and titles.
    """
    seen_urls: set[str] = set()
    seen_titles: set[str] = set()
    unique: list[Article] = []

    for article in articles:
        norm_url = _normalize_url(article.url)
        norm_title = _normalize_title(article.title)

        if norm_url in seen_urls or norm_title in seen_titles:
            continue

        seen_urls.add(norm_url)
        seen_titles.add(norm_title)
        unique.append(article)

    return unique


def filter_published(articles: list[Article]) -> list[Article]:
    """
    Remove articles that have already been published (using normalized URL comparison).
    """
    published_urls = get_published_urls()
    # Normalize published URLs for comparison
    published_normalized = {_normalize_url(u) for u in published_urls}

    filtered = []
    for article in articles:
        norm_url = _normalize_url(article.url)
        if norm_url in published_normalized:
            continue
        filtered.append(article)

    return filtered