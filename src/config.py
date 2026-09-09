import os
from dotenv import load_dotenv

load_dotenv()

RSS_FEEDS = {
    "MIT Technology Review": "https://www.technologyreview.com/feed/",
    "TechCrunch AI": "https://techcrunch.com/category/artificial-intelligence/feed/",
    "The Verge AI": "https://www.theverge.com/rss/ai-artificial-intelligence/index.xml",
    "Ars Technica AI": "https://feeds.arstechnica.com/arstechnica/technology-lab",
    "VentureBeat AI": "https://venturebeat.com/category/ai/feed/",
    "Google AI Blog": "https://blog.google/technology/ai/rss/",
    "OpenAI Blog": "https://openai.com/blog/rss.xml",
}

FETCH_TIMEOUT_SECONDS = 15

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
}

MIN_QUALITY_THRESHOLD = 0.25

GEMINI_API_KEY = os.getenv("GEMINI_API_KEY", "")
GEMINI_MODEL = "gemini-3.6-flash"
GEMINI_FALLBACK_MODEL = "gemini-3.5-flash"

GEMINI_MAX_RETRIES = 3
GEMINI_RETRY_WAIT_MIN = 2
GEMINI_RETRY_WAIT_MAX = 30

EMAIL_SENDER = os.getenv("EMAIL_SENDER", "")
EMAIL_PASSWORD = os.getenv("EMAIL_PASSWORD", "")
EMAIL_RECIPIENT = os.getenv("EMAIL_RECIPIENT", "")
EMAIL_SMTP_HOST = os.getenv("EMAIL_SMTP_HOST", "smtp.gmail.com")
EMAIL_SMTP_PORT = int(os.getenv("EMAIL_SMTP_PORT", "587"))

LINKEDIN_ACCESS_TOKEN = os.getenv("LINKEDIN_ACCESS_TOKEN", "")
LINKEDIN_PERSON_URN = os.getenv("LINKEDIN_PERSON_URN", "")

DB_PATH = os.getenv("DB_PATH", "news_agent.db")
