import os
import tempfile
import sqlite3
import pytest
from src.database import init_db, migrate_db, save_article, is_already_published, get_published_urls
from src.utils import normalize_url


@pytest.fixture
def db_path():
    fd, path = tempfile.mkstemp(suffix=".db")
    os.close(fd)
    init_db(path)
    yield path
    os.unlink(path)


def test_init_creates_table(db_path):
    import sqlite3
    conn = sqlite3.connect(db_path)
    tables = conn.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    ).fetchall()
    conn.close()
    table_names = [t[0] for t in tables]
    assert "published_articles" in table_names


def test_save_and_check_published(db_path):
    assert not is_already_published("https://example.com/1", db_path)
    save_article(
        url="https://example.com/1",
        title="Test Article",
        source="TestSource",
        score=0.85,
        linkedin_post="A post",
        db_path=db_path,
    )
    assert is_already_published("https://example.com/1", db_path)


def test_duplicate_insert_ignored(db_path):
    save_article("https://example.com/1", "Title", "Src", 0.8, "Post", db_path=db_path)
    save_article("https://example.com/1", "Title", "Src", 0.9, "Post2", db_path=db_path)
    urls = get_published_urls(db_path)
    assert len(urls) == 1


def test_get_published_urls(db_path):
    save_article("https://a.com", "A", "S1", 0.5, "P1", db_path=db_path)
    save_article("https://b.com", "B", "S2", 0.6, "P2", db_path=db_path)
    urls = get_published_urls(db_path)
    assert urls == {"https://a.com", "https://b.com"}


@pytest.mark.parametrize("initialize", [init_db, migrate_db])
def test_legacy_migration_preserves_history_before_index_creation(legacy_db, initialize):
    with sqlite3.connect(legacy_db) as conn:
        before = conn.execute("SELECT * FROM published_articles").fetchone()
    initialize(str(legacy_db))
    initialize(str(legacy_db))
    with sqlite3.connect(legacy_db) as conn:
        conn.row_factory = sqlite3.Row
        rows = conn.execute("SELECT * FROM published_articles").fetchall()
        indexes = {row[1] for row in conn.execute("PRAGMA index_list(published_articles)")}
    assert len(rows) == 1
    assert tuple(rows[0])[:len(before)] == before
    assert rows[0]["normalized_url"] == normalize_url(rows[0]["url"])
    assert {"idx_published_normalized_url", "idx_published_source"} <= indexes
    assert is_already_published("https://example.com/old", str(legacy_db))
