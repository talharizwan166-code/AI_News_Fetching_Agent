"""
Shared utilities for URL normalization and text processing.
"""
import re
from urllib.parse import urlparse, parse_qs, urlencode, urlunparse


_UTM_PARAMS = {
    "utm_source", "utm_medium", "utm_campaign", "utm_term", "utm_content",
    "utm_id", "utm_source_platform", "utm_creative_format", "utm_marketing_tactic",
    "fbclid", "gclid", "msclkid", "ref", "source", "mc_cid", "mc_eid",
}


def normalize_url(url: str) -> str:
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


def normalize_title(text: str) -> str:
    """Normalize title for comparison: lowercase, strip punctuation, collapse whitespace."""
    if not text:
        return ""
    text = text.lower().strip()
    text = re.sub(r"[^a-z0-9\s]", " ", text)
    text = re.sub(r"\s+", " ", text)
    return text.strip()


_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    if not text:
        return ""
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()