"""Monitoring persistence helpers; credentials stay in memory only."""

from dataclasses import replace
import hashlib
import os
from pathlib import Path
import re
import sqlite3
from urllib.parse import quote, quote_plus, urlsplit, parse_qsl

from .judge import Verdict
from .report import Redactor
from .storage import Storage, now


def secret_redactor(extra_values=()):
    names = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|CREDENTIAL|AUTH|COOKIE|WEBHOOK|CONNECTION_STRING", re.I)
    explicit = set(os.environ.get("CHATCHECK_SECRET_ENV_NAMES", "").split(","))
    literals = {encoded for name, value in os.environ.items() if value and (names.search(name) or name in explicit)
                for encoded in (value, quote(value, safe=""), quote_plus(value))}
    literals.update(encoded for value in extra_values if value for encoded in (value, quote(value, safe=""), quote_plus(value)))

    class SecretRedactor(Redactor):
        def text(self, value):
            text = str(value)
            for literal in sorted(literals, key=len, reverse=True):
                text = text.replace(literal, "[REDACTED]")
            return super().text(text)

        def tree(self, value):
            if isinstance(value, dict):
                return {self.text(k): self.tree(v) for k, v in value.items()}
            return super().tree(value)

    return SecretRedactor.from_environment()


def target_redactor(target):
    """Do not allow inline authentication secrets in monitored target configs."""
    sensitive = re.compile(r"KEY|TOKEN|SECRET|PASSWORD|PASSWD|AUTH|COOKIE", re.I)
    credential_field = re.compile(r"(?:api[_-]?key|access[_-]?token|auth[_-]?token|token|secret|password|passwd|authorization|cookie|credentials)", re.I)
    parsed = urlsplit(target.get("url", ""))
    if parsed.username or parsed.password or any(credential_field.fullmatch(key) for key, _ in parse_qsl(parsed.query)):
        raise ValueError("Monitoring authentication must use environment-backed headers, not URL credentials")
    values = []
    for key, value in target.get("headers", {}).items():
        if sensitive.search(key) and not re.fullmatch(r"(?:(?:Bearer|Basic) )?\$\{[A-Za-z_][A-Za-z_0-9]*\}", value, re.I):
            raise ValueError("Monitoring authentication headers require environment references")
        values.extend(os.environ.get(name, "") for name in re.findall(r"\$\{([A-Za-z_][A-Za-z_0-9]*)\}", value))
    def inspect(value):
        if isinstance(value, dict):
            if any(credential_field.fullmatch(key) for key in value):
                raise ValueError("Monitoring credentials must use environment-backed headers, not request-template fields")
            for item in value.values():
                inspect(item)
        elif isinstance(value, list):
            for item in value:
                inspect(item)
    inspect(target.get("request_template", {}))
    return secret_redactor(values)


class MonitorStorage(Storage):
    """Redact before persistence; the runner still judges original in-memory text."""
    def __init__(self, path, redactor):
        self.redactor = redactor
        super().__init__(path)

    def start_run(self, tests, target_name, suite_path, options):
        clean = [replace(t, prompt=self.redactor.text(t.prompt), checks=self.redactor.tree(t.checks),
                         expected_behavior=self.redactor.text(t.expected_behavior) if t.expected_behavior else None,
                         id=self.redactor.text(t.id), tags=self.redactor.tree(t.tags)) for t in tests]
        return super().start_run(clean, self.redactor.text(target_name), self.redactor.text(suite_path), options)

    def record_attempt(self, test_id, attempt, text, latency_ms, error):
        return super().record_attempt(test_id, attempt, self.redactor.text(text) if text is not None else None,
                                      latency_ms, self.redactor.text(error) if error is not None else None)

    def record_verdict(self, test_id, verdict):
        return super().record_verdict(test_id, Verdict(verdict.passed, self.redactor.text(verdict.reason),
                                                       self.redactor.tree(verdict.checks)))

    def mark_not_run(self, run_id, test_keys, reason):
        return super().mark_not_run(run_id, self.redactor.tree(test_keys), self.redactor.text(reason))


def readonly_storage(path):
    path = Path(path).resolve(strict=True)
    store = Storage.__new__(Storage)
    store.connection = sqlite3.connect(path.as_uri() + "?mode=ro", uri=True, timeout=30)
    store.connection.row_factory = sqlite3.Row
    store.connection.execute("PRAGMA query_only=ON")
    return store


def register_artifact(storage, path, *, run_id, kind, client_id=None, created_at=None):
    if client_id is None:
        owner = storage.connection.execute("SELECT client_id FROM monitor_cycles WHERE run_id=?", (run_id,)).fetchone()
        if owner is None:
            return
        client_id = owner[0]
    path = Path(path).absolute()
    # Do not follow links while recording ownership. Retention rechecks parents.
    if path.is_symlink() or path.is_junction() or not path.is_file():
        raise ValueError("Artifact must be a regular file")
    with storage.connection:
        storage.connection.execute("INSERT INTO monitor_artifacts VALUES (?, ?, ?, ?, ?, ?)",
                                   (str(path), client_id, run_id, kind, created_at or now(),
                                    hashlib.sha256(path.read_bytes()).hexdigest()))
