from datetime import datetime, timezone, timedelta
from src.fetcher import Article
from src.scorer import score_article, score_and_rank, _freshness_score


def _article(title="Title", summary="", source="MIT Technology Review", published_at=""):
    return Article(
        title=title, url="https://example.com", source=source,
        summary=summary, published_at=published_at,
    )


def test_ai_heavy_article_scores_higher():
    ai_article = _article(
        title="OpenAI Releases New Large Language Model GPT-5",
        summary="A new transformer-based generative AI system",
    )
    generic_article = _article(
        title="Company Reports Q2 Earnings",
        summary="Revenue increased this quarter",
    )
    assert score_article(ai_article) > score_article(generic_article)


def test_freshness_recent_is_higher():
    now = datetime.now(timezone.utc)
    fresh = _freshness_score((now - timedelta(hours=2)).isoformat())
    stale = _freshness_score((now - timedelta(days=5)).isoformat())
    assert fresh > stale


def test_freshness_empty_string():
    assert _freshness_score("") == 0.5


def test_score_and_rank_sorts_descending():
    articles = [
        _article(title="Boring Company News", summary="nothing special"),
        _article(title="AI Breakthrough in Deep Learning Neural Network", summary="transformer LLM"),
    ]
    ranked = score_and_rank(articles)
    assert ranked[0].score >= ranked[1].score


def test_source_credibility_matters():
    high_cred = _article(title="AI News", source="MIT Technology Review")
    low_cred = _article(title="AI News", source="Unknown Source")
    assert score_article(high_cred) > score_article(low_cred)
