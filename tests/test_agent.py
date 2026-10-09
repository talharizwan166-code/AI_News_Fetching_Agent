from unittest.mock import patch, MagicMock
from src.fetcher import Article
from src.agent import run_agent


def _articles():
    return [
        Article(
            title="OpenAI Announces GPT-5 with Advanced Reasoning",
            url="https://a.com/1",
            source="SourceA",
            summary="OpenAI unveiled GPT-5, a new large language model with breakthrough reasoning capabilities. The transformer-based generative AI system shows significant improvements in coding and mathematics.",
        ),
        Article(
            title="Google DeepMind Releases New Multimodal AI Model",
            url="https://b.com/1",
            source="SourceB",
            summary="Google DeepMind announced a novel multimodal foundation model that combines vision and language. The AI agent can process images, text, and code simultaneously.",
        ),
    ]


@patch("src.agent.save_article")
@patch("src.agent.send_email")
@patch("src.agent.create_approval_issue", return_value="https://github.com/test/issues/1")
@patch("src.agent.generate_linkedin_post", return_value="A great LinkedIn post")
@patch("src.agent.select_best_article")
@patch("src.agent.filter_published", return_value=_articles())
@patch("src.agent.init_db")
@patch("src.agent.fetch_all_feeds")
def test_full_pipeline_success(mock_fetch, mock_init, mock_filter, mock_select, mock_gen, mock_issue, mock_email, mock_save):
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


@patch("src.agent.filter_published", return_value=[])
@patch("src.agent.init_db")
@patch("src.agent.fetch_all_feeds")
def test_all_already_published(mock_fetch, mock_init, mock_filter):
    articles = _articles()
    mock_fetch.return_value = articles
    result = run_agent()
    assert result["status"] == "all_published"


@patch("src.agent.filter_published", return_value=_articles())
@patch("src.agent.init_db")
@patch("src.agent.fetch_all_feeds")
def test_below_threshold(mock_fetch, mock_init, mock_filter):
    articles = _articles()
    for a in articles:
        a.score = 0.01
    mock_fetch.return_value = articles

    with patch("src.agent.select_best_article", return_value=None):
        result = run_agent()
    assert result["status"] == "below_threshold"