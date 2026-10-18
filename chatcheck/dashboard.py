"""Read-only Streamlit dashboard. Importing this module never opens a database."""

import hashlib
import hmac
import os
from pathlib import Path

from chatcheck.monitor import detect, metrics, previous_runs
from chatcheck.monitor_store import readonly_storage, secret_redactor
from chatcheck.scoring import has_response, outcome


def require_password():
    password = os.environ.get("CHATCHECK_DASHBOARD_PASSWORD", "")
    if not password.strip():
        raise ValueError("Dashboard refused: CHATCHECK_DASHBOARD_PASSWORD is not set")
    return password


def password_matches(candidate, password):
    return hmac.compare_digest(candidate.encode("utf-8"), password.encode("utf-8"))


def snapshot(db):
    redactor = secret_redactor()
    targets = []
    with readonly_storage(db) as storage:
        pairs = storage.connection.execute("SELECT DISTINCT client_id, target_id FROM monitor_cycles ORDER BY client_id, target_id").fetchall()
        for client, target in pairs:
            runs = previous_runs(storage, client, target)
            if not runs:
                continue
            latest = runs[-1]
            changes = detect(latest, runs[-2] if len(runs) > 1 else None, score_drop_threshold=100, error_rate_threshold=100)
            details = []
            for test in latest["tests"]:
                available = has_response(test)
                if not available or outcome(test) == "fail":
                    response = test["responses"][-1] if test["responses"] else {}
                    details.append({"test": test["test_key"], "kind": "model check failure" if available else "availability / not run",
                                    "reason": redactor.text(test["verdict"]["reason"] if test["verdict"] else "Not attempted")[:600],
                                    "evidence": redactor.text(response.get("text") or "")[:2000] if available else "No usable response"})
            targets.append({"client": client, "target": target, "changes": changes, "details": details,
                            "trend": [{"date": run["started_at"], **metrics(run)} for run in runs]})
    return redactor.tree(targets)


def app():
    password = require_password()  # Refuse before importing Streamlit or reading data.
    import streamlit as st
    st.set_page_config(page_title="Chatcheck monitoring", layout="wide")
    # HMAC binds authentication to the current password without retaining it.
    session_token = hmac.new(password.encode(), b"chatcheck-dashboard-session", hashlib.sha256).hexdigest()
    if not hmac.compare_digest(st.session_state.get("authenticated", ""), session_token):
        def authenticate():
            candidate = st.session_state.pop("password_input", "")
            if password_matches(candidate, password):
                st.session_state["authenticated"] = session_token
        st.text_input("Dashboard password", type="password", key="password_input", on_change=authenticate)
        st.stop()
    st.title("Chatcheck monitoring")
    st.caption("Read-only. Connector errors describe availability, not model failures.")
    db = os.environ.get("CHATCHECK_DASHBOARD_DB", "chatcheck.db")
    try:
        data = snapshot(db)
    except Exception:
        st.error("Monitoring data is unavailable. Check the configured database.")
        st.stop()
    if not data:
        st.info("No completed monitoring cycles.")
        return
    index = st.selectbox("Target", range(len(data)), format_func=lambda i: data[i]["client"] + " / " + data[i]["target"])
    selected = data[index]
    st.line_chart(selected["trend"], x="date", y=["score", "availability"])
    st.dataframe(selected["trend"])
    st.write("Newly failing tests", selected["changes"]["newly_failing"])
    st.write("Newly fixed tests", selected["changes"]["newly_fixed"])
    st.dataframe(selected["details"])


def launch():
    require_password()  # A missing password must prevent the server from starting.
    import subprocess
    import sys
    return subprocess.call([sys.executable, "-m", "streamlit", "run", str(Path(__file__).resolve()),
                            "--server.address=127.0.0.1", "--server.headless=true", "--browser.gatherUsageStats=false"])


if __name__ == "__main__":
    app()
