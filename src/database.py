import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from src.config import DB_PATH
from src.utils import normalize_url


@contextmanager
def get_connection(db_path: str = DB_PATH):
    """Context manager for database connections."""
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    try:
        yield conn
    finally:
        conn.close()


def init_db(db_path: str = DB_PATH) -> None:
    """Initialize database with schema and indexes."""
    with get_connection(db_path) as conn:
        conn.execute("""
            CREATE TABLE IF NOT EXISTS published_articles (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                url TEXT UNIQUE NOT NULL,
                normalized_url TEXT NOT NULL,
                title TEXT NOT NULL,
                source TEXT NOT NULL,
                score REAL,
                linkedin_post TEXT,
                published_at TEXT,
                created_at TEXT NOT NULL
            )
        """)
        # Index on normalized_url for fast duplicate lookups
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_published_normalized_url
            ON published_articles(normalized_url)
        """)
        # Index on source for source diversity queries
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_published_source
            ON published_articles(source)
        """)
        conn.commit()


def migrate_db(db_path: str = DB_PATH) -> None:
    """
    Migrate existing database to add normalized_url column and indexes.
    Safe to run multiple times.
    """
    with get_connection(db_path) as conn:
        # Check if normalized_url column exists
        cols = [row[1] for row in conn.execute("PRAGMA table_info(published_articles)").fetchall()]

        if "normalized_url" not in cols:
            # Add normalized_url column
            conn.execute("ALTER TABLE published_articles ADD COLUMN normalized_url TEXT")
            # Populate normalized_url for existing rows
            rows = conn.execute("SELECT id, url FROM published_articles").fetchall()
            for row in rows:
                norm_url = normalize_url(row["url"])
                conn.execute(
                    "UPDATE published_articles SET normalized_url = ? WHERE id = ?",
                    (norm_url, row["id"]),
                )
            conn.commit()

        # Create indexes if they don't exist
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_published_normalized_url
            ON published_articles(normalized_url)
        """)
        conn.execute("""
            CREATE INDEX IF NOT EXISTS idx_published_source
            ON published_articles(source)
        """)
        conn.commit()


def is_already_published(url: str, db_path: str = DB_PATH) -> bool:
    """Check if URL (normalized) has already been published."""
    norm_url = normalize_url(url)
    with get_connection(db_path) as conn:
        row = conn.execute(
            "SELECT 1 FROM published_articles WHERE normalized_url = ?", (norm_url,)
        ).fetchone()
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
    """Save article with normalized URL for deduplication."""
    norm_url = normalize_url(url)
    with get_connection(db_path) as conn:
        conn.execute(
            """
            INSERT OR IGNORE INTO published_articles
                (url, normalized_url, title, source, score, linkedin_post, published_at, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                url,
                norm_url,
                title,
                source,
                score,
                linkedin_post,
                published_at,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()


def get_published_urls(db_path: str = DB_PATH) -> set[str]:
    """Get all published URLs (original URLs)."""
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT url FROM published_articles").fetchall()
        return {row["url"] for row in rows}


def get_published_normalized_urls(db_path: str = DB_PATH) -> set[str]:
    """Get all published normalized URLs for deduplication."""
    with get_connection(db_path) as conn:
        rows = conn.execute("SELECT normalized_url FROM published_articles").fetchall()
        return {row["normalized_url"] for row in rows}