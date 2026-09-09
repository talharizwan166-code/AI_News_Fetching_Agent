from src.fetcher import Article
from src.selector import select_best_article


def _article(title="T", url="https://x.com", source="Src", score=0.5):
    a = Article(title=title, url=url, source=source)
    a.score = score
    return a


def test_selects_highest_scoring():
    articles = [
        _article(source="A", score=0.9),
        _article(source="B", score=0.8),
        _article(source="C", score=0.7),
    ]
    best = select_best_article(articles)
    assert best.source == "A"
    assert best.score == 0.9


def test_source_diversity_one_source_dominates():
    articles = [
        _article(title="A1", url="https://a.com/1", source="DominantSource", score=0.95),
        _article(title="A2", url="https://a.com/2", source="DominantSource", score=0.90),
        _article(title="A3", url="https://a.com/3", source="DominantSource", score=0.85),
        _article(title="B1", url="https://b.com/1", source="OtherSource", score=0.80),
    ]
    best = select_best_article(articles)
    assert best.source == "DominantSource"
    assert best.score == 0.95


def test_diversity_picks_best_per_source():
    articles = [
        _article(title="A1", url="u1", source="X", score=0.9),
        _article(title="A2", url="u2", source="X", score=0.5),
        _article(title="B1", url="u3", source="Y", score=0.85),
        _article(title="B2", url="u4", source="Y", score=0.4),
    ]
    best = select_best_article(articles)
    assert best.source == "X"


def test_threshold_filters_low_quality():
    articles = [
        _article(source="A", score=0.1),
        _article(source="B", score=0.2),
    ]
    best = select_best_article(articles, min_threshold=0.5)
    assert best is None


def test_empty_articles():
    assert select_best_article([]) is None


def test_configurable_threshold():
    articles = [
        _article(source="A", score=0.35),
        _article(source="B", score=0.45),
    ]
    assert select_best_article(articles, min_threshold=0.5) is None
    assert select_best_article(articles, min_threshold=0.3) is not None
