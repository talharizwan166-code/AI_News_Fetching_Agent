"""Client-owned retention inventory; dry-run by default and no wildcard deletion."""

from datetime import datetime, timedelta, timezone
import hashlib
import html
import json
from pathlib import Path
import re

from .models import read_json
from .monitor_store import readonly_storage, secret_redactor
from .storage import Storage


def load_policy(path):
    path = Path(path).resolve()
    policy = read_json(path)
    if not isinstance(policy, dict) or set(policy) != {"clients"} or not isinstance(policy["clients"], list) or not policy["clients"]:
        raise ValueError("Retention policy requires a nonempty clients list")
    seen = set()
    for row in policy["clients"]:
        if (not isinstance(row, dict) or set(row) != {"client_id", "days", "reports_dir"}
                or not isinstance(row["client_id"], str) or not re.fullmatch(r"[A-Za-z0-9_-]{1,64}", row["client_id"])
                or row["client_id"] in seen or type(row["days"]) is not int or not 0 <= row["days"] <= 36500
                or not isinstance(row["reports_dir"], str) or not row["reports_dir"]):
            raise ValueError("Each retention client needs a unique ID, days from 0 to 36500, and reports_dir")
        seen.add(row["client_id"])
        row["reports_dir"] = str((path.parent / row["reports_dir"]).absolute())
    return policy


def permitted_file(path, root, expected_hash):
    """Validate absolute containment and every symlink/junction before unlinking."""
    path, root = Path(path).absolute(), Path(root).absolute()
    if root.resolve() == Path(root.anchor) or path == root or path.suffix.lower() not in {".html", ".htm", ".pdf", ".json"}:
        return False, "unsupported path"
    for part in (root, *root.parents, path, *path.parents):
        if part.is_symlink() or part.is_junction():
            return False, "symlink or junction"
    if not path.resolve().is_relative_to(root.resolve()):
        return False, "outside configured reports directory"
    if not path.exists():
        return True, "already absent"
    if not path.is_file() or hashlib.sha256(path.read_bytes()).hexdigest() != expected_hash:
        return False, "file changed since registration"
    return True, "eligible"


def inventory(storage, policy, timestamp):
    results = []
    for client in policy["clients"]:
        cutoff = (timestamp - timedelta(days=client["days"])).isoformat()
        runs = [dict(row) for row in storage.connection.execute(
            "SELECT DISTINCT r.id, r.started_at, r.finished_at FROM runs r JOIN monitor_cycles m ON m.run_id=r.id "
            "WHERE m.client_id=? AND r.status!='running' AND julianday(r.finished_at)<julianday(?) "
            "AND NOT EXISTS (SELECT 1 FROM monitor_cycles other WHERE other.run_id=r.id AND other.client_id!=?) ORDER BY r.started_at",
            (client["client_id"], cutoff, client["client_id"]))]
        files = []
        for row in storage.connection.execute(
                "SELECT * FROM monitor_artifacts WHERE client_id=? AND julianday(created_at)<julianday(?) ORDER BY path",
                (client["client_id"], cutoff)):
            allowed, reason = permitted_file(row["path"], client["reports_dir"], row["sha256"])
            files.append({**dict(row), "eligible": allowed, "reason": reason})
        results.append({**client, "cutoff": cutoff, "runs": runs, "files": files})
    return results


