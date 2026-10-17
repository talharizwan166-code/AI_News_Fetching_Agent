"""Craft bytes before parsing: encodings and malformed feeds are real inputs."""

from xml.sax.saxutils import escape

TITLE = "New open-source AI machine learning model API for developers"
SUMMARY = "Artificial intelligence research releases an open-source neural network SDK and benchmark for developers."
ARTICLE_URL = "https://example.invalid/ai-news"


def feed_bytes(case):
    kind = case.get("feed", "normal")
    if kind == "broken":
        return b"<rss><channel><item><title>"
    if kind == "empty":
        return b"<rss version='2.0'><channel><title>Empty</title></channel></rss>"
    title = case.get("title", TITLE)
    summary = case.get("article", SUMMARY)
    if kind == "huge":
        summary += " AI research" * 100_000
    if kind == "non_utf8":
        summary += " caf\u00e9 intelligence"
    url = case.get("article_url", ARTICLE_URL)
    item = (f"<item><title>{escape(title)}</title><link>{escape(url)}</link>"
            f"<description>{escape(summary)}</description><pubDate>Sat, 17 Oct 2026 05:00:00 GMT</pubDate></item>")
    encoding = "iso-8859-1" if kind == "non_utf8" else "utf-8"
    count = 8 if kind == "duplicates" else 1
    return (f'<?xml version="1.0" encoding="{encoding}"?><rss version="2.0"><channel><title>AI</title>'
            + item * count + "</channel></rss>").encode(encoding)


def validate_case(case):
    if not isinstance(case, dict):
        raise ValueError("Scenario prompt must contain a JSON object")
    allowed = {"feed", "title", "article", "article_url", "comment", "association", "pending",
               "llm", "max_calls", "max_tokens", "max_steps", "repeat", "issue_error", "feed_url"}
    if set(case) - allowed:
        raise ValueError("Unknown sandbox scenario field")
    for name, upper in (("max_calls", 12), ("max_tokens", 100000), ("max_steps", 100), ("repeat", 2)):
        if name in case and (type(case[name]) is not int or not 1 <= case[name] <= upper):
            raise ValueError(f"Invalid sandbox {name}")
    for name in ("pending", "issue_error"):
        if name in case and type(case[name]) is not bool:
            raise ValueError(f"Invalid sandbox {name}")
    for name in ("title", "article", "article_url", "comment", "association", "feed_url"):
        if name in case and (not isinstance(case[name], str) or len(case[name]) > 20000):
            raise ValueError(f"Invalid sandbox {name}")
    if case.get("feed", "normal") not in {"normal", "empty", "broken", "huge", "non_utf8", "duplicates", "redirect"}:
        raise ValueError("Unknown feed fixture")
    if case.get("llm", "safe") not in {"safe", "echo_marker", "leak_prompt", "invalid", "error", "invalid_once"}:
        raise ValueError("Unknown fake LLM mode")
    return case
