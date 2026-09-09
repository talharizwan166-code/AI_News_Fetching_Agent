import sqlite3
from datetime import datetime, timezone
from src.config import DB_PATH


def get_connection(db_path: str = DB_PATH) -> sqlite3.Connection:
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    return conn


def init_db(db_path: str = DB_PATH) -> None:
    conn = get_connection(db_path)
    conn.execute("""
        CREATE TABLE IF NOT EXISTS published_articles (
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
    conn.commit()
    conn.close()


def is_already_published(url: str, db_path: str = DB_PATH) -> bool:
    conn = get_connection(db_path)
    row = conn.execute(
        "SELECT 1 FROM published_articles WHERE url = ?", (url,)
    ).fetchone()
    conn.close()
    return row is not None


def save_article(
    url: str,
    title: str,
    source: str,
    score: float,
    linkedin_post: str,
    published_at: str = "",
    db_path: str = DB_PATH,
) -> None:
    conn = get_connection(db_path)
    conn.execute(
        """
        INSERT OR IGNORE INTO published_articles
            (url, title, source, score, linkedin_post, published_at, created_at)
        VALUES (?, ?, ?, ?, ?, ?, ?)
        """,
        (
            url,
            title,
            source,
            score,
            linkedin_post,
            published_at,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    conn.commit()
    conn.close()


def get_published_urls(db_path: str = DB_PATH) -> set[str]:
    conn = get_connection(db_path)
    rows = conn.execute("SELECT url FROM published_articles").fetchall()
    conn.close()
    return {row["url"] for row in rows}
