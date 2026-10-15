import json
import re
import shutil
import sqlite3
import textwrap
from pathlib import Path
from unittest.mock import patch

import pytest

from src.database import init_db, save_article, seed_from_json
from src.utils import normalize_url


SEED_PATH = Path(__file__).resolve().parents[1] / "data" / "seed_published.json"


def _rows(path):
    with sqlite3.connect(path) as conn:
        conn.row_factory = sqlite3.Row
        return [dict(row) for row in conn.execute("SELECT * FROM published_articles ORDER BY id")]


def test_seed_imports_committed_history_and_is_idempotent(tmp_path):
    path = str(tmp_path / "seed.db")
    articles = json.loads(SEED_PATH.read_text(encoding="utf-8"))
    assert len(articles) == 3
    assert all(set(article) == {"url", "title", "source"} for article in articles)
    assert seed_from_json(path, str(SEED_PATH)) == 3
    before = _rows(path)
    assert [{key: row[key] for key in ("url", "title", "source")} for row in before] == articles
    assert all(row["normalized_url"] == normalize_url(row["url"]) for row in before)
    assert seed_from_json(path, str(SEED_PATH)) == 0
    assert _rows(path) == before


def test_seed_ignores_normalized_duplicates_and_preserves_existing_metadata(tmp_path):
    path = str(tmp_path / "seed.db")
    init_db(path)
    save_article("https://example.com/item?utm_source=old#section", "Keep title", "Keep source", 0.9, "Keep post", db_path=path)
    before = _rows(path)
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps([
        {"url": "https://example.com/item", "title": "New title", "source": "New source"},
        {"url": "https://example.com/item?utm_campaign=test", "title": "Other title", "source": "Other source"},
    ]), encoding="utf-8")
    assert seed_from_json(path, str(seed)) == 0
    assert _rows(path) == before


def test_seed_migrates_legacy_database_without_losing_history(legacy_db):
    before = _rows(legacy_db)[0]
    assert seed_from_json(str(legacy_db), str(SEED_PATH)) == 3
    rows = _rows(legacy_db)
    assert len(rows) == 4
    assert all(rows[0][key] == value for key, value in before.items())
    assert rows[0]["normalized_url"] == normalize_url(before["url"])


@pytest.mark.parametrize("payload", [{}, [{"url": "https://example.com"}], [None]])
def test_invalid_seed_does_not_create_database(tmp_path, payload):
    path = tmp_path / "seed.db"
    seed = tmp_path / "seed.json"
    seed.write_text(json.dumps(payload), encoding="utf-8")
    with pytest.raises(ValueError):
        seed_from_json(str(path), str(seed))
    assert not path.exists()


@pytest.mark.parametrize("already_populated", [False, True])
def test_workflow_only_seeds_an_empty_database(tmp_path, monkeypatch, already_populated):
    workflow = (SEED_PATH.parents[1] / ".github/workflows/news_agent.yml").read_text(encoding="utf-8")
    match = re.search(r"^          python - <<'PY'\n(.*?)^          PY$", workflow, re.M | re.S)
    assert match is not None
    script = textwrap.dedent(match.group(1))
    (tmp_path / "data").mkdir()
    (tmp_path / "data-branch").mkdir()
    shutil.copyfile(SEED_PATH, tmp_path / "data/seed_published.json")
    path = str(tmp_path / "data-branch/news_agent.db")
    if already_populated:
        init_db(path)
        save_article("https://example.com/existing", "Keep title", "Keep source", 0.9, "Keep post", db_path=path)
        before = _rows(path)
    monkeypatch.chdir(tmp_path)
    with patch("src.database.seed_from_json", wraps=seed_from_json) as seed:
        exec(compile(script, "workflow-seed", "exec"), {})
        if already_populated:
            seed.assert_not_called()
            assert _rows(path) == before
        else:
            seed.assert_called_once_with("data-branch/news_agent.db", "data/seed_published.json")
            assert len(_rows(path)) == 3