def retain(policy, db, *, yes=False, clock=None):
    timestamp = (clock or (lambda: datetime.now(timezone.utc)))().astimezone(timezone.utc)
    # Even the default inventory uses SQLite read-only mode: no migrations/writes.
    with readonly_storage(db) as storage:
        clients = inventory(storage, policy, timestamp)
    deleted_runs, deleted_files = [], []
    if yes:
        with Storage(db) as storage:
            # Re-evaluate after acquiring the write-capable connection.
            clients = inventory(storage, policy, timestamp)
            for client in clients:
                for file in client["files"]:
                    allowed, reason = permitted_file(file["path"], client["reports_dir"], file["sha256"])
                    if not allowed:
                        file.update(eligible=False, reason=reason)
                        continue
                    Path(file["path"]).unlink(missing_ok=True)
                    with storage.connection:
                        storage.connection.execute("DELETE FROM monitor_artifacts WHERE path=?", (file["path"],))
                    deleted_files.append(file["path"])
                for run in client["runs"]:
                    cycles = [row[0] for row in storage.connection.execute("SELECT id FROM monitor_cycles WHERE run_id=?", (run["id"],))]
                    storage.purge(run_id=run["id"], confirmed=True)
                    with storage.connection:
                        storage.connection.executemany("UPDATE monitor_cycles SET summary_json=NULL, schedule='', report_root='', config_hash='' WHERE id=?",
                                                       [(cycle_id,) for cycle_id in cycles])
                    deleted_runs.append(run["id"])
    return secret_redactor().tree({"as_of": timestamp.isoformat(), "dry_run": not yes, "clients": clients,
                                  "deleted_runs": deleted_runs, "deleted_files": deleted_files,
                                  "limits": "Only owned monitoring runs and registered files. Backups, provider logs and unregistered copies are outside this inventory. Idempotency metadata remains."})


def write_inventory(result, output):
    # A client-readable report with no chatbot content. Never overwrite an export.
    text = json.dumps(secret_redactor().tree(result), indent=2)
    with Path(output).open("x", encoding="utf-8") as stream:
        if Path(output).suffix.lower() == ".html":
            safe = secret_redactor().tree(result)
            escape = lambda value: html.escape(str(value))
            sections = []
            for client in safe["clients"]:
                run_rows = "".join("<tr><td>" + escape(row["id"]) + "</td><td>" + escape(row["finished_at"]) + "</td></tr>" for row in client["runs"])
                file_rows = "".join("<tr><td>" + escape(row["kind"]) + "</td><td>" + escape(row["path"]) + "</td><td>" + escape(row["reason"]) + "</td></tr>" for row in client["files"])
                sections.append(f"<section><h2>{escape(client['client_id'])}</h2><p>Retention: {client['days']} days. Cutoff: {escape(client['cutoff'])}.</p>"
                                f"<p>{len(client['runs'])} eligible runs; {sum(f['eligible'] for f in client['files'])} eligible registered files; {sum(not f['eligible'] for f in client['files'])} files blocked from deletion.</p>"
                                "<h3>Old runs</h3><table><tr><th>Run ID</th><th>Finished (UTC)</th></tr>" + run_rows + "</table>"
                                "<h3>Reports and exports</h3><table><tr><th>Type</th><th>Path</th><th>Disposition</th></tr>" + file_rows + "</table></section>")
            stream.write('<!doctype html><html><head><meta charset="utf-8"><title>Client data retention</title>'
                         '<meta http-equiv="Content-Security-Policy" content="default-src \'none\'; style-src \'unsafe-inline\'">'
                         '<style>body{font:16px/1.5 sans-serif;max-width:1100px;margin:40px auto;padding:20px;color:#173042}table{width:100%;border-collapse:collapse;table-layout:fixed}td,th{text-align:left;border-bottom:1px solid #ccc;padding:10px;overflow-wrap:anywhere}section{margin:30px 0}</style></head><body>'
                         '<h1>Client data-retention report</h1><p>' + ("Dry-run inventory — no data was deleted." if safe["dry_run"] else "Deletion receipt")
                         + f"</p><p>As of {escape(safe['as_of'])}. Deleted: {len(safe['deleted_runs'])} runs and {len(safe['deleted_files'])} registered files.</p>"
                         + "".join(sections) + "<h2>Scope and limits</h2><p>" + escape(safe["limits"]) + "</p></body></html>")
        else:
            stream.write(text + "\n")
