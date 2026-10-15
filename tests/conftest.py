import sqlite3

import pytest


@pytest.fixture
def legacy_db(tmp_path):
    """A populated database with the original, pre-normalization schema."""
    path = tmp_path / "legacy.db"
    with sqlite3.connect(path) as conn:
        conn.execute("""
            CREATE TABLE published_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                score REAL,
                linkedin_post TEXT,
                published_at TEXT,
                created_at TEXT NOT NULL
            )
        """)
        conn.execute("""
            INSERT INTO published_articles
                (url, title, source, score, linkedin_post, published_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?)
        """, (
            "https://example.com/old?utm_source=test#section", "Old article",
            "Original source", 0.8, "Original post", "2026-01-01", "2026-01-02",
        ))
    return path
