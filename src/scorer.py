import re
from datetime import datetime, timezone
from src.fetcher import Article
from src.config import SCORING_WEIGHTS, SOURCE_CREDIBILITY

AI_KEYWORDS = [
    "artificial intelligence", "machine learning", "deep learning", "neural network",
    "llm", "large language model", "gpt", "transformer", "generative ai",
    "diffusion model", "reinforcement learning", "computer vision", "nlp",
    "natural language processing", "chatbot", "ai agent", "openai", "anthropic",
    "google ai", "meta ai", "mistral", "llama", "gemini", "claude",
    "ai safety", "alignment", "multimodal", "foundation model", "fine-tuning",
    "rag", "retrieval augmented", "embedding", "vector database",
]

DEV_KEYWORDS = [
    "api", "sdk", "open source", "github", "developer", "framework",
    "library", "tool", "release", "benchmark", "model weights",
    "python", "pytorch", "tensorflow", "hugging face", "deployment",
    "inference", "training", "fine-tune", "prompt engineering",
]

INNOVATION_KEYWORDS = [
    "breakthrough", "novel", "first", "new approach", "state-of-the-art",
    "outperforms", "revolutionary", "unprecedented", "launch", "announce",
    "release", "introduce", "discover", "invent",
]

# Compile word-boundary regex patterns for each keyword list
# Use \b for word boundaries, escape special chars
_AI_PATTERNS = [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in AI_KEYWORDS]
_DEV_PATTERNS = [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in DEV_KEYWORDS]
_INNOV_PATTERNS = [re.compile(rf"\b{re.escape(kw)}\b", re.IGNORECASE) for kw in INNOVATION_KEYWORDS]

# Exported for AI relevance filtering
AI_RELEVANCE_PATTERNS = _AI_PATTERNS

_HTML_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


def _strip_html(text: str) -> str:
    """Remove HTML tags and normalize whitespace."""
    if not text:
        return ""
    text = _HTML_TAG_RE.sub(" ", text)
    text = _WHITESPACE_RE.sub(" ", text)
    return text.strip()


def _keyword_score(text: str, patterns: list[re.Pattern]) -> float:
    """Score based on word-boundary regex matches."""
    if not text:
        return 0.0
    hits = sum(1 for pat in patterns if pat.search(text))
    max_possible = min(len(patterns), 8)
    return min(hits / max_possible, 1.0)


def ai_relevance_score(text: str) -> float:
    """Public function to compute AI relevance score for filtering."""
    clean_text = _strip_html(text)
    return _keyword_score(clean_text, AI_RELEVANCE_PATTERNS)


def _freshness_score(published_at: str) -> float:
    if not published_at:
        return 0.5
    try:
        pub_time = datetime.fromisoformat(published_at)
        now = datetime.now(timezone.utc)
        hours_old = (now - pub_time).total_seconds() / 3600
        if hours_old <= 6:
            return 1.0
        if hours_old <= 24:
            return 0.85
        if hours_old <= 48:
            return 0.6
        if hours_old <= 72:
            return 0.4
        return 0.2
    except (ValueError, TypeError):
        return 0.5


def score_article(article: Article) -> float:
    # Strip HTML from summary before scoring
    clean_summary = _strip_html(article.summary)
    text = f"{article.title} {clean_summary}"

    ai_score = _keyword_score(text, _AI_PATTERNS)
    dev_score = _keyword_score(text, _DEV_PATTERNS)
    innov_score = _keyword_score(text, _INNOV_PATTERNS)
    fresh_score = _freshness_score(article.published_at)
    cred_score = SOURCE_CREDIBILITY.get(article.source, 0.5)

    total = (
        SCORING_WEIGHTS["ai_relevance"] * ai_score
        + SCORING_WEIGHTS["developer_relevance"] * dev_score
        + SCORING_WEIGHTS["innovation"] * innov_score
        + SCORING_WEIGHTS["freshness"] * fresh_score
        + SCORING_WEIGHTS["source_credibility"] * cred_score
    )
    return round(total, 4)


def score_and_rank(articles: list[Article]) -> list[Article]:
    for article in articles:
        article.score = score_article(article)
    return sorted(articles, key=lambda a: a.score, reverse=True)