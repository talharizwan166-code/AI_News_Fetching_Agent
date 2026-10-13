import html as html_lib
import logging
import smtplib
import socket
import time
from email.mime.text import MIMEText
from email.mime.multipart import MIMEMultipart
from email.utils import formataddr, make_msgid
from urllib.parse import quote

from src.fetcher import Article
from src.config import (
    EMAIL_SENDER,
    EMAIL_PASSWORD,
    EMAIL_RECIPIENT,
    EMAIL_SMTP_HOST,
    EMAIL_SMTP_PORT,
)

logger = logging.getLogger(__name__)

# SMTP retry configuration
SMTP_MAX_RETRIES = 3
SMTP_RETRY_DELAY_SECONDS = 5


def _create_message(article: Article, linkedin_post: str, issue_url: str = "") -> MIMEMultipart:
    """Create the email message with proper headers for deliverability."""
    linkedin_share_url = (
        "https://www.linkedin.com/sharing/share-offsite/?url="
        + quote(article.url, safe="")
    )

    safe_title = html_lib.escape(article.title)
    safe_source = html_lib.escape(article.source)
    safe_url = html_lib.escape(article.url)
    safe_linkedin_url = html_lib.escape(linkedin_share_url)
    safe_issue_url = html_lib.escape(issue_url) if issue_url else ""
    safe_post = html_lib.escape(linkedin_post)

    msg = MIMEMultipart("alternative")
    msg["Subject"] = f"AI News Agent: {article.title}"
    msg["From"] = formataddr(("AI News Agent", EMAIL_SENDER))
    msg["To"] = EMAIL_RECIPIENT
    msg["Message-ID"] = make_msgid(domain=EMAIL_SENDER.split("@")[-1])
    msg["Auto-Submitted"] = "auto-generated"
    msg["Precedence"] = "bulk"

    approve_text = ""
    if issue_url:
        approve_text = (
            f"\n--- Approve or Reject ---\n"
            f"To auto-post to LinkedIn, comment 'approve' on this issue:\n"
            f"{issue_url}\n"
            f"To skip, comment 'reject'.\n"
        )

    body = f"""AI News Agent — Daily Pick

Article: {article.title}
Source: {article.source}
URL: {article.url}
Score: {article.score}

--- Generated LinkedIn Post ---

{linkedin_post}
{approve_text}
--- Or share manually ---
1. Copy the post text above
2. Open LinkedIn: {linkedin_share_url}
3. Paste the text and share!

---
This email was sent automatically by AI News Agent.
"""

    approve_html = ""
    if safe_issue_url:
        approve_html = f"""<hr>
<h3>Auto-Post to LinkedIn</h3>
<p style="color:#555; margin-bottom:16px;">Click below to review. Comment <b>approve</b> to post automatically, or <b>reject</b> to skip.</p>
<div style="text-align:center; margin:24px 0;">
  <a href="{safe_issue_url}" target="_blank"
     style="display:inline-block; background:#28a745; color:#ffffff;
            padding:14px 32px; border-radius:6px; text-decoration:none;
            font-size:16px; font-weight:bold;">
    Review & Approve Post
  </a>
</div>"""

    html = f"""<html><body>
<h2>AI News Agent — Daily Pick</h2>
<table style="border-collapse:collapse;">
  <tr><td><b>Article:</b></td><td>{safe_title}</td></tr>
  <tr><td><b>Source:</b></td><td>{safe_source}</td></tr>
  <tr><td><b>URL:</b></td><td><a href="{safe_url}">{safe_url}</a></td></tr>
  <tr><td><b>Score:</b></td><td>{article.score}</td></tr>
</table>
<hr>
<h3>Generated LinkedIn Post</h3>
<div style="white-space:pre-wrap; background:#f0f7ff; padding:16px; border-radius:8px;
            border:2px solid #0A66C2; font-size:14px; line-height:1.5;">
{safe_post}
</div>
{approve_html}
<hr>
<h3>Or Share Manually</h3>
<p style="color:#555;">Copy the post text above, then click below to open LinkedIn.</p>
<div style="text-align:center; margin:16px 0;">
  <a href="{safe_linkedin_url}" target="_blank"
     style="display:inline-block; background:#0A66C2; color:#ffffff;
            padding:10px 24px; border-radius:6px; text-decoration:none;
            font-size:14px;">
    Open LinkedIn Share
  </a>
</div>
<hr>
<p style="color:#888; font-size:12px;">Sent automatically by AI News Agent.</p>
</body></html>"""

    msg.attach(MIMEText(body, "plain", "utf-8"))
    msg.attach(MIMEText(html, "html", "utf-8"))
    return msg


def _send_with_retry(msg: MIMEMultipart) -> None:
    """Send email with retry logic for transient failures."""
    last_exception = None

    for attempt in range(1, SMTP_MAX_RETRIES + 1):
        try:
            with smtplib.SMTP(EMAIL_SMTP_HOST, EMAIL_SMTP_PORT, timeout=30) as server:
                server.set_debuglevel(0)
                server.ehlo()
                server.starttls()
                server.ehlo()
                server.login(EMAIL_SENDER, EMAIL_PASSWORD)
                server.sendmail(EMAIL_SENDER, EMAIL_RECIPIENT, msg.as_string())
            logger.info("Email sent successfully to %s (attempt %d/%d)", EMAIL_RECIPIENT, attempt, SMTP_MAX_RETRIES)
            return
        except (smtplib.SMTPAuthenticationError, smtplib.SMTPRecipientsRefused) as exc:
            # These are permanent failures - don't retry
            logger.error("Permanent SMTP error (no retry): %s", exc)
            raise
        except (smtplib.SMTPServerDisconnected, smtplib.SMTPConnectError, socket.timeout, socket.gaierror, OSError) as exc:
            # These are transient - retry
            last_exception = exc
            logger.warning("Transient SMTP error on attempt %d/%d: %s", attempt, SMTP_MAX_RETRIES, exc)
            if attempt < SMTP_MAX_RETRIES:
                time.sleep(SMTP_RETRY_DELAY_SECONDS * attempt)  # Exponential backoff
        except smtplib.SMTPException as exc:
            # Other SMTP errors - log and retry
            last_exception = exc
            logger.warning("SMTP error on attempt %d/%d: %s", attempt, SMTP_MAX_RETRIES, exc)
            if attempt < SMTP_MAX_RETRIES:
                time.sleep(SMTP_RETRY_DELAY_SECONDS * attempt)

    # All retries exhausted
    logger.error("Failed to send email after %d attempts. Last error: %s", SMTP_MAX_RETRIES, last_exception)
    raise last_exception


def send_email(article: Article, linkedin_post: str, issue_url: str = "") -> None:
    """Send email with retry logic and improved deliverability."""
    if not all([EMAIL_SENDER, EMAIL_PASSWORD, EMAIL_RECIPIENT]):
        raise ValueError("Email credentials are not fully configured")

    msg = _create_message(article, linkedin_post, issue_url)
    _send_with_retry(msg)