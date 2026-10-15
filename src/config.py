import os
from dotenv import load_dotenv

load_dotenv()

RSS_FEEDS = {
    "MIT Technology Review": "https://www.technologyreview.com/feed/",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Ars Technica AI": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",  # Often rate-limited (429)
    "Google AI Blog": "https://blog.google/technology/ai/rss/",
    "OpenAI Blog": "https://openai.com/blog/rss.xml",
    "AI Weekly": "https://aiweekly.co/rss/",
    "KDnuggets AI": "https://www.kdnuggets.com/feed",
}

FETCH_TIMEOUT_SECONDS = int(os.getenv("FETCH_TIMEOUT_SECONDS", "15"))

SCORING_WEIGHTS = {
    "ai_relevance": 0.30,
    "developer_relevance": 0.20,
    "innovation": 0.20,
    "freshness": 0.15,
    "source_credibility": 0.15,
}

SOURCE_CREDIBILITY = {
    "MIT Technology Review": 0.95,
    "TechCrunch AI": 0.85,
    "The Verge AI": 0.80,
    "Ars Technica AI": 0.90,
    "VentureBeat AI": 0.80,
    "Google AI Blog": 0.90,
    "OpenAI Blog": 0.90,
    "AI Weekly": 0.85,
    "KDnuggets AI": 0.85,
}

MIN_QUALITY_THRESHOLD = float(os.getenv("MIN_QUALITY_THRESHOLD", "0.25"))
MIN_AI_RELEVANCE = float(os.getenv("MIN_AI_RELEVANCE", "0.30"))

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = os.getenv("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_FALLBACK_MODEL = os.getenv("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")

GEMINI_MAX_RETRIES = int(os.getenv("GEMINI_MAX_RETRIES", "3"))
GEMINI_RETRY_WAIT_MIN = int(os.getenv("GEMINI_RETRY_WAIT_MIN", "2"))
GEMINI_RETRY_WAIT_MAX = int(os.getenv("GEMINI_RETRY_WAIT_MAX", "30"))

EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))

LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_URN = os.getenv("LINKEDIN_PERSON_URN", "")
# Verified 2026-10-15: https://learn.microsoft.com/en-us/linkedin/marketing/versioning
LINKEDIN_API_VERSION = os.getenv("LINKEDIN_API_VERSION", "202610")

DB_PATH = os.getenv("DB_PATH", "news_agent.db")


class Config:
    """Configuration validator."""

    REQUIRED_VARS = {
        "GEMINI_API_KEY": GEMINI_API_KEY,
        "EMAIL_SENDER": EMAIL_SENDER,
        "EMAIL_PASSWORD": EMAIL_PASSWORD,
        "EMAIL_RECIPIENT": EMAIL_RECIPIENT,
    }

    @classmethod
    def validate(cls) -> tuple[bool, list[str]]:
        """Validate all required config. Returns (is_valid, missing_vars)."""
        missing = [name for name, value in cls.REQUIRED_VARS.items() if not value]
        return (len(missing) == 0, missing)

    @classmethod
    def validate_scoring_weights(cls) -> tuple[bool, str]:
        """Validate scoring weights sum to 1.0."""
        total = sum(SCORING_WEIGHTS.values())
        if abs(total - 1.0) > 0.001:
            return False, f"Scoring weights sum to {total:.3f}, expected 1.0"
        return True, ""

    @classmethod
    def validate_thresholds(cls) -> tuple[bool, str]:
        """Validate thresholds are in valid range."""
        if not 0 <= MIN_QUALITY_THRESHOLD <= 1:
            return False, f"MIN_QUALITY_THRESHOLD must be 0-1, got {MIN_QUALITY_THRESHOLD}"
        if not 0 <= MIN_AI_RELEVANCE <= 1:
            return False, f"MIN_AI_RELEVANCE must be 0-1, got {MIN_AI_RELEVANCE}"
        return True, ""


config = Config()
