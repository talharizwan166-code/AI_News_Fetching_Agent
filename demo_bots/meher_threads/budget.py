"""Persistent, at-most-once target reservations; never stores request contents."""

import hashlib
import json
import sqlite3
import threading
import uuid
from datetime import datetime, timezone


class BudgetStop(Exception):
    """No request may be made with this reservation."""


class TargetBudget:
    def __init__(self, path, session, metadata, *, max_calls, max_output_tokens):
        if type(max_calls) is not int or max_calls < 0:
            raise ValueError("Target max calls must be a nonnegative integer")
        if type(max_output_tokens) is not int or not 1 <= max_output_tokens <= 8192:
            raise ValueError("Target max output tokens must be between 1 and 8192")
        self.max_calls, self.max_output_tokens = max_calls, max_output_tokens
        self.session = session
        self.lock = threading.Lock()
        self.db = sqlite3.connect(str(path), timeout=30, check_same_thread=False)
        signature = hashlib.sha256(json.dumps(metadata, sort_keys=True).encode()).hexdigest()
        try:
            self.db.executescript("""
                CREATE TABLE IF NOT EXISTS budgets (
                    session TEXT PRIMARY KEY, signature TEXT NOT NULL,
                    max_calls INTEGER NOT NULL, max_output_tokens INTEGER NOT NULL);
                CREATE TABLE IF NOT EXISTS calls (
                    session TEXT NOT NULL, request_id TEXT NOT NULL, created_at TEXT NOT NULL,
                    PRIMARY KEY (session, request_id));
            """)
            with self.db:
                self.db.execute("BEGIN IMMEDIATE")
                self.db.execute("INSERT OR IGNORE INTO budgets VALUES (?, ?, ?, ?)",
                                (session, signature, max_calls, max_output_tokens))
                saved = self.db.execute("SELECT signature, max_calls, max_output_tokens FROM budgets WHERE session=?", (session,)).fetchone()
                if saved != (signature, max_calls, max_output_tokens):
                    raise ValueError("Saved target budget configuration differs; use the original configuration")
        except Exception:
            self.db.close()
            raise

    @property
    def calls(self):
        with self.lock:
            return self.db.execute("SELECT COUNT(*) FROM calls WHERE session=?", (self.session,)).fetchone()[0]

    def reserve(self, request_id=None):
        request_id = request_id or uuid.uuid4().hex
        with self.lock, self.db:
            self.db.execute("BEGIN IMMEDIATE")
            if self.db.execute("SELECT 1 FROM calls WHERE session=? AND request_id=?", (self.session, request_id)).fetchone():
                raise BudgetStop("Request already reserved; it will not be repeated")
            count = self.db.execute("SELECT COUNT(*) FROM calls WHERE session=?", (self.session,)).fetchone()[0]
            if count >= self.max_calls:
                raise BudgetStop("Target call budget exhausted")
            self.db.execute("INSERT INTO calls VALUES (?, ?, ?)",
                            (self.session, request_id, datetime.now(timezone.utc).isoformat()))

    def close(self):
        self.db.close()
