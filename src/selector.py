from collections import defaultdict
from src.fetcher import Article
from src.config import MIN_QUALITY_THRESHOLD


def select_best_article(
    articles: list[Article],
    min_threshold: float = MIN_QUALITY_THRESHOLD,
) -> Article | None:
    if not articles:
        return None

    by_source: dict[str, list[Article]] = defaultdict(list)
    for article in articles:
        by_source[article.source].append(article)

    candidates: list[Article] = []
    for source, source_articles in by_source.items():
        best = max(source_articles, key=lambda a: a.score)
        if best.score >= min_threshold:
            candidates.append(best)

    if not candidates:
        return None

    candidates.sort(key=lambda a: a.score, reverse=True)
    return candidates[0]
