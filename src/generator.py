import logging
import re

from google import genai
from google.genai.errors import ServerError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception

from src.fetcher import Article
from src.config import (
    GEMINI_API_KEY,
    GEMINI_MODEL,
    GEMINI_FALLBACK_MODEL,
    GEMINI_MAX_RETRIES,
    GEMINI_RETRY_WAIT_MIN,
    GEMINI_RETRY_WAIT_MAX,
)

logger = logging.getLogger(__name__)

PROMPT_TEMPLATE = """You are a professional LinkedIn content writer specializing in AI and technology.

Based on the following article, write a concise, engaging LinkedIn post.

Article Title: {title}
Article Source: {source}
Article Summary: {summary}
Article URL: {url}

Requirements:
- Keep it under 280 words
- Professional and informative tone
- Start with a hook that grabs attention
- Include 2-3 key insights from the article
- End with a thought-provoking question or call to action
- Add 3-5 relevant hashtags at the end
- Include the full article URL on its own line near the end (before hashtags)
- Do NOT hallucinate or add facts not present in the article
- Do NOT use excessive emojis

Write the LinkedIn post now:"""

# Retryable error codes
_RETRYABLE_CODES = {429, 500, 502, 503, 504}


def _is_retryable_error(exc: Exception) -> bool:
    """Check if exception is retryable (429, 5xx, ServerError)."""
    if isinstance(exc, ServerError):
        return True
    # Check for HTTP status codes in error message
    err_str = str(exc)
    for code in _RETRYABLE_CODES:
        if str(code) in err_str:
            return True
    return False


def _validate_post(post: str, article_url: str) -> tuple[bool, str]:
    """
    Validate generated LinkedIn post.
    Returns (is_valid, error_message).
    """
    if not post or not post.strip():
        return False, "Empty post"

    # Word count check (≤280 words)
    word_count = len(post.split())
    if word_count > 280:
        return False, f"Post exceeds 280 words ({word_count})"

    # Must contain article URL
    if article_url not in post:
        return False, "Missing article URL"

    # Must have 3-5 hashtags
    hashtags = re.findall(r"#\w+", post)
    if len(hashtags) < 3 or len(hashtags) > 5:
        return False, f"Hashtag count {len(hashtags)} not in 3-5 range"

    return True, ""


def _call_gemini(client: genai.Client, model: str, prompt: str) -> str:
    @retry(
        retry=retry_if_exception(_is_retryable_error),
        stop=stop_after_attempt(GEMINI_MAX_RETRIES),
        wait=wait_exponential(min=GEMINI_RETRY_WAIT_MIN, max=GEMINI_RETRY_WAIT_MAX),
        before_sleep=lambda state: logger.warning(
            "Gemini %s returned retryable error, retrying (attempt %d/%d)...",
            model, state.attempt_number, GEMINI_MAX_RETRIES,
        ),
        reraise=True,
    )
    def _invoke():
        response = client.models.generate_content(model=model, contents=prompt)
        text = response.text
        if not text or not text.strip():
            raise ValueError("Empty response from Gemini")
        return text.strip()

    return _invoke()


def generate_linkedin_post(article: Article) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=GEMINI_API_KEY)

    # Prompt-injection guard: truncate and sanitize article text
    safe_title = article.title[:200]
    safe_source = article.source[:100]
    safe_summary = article.summary[:500]
    safe_url = article.url[:500]

    prompt = PROMPT_TEMPLATE.format(
        title=safe_title,
        source=safe_source,
        summary=safe_summary,
        url=safe_url,
    )

    # Try primary model
    try:
        post = _call_gemini(client, GEMINI_MODEL, prompt)
        valid, err = _validate_post(post, safe_url)
        if valid:
            return post
        logger.warning("Primary model post validation failed: %s. Retrying once...", err)
        # Retry once with same model
        post = _call_gemini(client, GEMINI_MODEL, prompt)
        valid, err = _validate_post(post, safe_url)
        if valid:
            return post
        logger.warning("Primary model retry validation failed: %s. Falling back...", err)
    except Exception as exc:
        logger.warning("Primary model %s failed: %s. Falling back...", GEMINI_MODEL, exc)

    # Try fallback model
    try:
        post = _call_gemini(client, GEMINI_FALLBACK_MODEL, prompt)
        valid, err = _validate_post(post, safe_url)
        if valid:
            return post
        logger.warning("Fallback model post validation failed: %s. Retrying once...", err)
        post = _call_gemini(client, GEMINI_FALLBACK_MODEL, prompt)
        valid, err = _validate_post(post, safe_url)
        if valid:
            return post
        logger.error("Fallback model retry validation failed: %s", err)
    except Exception as exc:
        logger.error("Fallback model %s also failed: %s", GEMINI_FALLBACK_MODEL, exc)
        raise

    raise ValueError("All models failed validation")