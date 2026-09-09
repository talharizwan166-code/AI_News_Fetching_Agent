from unittest.mock import patch, MagicMock
from src.fetcher import Article
from src.agent import run_agent


def _articles():
    return [
        Article(title="AI News 1", url="https://a.com/1", source="SourceA", summary="Deep learning breakthrough"),
        Article(title="AI News 2", url="https://b.com/1", source="SourceB", summary="New LLM model released"),
    ]


@patch("src.agent.save_article")
@patch("src.agent.send_email")
@patch("src.agent.create_approval_issue", return_value="https://github.com/test/issues/1")
@patch("src.agent.generate_linkedin_post", return_value="A great LinkedIn post")
@patch("src.agent.select_best_article")
@patch("src.agent.get_published_urls", return_value=set())
@patch("src.agent.init_db")
@patch("src.agent.fetch_all_feeds")
def test_full_pipeline_success(mock_fetch, mock_init, mock_urls, mock_select, mock_gen, mock_issue, mock_email, mock_save):
    articles = _articles()
    mock_fetch.return_value = articles
    mock_select.return_value = articles[0]
    result = run_agent()
    assert result["status"] == "success"
    mock_gen.assert_called_once()
    mock_issue.assert_called_once()
    mock_email.assert_called_once()
    mock_save.assert_called_once()


@patch("src.agent.init_db")
@patch("src.agent.fetch_all_feeds", return_value=[])
def test_no_articles_fetched(mock_fetch, mock_init):
    result = run_agent()
    assert result["status"] == "no_articles"


@patch("src.agent.get_published_urls")
@patch("src.agent.init_db")
@patch("src.agent.fetch_all_feeds")
def test_all_already_published(mock_fetch, mock_init, mock_urls):
    articles = _articles()
    mock_fetch.return_value = articles
    mock_urls.return_value = {a.url for a in articles}
    result = run_agent()
    assert result["status"] == "all_published"


@patch("src.agent.get_published_urls", return_value=set())
@patch("src.agent.init_db")
@patch("src.agent.fetch_all_feeds")
def test_below_threshold(mock_fetch, mock_init, mock_urls):
    articles = _articles()
    for a in articles:
        a.score = 0.01
    mock_fetch.return_value = articles

    with patch("src.agent.select_best_article", return_value=None):
        result = run_agent()
    assert result["status"] == "below_threshold"
