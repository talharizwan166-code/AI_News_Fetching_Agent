from src.fetcher import Article
from src.dedup import deduplicate


def _article(title="Title", url="https://example.com", source="Src"):
    return Article(title=title, url=url, source=source)


def test_removes_duplicate_urls():
    articles = [
        _article(title="A", url="https://example.com/1"),
        _article(title="B", url="https://example.com/1"),
    ]
    result = deduplicate(articles)
    assert len(result) == 1
    assert result[0].title == "A"


def test_removes_duplicate_titles():
    articles = [
        _article(title="Same Title", url="https://a.com"),
        _article(title="Same Title", url="https://b.com"),
    ]
    result = deduplicate(articles)
    assert len(result) == 1


def test_normalizes_title_for_dedup():
    articles = [
        _article(title="AI: The Future!", url="https://a.com"),
        _article(title="  ai the future  ", url="https://b.com"),
    ]
    result = deduplicate(articles)
    assert len(result) == 1


def test_keeps_distinct_articles():
    articles = [
        _article(title="Article One", url="https://a.com/1"),
        _article(title="Article Two", url="https://b.com/2"),
    ]
    result = deduplicate(articles)
    assert len(result) == 2


def test_empty_list():
    assert deduplicate([]) == []


def test_trailing_slash_url_dedup():
    articles = [
        _article(title="A", url="https://example.com/page/"),
        _article(title="B", url="https://example.com/page"),
    ]
    result = deduplicate(articles)
    assert len(result) == 1
