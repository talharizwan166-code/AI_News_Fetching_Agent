import logging

from google import genai
from google.genai.errors import ServerError
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

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


def _call_gemini(client: genai.Client, model: str, prompt: str) -> str:
    @retry(
        retry=retry_if_exception_type(ServerError),
        stop=stop_after_attempt(GEMINI_MAX_RETRIES),
        wait=wait_exponential(min=GEMINI_RETRY_WAIT_MIN, max=GEMINI_RETRY_WAIT_MAX),
        before_sleep=lambda state: logger.warning(
            "Gemini %s returned server error, retrying (attempt %d/%d)...",
            model, state.attempt_number, GEMINI_MAX_RETRIES,
        ),
        reraise=True,
    )
    def _invoke():
        response = client.models.generate_content(model=model, contents=prompt)
        return response.text.strip()

    return _invoke()


def generate_linkedin_post(article: Article) -> str:
    if not GEMINI_API_KEY:
        raise ValueError("GEMINI_API_KEY is not set")

    client = genai.Client(api_key=GEMINI_API_KEY)

    prompt = PROMPT_TEMPLATE.format(
        title=article.title,
        source=article.source,
        summary=article.summary,
        url=article.url,
    )

    try:
        return _call_gemini(client, GEMINI_MODEL, prompt)
    except ServerError:
        logger.warning(
            "Primary model %s unavailable after %d retries, falling back to %s",
            GEMINI_MODEL, GEMINI_MAX_RETRIES, GEMINI_FALLBACK_MODEL,
        )

    try:
        return _call_gemini(client, GEMINI_FALLBACK_MODEL, prompt)
    except Exception as exc:
        logger.error("Fallback model %s also failed: %s", GEMINI_FALLBACK_MODEL, exc)
        raise
