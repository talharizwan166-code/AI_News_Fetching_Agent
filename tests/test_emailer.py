import base64
import email
from unittest.mock import patch, MagicMock
from src.fetcher import Article
from src.emailer import send_email
import pytest


def _article():
    return Article(
        title="AI Breakthrough",
        url="https://example.com/article",
        source="TechCrunch AI",
        summary="A major AI discovery.",
        score=0.85,
    )


def _get_html_body(mock_server):
    raw = mock_server.sendmail.call_args[0][2]
    msg = email.message_from_string(raw)
    for part in msg.walk():
        if part.get_content_type() == "text/html":
            payload = part.get_payload()
            return base64.b64decode(payload).decode()
    return ""


@patch("src.emailer.EMAIL_SENDER", "sender@test.com")
@patch("src.emailer.EMAIL_PASSWORD", "password")
@patch("src.emailer.EMAIL_RECIPIENT", "recipient@test.com")
@patch("src.emailer.smtplib.SMTP")
def test_send_email_success(mock_smtp_class):
    mock_server = MagicMock()
    mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
    mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

    send_email(_article(), "Check out this AI news! #AI", "https://github.com/test/issues/1")

    mock_server.starttls.assert_called_once()
    mock_server.login.assert_called_once_with("sender@test.com", "password")
    mock_server.sendmail.assert_called_once()
    args = mock_server.sendmail.call_args[0]
    assert args[0] == "sender@test.com"
    assert args[1] == "recipient@test.com"


@patch("src.emailer.EMAIL_SENDER", "sender@test.com")
@patch("src.emailer.EMAIL_PASSWORD", "password")
@patch("src.emailer.EMAIL_RECIPIENT", "recipient@test.com")
@patch("src.emailer.smtplib.SMTP")
def test_email_contains_approve_button_when_issue_url(mock_smtp_class):
    mock_server = MagicMock()
    mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
    mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

    send_email(_article(), "Post text", "https://github.com/test/issues/1")

    html = _get_html_body(mock_server)
    assert "Review &amp; Approve Post" in html
    assert "https://github.com/test/issues/1" in html


@patch("src.emailer.EMAIL_SENDER", "sender@test.com")
@patch("src.emailer.EMAIL_PASSWORD", "password")
@patch("src.emailer.EMAIL_RECIPIENT", "recipient@test.com")
@patch("src.emailer.smtplib.SMTP")
def test_email_without_issue_url(mock_smtp_class):
    mock_server = MagicMock()
    mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
    mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

    send_email(_article(), "Post text")

    html = _get_html_body(mock_server)
    assert "Review &amp; Approve Post" not in html
    assert "Open LinkedIn Share" in html


@patch("src.emailer.EMAIL_SENDER", "")
@patch("src.emailer.EMAIL_PASSWORD", "password")
@patch("src.emailer.EMAIL_RECIPIENT", "recipient@test.com")
def test_raises_without_credentials():
    with pytest.raises(ValueError, match="Email credentials"):
        send_email(_article(), "Post text")


@patch("src.emailer.EMAIL_SENDER", "sender@test.com")
@patch("src.emailer.EMAIL_PASSWORD", "password")
@patch("src.emailer.EMAIL_RECIPIENT", "recipient@test.com")
@patch("src.emailer.smtplib.SMTP")
def test_email_escapes_html_in_body(mock_smtp_class):
    mock_server = MagicMock()
    mock_smtp_class.return_value.__enter__ = MagicMock(return_value=mock_server)
    mock_smtp_class.return_value.__exit__ = MagicMock(return_value=False)

    article = _article()
    article.title = '<script>alert("xss")</script>'
    send_email(article, "Post text")

    html = _get_html_body(mock_server)
    assert "<script>" not in html
    assert "&lt;script&gt;" in html
