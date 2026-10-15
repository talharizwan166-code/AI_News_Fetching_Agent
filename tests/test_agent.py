from unittest.mock import patch
from pathlib import Path
import shutil

import pytest

from src.database import init_db, save_article
from src.fetcher import Article
from src.agent import run_agent


@pytest.fixture(autouse=True)
def agent_db(tmp_path, monkeypatch):
    """Exercise initialization and migration without touching the local database."""
    db_path = str(tmp_path / "news_agent.db")
    monkeypatch.setattr("src.agent.DB_PATH", db_path)
    return db_path


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
@patch("src.agent.fetch_all_feeds")
def test_full_pipeline_success(mock_fetch, mock_filter, mock_select, mock_gen, mock_issue, mock_email, mock_save):
    articles = _articles()
    mock_fetch.return_value = articles
    mock_select.return_value = articles[0]
    result = run_agent()
    assert result["status"] == "success"
    mock_gen.assert_called_once()
    mock_issue.assert_called_once()
    mock_email.assert_called_once()
    mock_save.assert_called_once()


@patch("src.agent.fetch_all_feeds", return_value=[])
def test_no_articles_fetched(mock_fetch):
    result = run_agent()
    assert result["status"] == "no_articles"


@patch("src.agent.filter_published", return_value=[])
@patch("src.agent.fetch_all_feeds")
def test_all_already_published(mock_fetch, mock_filter):
    articles = _articles()
    mock_fetch.return_value = articles
    result = run_agent()
    assert result["status"] == "all_published"


@patch("src.agent.filter_published", return_value=_articles())
@patch("src.agent.fetch_all_feeds")
def test_below_threshold(mock_fetch, mock_filter):
    articles = _articles()
    for a in articles:
        a.score = 0.01
    mock_fetch.return_value = articles

    with patch("src.agent.select_best_article", return_value=None):
        result = run_agent()
    assert result["status"] == "below_threshold"


@pytest.fixture
def selected_pipeline(monkeypatch):
    monkeypatch.setattr("src.agent.fetch_all_feeds", _articles)
    monkeypatch.setattr(
        "src.agent.select_best_article", lambda articles, **kwargs: articles[0],
    )
    monkeypatch.setattr("src.agent.generate_linkedin_post", lambda article: "Generated post")


def test_generation_failure_leaves_article_unpublished(selected_pipeline, monkeypatch):
    def fail(article):
        raise RuntimeError("Generation unavailable")

    monkeypatch.setattr("src.agent.generate_linkedin_post", fail)
    with patch("src.agent.create_approval_issue") as issue, \
            patch("src.agent.send_email") as email, \
            patch("src.agent.save_article") as save:
        assert run_agent()["status"] == "gemini_failed"
        issue.assert_not_called()
        email.assert_not_called()
        save.assert_not_called()


@pytest.mark.parametrize("issue_fails, email_fails", [(True, True), (True, False), (False, True)])
def test_delivery_failures_only_mark_delivered_articles(
    selected_pipeline, issue_fails, email_fails,
):
    with patch("src.agent.create_approval_issue", return_value="https://example.com/issue") as issue, \
            patch("src.agent.send_email") as email, \
            patch("src.agent.save_article") as save:
        if issue_fails:
            issue.side_effect = RuntimeError("Issue delivery unavailable")
        if email_fails:
            email.side_effect = RuntimeError("Email delivery unavailable")
        result = run_agent()
        if issue_fails and email_fails:
            assert result["status"] == "delivery_failed"
            save.assert_not_called()
        else:
            assert result["status"] == "success"
            save.assert_called_once()


@pytest.mark.parametrize("database_state", ["missing", "current", "legacy"])
@pytest.mark.parametrize("generation_fails", [False, True])
def test_dry_run_never_creates_or_modifies_database(
    agent_db, selected_pipeline, legacy_db, monkeypatch, database_state, generation_fails,
):
    path = Path(agent_db)
    if database_state == "current":
        init_db(agent_db)
        article = _articles()[0]
        save_article(article.url, article.title, article.source, 0.9, "Existing post", db_path=agent_db)
    elif database_state == "legacy":
        shutil.copyfile(legacy_db, path)
    before = (path.read_bytes(), path.stat().st_mtime_ns) if path.exists() else None
    directory_before = set(path.parent.iterdir())
    if generation_fails:
        def fail(article):
            raise RuntimeError("Generation unavailable")
        monkeypatch.setattr("src.agent.generate_linkedin_post", fail)

    with patch("src.agent.init_db") as initialize, \
            patch("src.agent.create_approval_issue") as issue, \
            patch("src.agent.send_email") as email, \
            patch("src.agent.save_article") as save:
        result = run_agent(dry_run=True)
        assert result["status"] == ("gemini_failed" if generation_fails else "success")
        initialize.assert_not_called()
        issue.assert_not_called()
        email.assert_not_called()
        save.assert_not_called()

    if before is None:
        assert not path.exists()
    else:
        assert (path.read_bytes(), path.stat().st_mtime_ns) == before
    assert set(path.parent.iterdir()) == directory_before
