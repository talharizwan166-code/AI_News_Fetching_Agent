"""Suite hashes, held-out exceptions and explicitly human-reviewed main revisions."""

import hashlib
import json
import os
import sqlite3
import uuid
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path, PureWindowsPath


def digest(value):
    return hashlib.sha256(json.dumps(value, ensure_ascii=True, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def guard_path(path):
    return Path(str(path) + ".freeze.json")


def snapshot(data):
    from .models import parse_suite
    cases = parse_suite(data)
    checks = {case.id: case.checks for case in cases}
    return {"suite_sha256": digest(data), "checks_sha256": digest(checks), "checks": checks}


def read_guard(path):
    from .models import read_json
    guard = read_json(guard_path(path))
    if (guard.get("version") != 1 or guard.get("role") not in {"main", "heldout"}
            or not guard.get("history") or digest(guard.get("checks")) != guard.get("checks_sha256")):
        raise ValueError("Invalid suite freeze record; restore its audited version")
    return guard


def verify_suite(path, data=None):
    if not guard_path(path).exists():
        return
    from .models import read_json
    guard = read_guard(path)
    current = snapshot(read_json(path) if data is None else data)
    if current["suite_sha256"] == guard["suite_sha256"]:
        return
    if guard["role"] == "main":
        raise ValueError("Main suite changed without a reviewed changelog entry. Restore the file and use chatcheck revise with a human-reviewed false failure.")
    kind = "checks" if current["checks_sha256"] != guard["checks_sha256"] else "definition"
    raise ValueError(f"Frozen held-out suite {kind} changed. Restore the file, or explicitly record an exception: chatcheck freeze --suite <file> --unfreeze \"reason\". Held-out results must not guide tuning.")


@contextmanager
def locked(path):
    lock = Path(str(guard_path(path)) + ".lock")
    try:
        stream = lock.open("x", encoding="utf-8")
    except FileExistsError:
        raise ValueError("Suite governance is busy; do not edit while another freeze/revision is active") from None
    stream.close()
    try:
        yield
    finally:
        lock.unlink()


def atomic_json(path, value):
    path = Path(path)
    temporary = path.with_name(path.name + "." + uuid.uuid4().hex + ".tmp")
    try:
        with temporary.open("x", encoding="utf-8", newline="\n") as stream:
            json.dump(value, stream, ensure_ascii=False, indent=2)
            stream.write("\n")
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def changes(old, new, reason, date):
    return [{"test_id": key, "old_check": old.get(key), "new_check": new.get(key), "reason": reason, "date": date}
            for key in sorted(old.keys() | new.keys()) if old.get(key) != new.get(key)]


def freeze_suite(path, *, role=None, unfreeze=None):
    from .models import parse_suite, read_json
    if unfreeze is not None and not unfreeze.strip():
        raise ValueError("--unfreeze requires a nonempty reason")
    path = Path(path)
    with locked(path):
        data = read_json(path)
        current = snapshot(data)
        date = datetime.now(timezone.utc).isoformat()
        if guard_path(path).exists():
            guard = read_guard(path)
            if role is not None and role != guard["role"]:
                raise ValueError("A recorded suite role cannot be changed; preserve the held-out audit")
            if unfreeze is None:
                verify_suite(path, data)
                return guard
            if guard["role"] == "main" and current["checks_sha256"] != guard["checks_sha256"]:
                raise ValueError("Main check revisions require chatcheck revise and an explicit human pass label on a failed rule; --unfreeze cannot bypass review")
            revisions = changes(guard["checks"], current["checks"], unfreeze.strip(), date)
            guard["changelog"].extend(revisions)
            guard["history"].append({"action": "unfreeze_refreeze", "reason": unfreeze.strip(), "date": date,
                                     "previous_sha256": guard["suite_sha256"], "suite_sha256": current["suite_sha256"],
                                     "changed_test_ids": [row["test_id"] for row in revisions]})
            guard.update(current)
        else:
            if unfreeze is not None:
                raise ValueError("No freeze exists to unfreeze; register the original suite first")
            role = role or "heldout"
            if role not in {"main", "heldout"}:
                raise ValueError("Suite role must be main or heldout")
            cases = parse_suite(data)
            if role == "main" and (any(word in path.stem.lower() for word in ("heldout", "held-out"))
                                   or any(set(case.tags) & {"heldout", "held-out"} for case in cases)):
                raise ValueError("A held-out suite cannot be registered as main")
            guard = {"version": 1, "role": role, **current, "changelog": [],
                     "history": [{"action": "freeze", "date": date, "suite_sha256": current["suite_sha256"]}]}
        atomic_json(guard_path(path), guard)
        return guard


def revise_checks(path, test_id, checks, *, reason, review_db, review_run):
    from .judge import validate_checks
    from .models import read_json
    if not reason.strip():
        raise ValueError("A revision reason is required")
    validate_checks(checks)
    path = Path(path)
    with locked(path):
        if not guard_path(path).exists() or read_guard(path)["role"] != "main":
            raise ValueError("Check revisions require a registered MAIN suite; held-out tuning is prohibited")
        verify_suite(path)
        guard = read_guard(path)
        data = read_json(path)
        rows = data["tests"] if isinstance(data, dict) else data
        row = next((item for index, item in enumerate(rows, 1) if item.get("id", str(index)) == test_id), None)
        if row is None:
            raise ValueError("Revision test ID not found")
        if any(check not in checks for check in row["checks"] if check["type"] == "not_contains"):
            raise ValueError("Exact forbidden-content checks must remain unchanged; phrase normalization cannot relax leakage guards")
        with sqlite3.connect(Path(review_db).resolve().as_uri() + "?mode=ro", uri=True) as db:
            db.row_factory = sqlite3.Row
            review = db.execute("""
                SELECT t.prompt, t.checks_json, t.tags_json, s.suite_path, v.passed, h.label, h.updated_at, a.id AS response_id, a.text, a.error
                FROM tests t JOIN runs s ON s.id=t.run_id JOIN verdicts v ON v.test_id=t.id JOIN human_labels h ON h.test_id=t.id
                JOIN responses a ON a.test_id=t.id AND a.attempt=(SELECT MAX(attempt) FROM responses WHERE test_id=t.id)
                WHERE t.run_id=? AND t.test_key=?
            """, (review_run, test_id)).fetchone()
        if (review is None or review["label"] != "pass" or review["passed"]
                or not review["text"] or review["error"] or review["prompt"] != row["prompt"]
                or PureWindowsPath(review["suite_path"]).name != path.name
                or any(word in review["suite_path"].casefold() for word in ("heldout", "held-out"))
                or set(json.loads(review["tags_json"])) & {"heldout", "held-out"}
                or json.loads(review["checks_json"]) != row["checks"]):
            raise ValueError("Revision requires a saved response with a failed rule and an explicit human pass label on these exact original checks and prompt")
        if row["checks"] == checks:
            raise ValueError("New checks equal the existing checks; no revision was made")
        date = datetime.now(timezone.utc).isoformat()
        entry = {"test_id": test_id, "old_check": row["checks"], "new_check": checks, "reason": reason.strip(), "date": date,
                 "review": {"run_id": review_run, "response_id": review["response_id"], "human_label": "pass",
                            "label_updated_at": review["updated_at"], "database": Path(review_db).name}}
        row["checks"] = checks
        current = snapshot(data)
        guard["changelog"].append(entry)
        guard["history"].append({"action": "main_revision", "date": date, "reason": reason.strip(),
                                 "previous_sha256": guard["suite_sha256"], "suite_sha256": current["suite_sha256"], "test_id": test_id})
        guard.update(current)
        # If interrupted between these atomic writes, verification fails closed.
        atomic_json(path, data)
        atomic_json(guard_path(path), guard)
        return entry
