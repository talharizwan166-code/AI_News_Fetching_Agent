from dotenv import load_dotenv

# Re-export the shared helpers here; the pre-dotenv guard imports src.env directly.
from src.env import ConfigError, env_str, env_int, env_float

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

FETCH_TIMEOUT_SECONDS = env_int("FETCH_TIMEOUT_SECONDS", 15)

SCORING_WEIGHTS = {
    "ai_relevance": env_float("SCORING_WEIGHT_AI_RELEVANCE", 0.30),
    "developer_relevance": env_float("SCORING_WEIGHT_DEVELOPER_RELEVANCE", 0.20),
    "innovation": env_float("SCORING_WEIGHT_INNOVATION", 0.20),
    "freshness": env_float("SCORING_WEIGHT_FRESHNESS", 0.15),
    "source_credibility": env_float("SCORING_WEIGHT_SOURCE_CREDIBILITY", 0.15),
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

MIN_QUALITY_THRESHOLD = env_float("MIN_QUALITY_THRESHOLD", 0.25)
MIN_AI_RELEVANCE = env_float("MIN_AI_RELEVANCE", 0.30)

GEMINI_API_KEY = env_str("GEMINI_API_KEY", "")
GEMINI_MODEL = env_str("GEMINI_MODEL", "gemini-3.5-flash")
GEMINI_FALLBACK_MODEL = env_str("GEMINI_FALLBACK_MODEL", "gemini-3.5-flash-lite")

GEMINI_MAX_RETRIES = env_int("GEMINI_MAX_RETRIES", 3)
GEMINI_RETRY_WAIT_MIN = env_int("GEMINI_RETRY_WAIT_MIN", 2)
GEMINI_RETRY_WAIT_MAX = env_int("GEMINI_RETRY_WAIT_MAX", 30)

EMAIL_SENDER = env_str("EMAIL_SENDER", "")
EMAIL_PASSWORD = env_str("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = env_str("EMAIL_RECIPIENT", "")
EMAIL_SMTP_HOST = env_str("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = env_int("EMAIL_SMTP_PORT", 587)

LINKEDIN_ACCESS_TOKEN = env_str("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_URN = env_str("LINKEDIN_PERSON_URN", "")
# Verified 2026-10-15: https://learn.microsoft.com/en-us/linkedin/marketing/versioning
LINKEDIN_API_VERSION = env_str("LINKEDIN_API_VERSION", "202610")

DB_PATH = env_str("DB_PATH", "news_agent.db")


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
        """Validate individual weights and their total without echoing values."""
        for name, value in SCORING_WEIGHTS.items():
            if not 0 <= value <= 1:
                return False, f"SCORING_WEIGHT_{name.upper()} must be between 0 and 1"
        total = sum(SCORING_WEIGHTS.values())
        if abs(total - 1.0) > 0.001:
            return False, "SCORING_WEIGHT_* values must sum to 1.0"
        return True, ""

    @classmethod
    def validate_thresholds(cls) -> tuple[bool, str]:
        """Validate thresholds are in valid range."""
        if not 0 <= MIN_QUALITY_THRESHOLD <= 1:
            return False, "MIN_QUALITY_THRESHOLD must be between 0 and 1"
        if not 0 <= MIN_AI_RELEVANCE <= 1:
            return False, "MIN_AI_RELEVANCE must be between 0 and 1"
        return True, ""

    @classmethod
    def validate_runtime(cls) -> tuple[bool, str]:
        """Reject unusable timeout, SMTP port and retry settings before network I/O."""
        errors = []
        if FETCH_TIMEOUT_SECONDS <= 0:
            errors.append("FETCH_TIMEOUT_SECONDS must be positive")
        if not 1 <= EMAIL_SMTP_PORT <= 65535:
            errors.append("EMAIL_SMTP_PORT must be between 1 and 65535")
        if GEMINI_MAX_RETRIES < 1:
            errors.append("GEMINI_MAX_RETRIES must be at least 1")
        if GEMINI_RETRY_WAIT_MIN < 0 or GEMINI_RETRY_WAIT_MAX < GEMINI_RETRY_WAIT_MIN:
            errors.append("GEMINI_RETRY_WAIT_MIN and GEMINI_RETRY_WAIT_MAX must satisfy 0 <= min <= max")
        return not errors, "; ".join(errors)


config = Config()
