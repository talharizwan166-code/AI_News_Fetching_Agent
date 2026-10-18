"""At-most-once alert attempts; no prompts or raw responses enter messages."""

from email.message import EmailMessage
import os
import smtplib
import ssl
from urllib.parse import urlsplit

import httpx

from .monitor_store import secret_redactor


def send_email(recipients, text):
    host = os.environ.get("CHATCHECK_SMTP_HOST")
    sender = os.environ.get("CHATCHECK_SMTP_FROM")
    if not host or not sender or any(c in sender for c in "\r\n"):
        raise ValueError("SMTP host and sender environment settings are required")
    message = EmailMessage()
    message["Subject"] = "Chatcheck monitoring alert"
    message["From"] = sender
    message["To"] = ", ".join(recipients)
    message.set_content(text)
    implicit = os.environ.get("CHATCHECK_SMTP_SSL", "false").lower() == "true"
    port = int(os.environ.get("CHATCHECK_SMTP_PORT", "465" if implicit else "587"))
    factory = smtplib.SMTP_SSL if implicit else smtplib.SMTP
    kwargs = {"context": ssl.create_default_context()} if implicit else {}
    with factory(host, port, timeout=20, **kwargs) as smtp:
        if not implicit:
            smtp.starttls(context=ssl.create_default_context())
        user = os.environ.get("CHATCHECK_SMTP_USER")
        if user:
            smtp.login(user, os.environ.get("CHATCHECK_SMTP_PASSWORD", ""))
        smtp.send_message(message, from_addr=sender, to_addrs=recipients)


def send_slack(text):
    webhook = os.environ.get("CHATCHECK_SLACK_WEBHOOK", "")
    parsed = urlsplit(webhook)
    if parsed.scheme != "https" or not parsed.hostname or parsed.username or parsed.password:
        raise ValueError("Slack webhook must be configured as an HTTPS environment value")
    with httpx.Client(timeout=20, trust_env=False, follow_redirects=False) as client:
        response = client.post(webhook, json={"text": text})
        if not 200 <= response.status_code < 300:
            raise ValueError("Slack delivery failed")


def deliver(storage, cycle_id, config, text, *, dry_run=False):
    text = secret_redactor().text(text)
    statuses = {}
    for channel in config["channels"]:
        with storage.connection:
            cursor = storage.connection.execute("INSERT OR IGNORE INTO monitor_alerts VALUES (?, ?, ?)",
                                                (cycle_id, channel, "dry_run" if dry_run else "attempted"))
        if not cursor.rowcount:
            statuses[channel] = "already_attempted"
            continue
        if dry_run:
            print(f"DRY RUN ({channel})\n{text}")
            statuses[channel] = "dry_run"
            continue
        try:
            if channel == "email":
                send_email(config["recipients"], text)
            else:
                send_slack(text)
            status = "sent"
        except Exception:
            # Provider exception strings can contain passwords or webhook URLs.
            status = "failed"
        with storage.connection:
            storage.connection.execute("UPDATE monitor_alerts SET status=? WHERE cycle_id=? AND channel=?",
                                       (status, cycle_id, channel))
        statuses[channel] = status
    return statuses
