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


def _keyword_score(text: str, keywords: list[str]) -> float:
    text_lower = text.lower()
    hits = sum(1 for kw in keywords if kw in text_lower)
    max_possible = min(len(keywords), 8)
    return min(hits / max_possible, 1.0)


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
    text = f"{article.title} {article.summary}"

    ai_score = _keyword_score(text, AI_KEYWORDS)
    dev_score = _keyword_score(text, DEV_KEYWORDS)
    innov_score = _keyword_score(text, INNOVATION_KEYWORDS)
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
