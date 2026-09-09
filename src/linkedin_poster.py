import json
import logging
import urllib.request
import urllib.error

from src.config import LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN

logger = logging.getLogger(__name__)


def post_to_linkedin(
    text: str,
    article_url: str = "",
    article_title: str = "",
) -> None:
    if not LINKEDIN_ACCESS_TOKEN or not LINKEDIN_PERSON_URN:
        raise ValueError(
            "LinkedIn secrets not configured. Add LINKEDIN_ACCESS_TOKEN and "
            "LINKEDIN_PERSON_URN to your GitHub repo secrets. See README for setup steps."
        )

    url = "https://api.linkedin.com/rest/posts"
    data = {
        "author": LINKEDIN_PERSON_URN,
        "commentary": text,
        "visibility": "PUBLIC",
        "distribution": {
            "feedDistribution": "MAIN_FEED",
            "targetEntities": [],
            "thirdPartyDistributionChannels": [],
        },
        "lifecycleState": "PUBLISHED",
        "isReshareDisabledByAuthor": False,
    }

    if article_url:
        data["content"] = {
            "article": {
                "source": article_url,
                "title": article_title or article_url,
            }
        }

    req = urllib.request.Request(
        url,
        data=json.dumps(data).encode(),
        headers={
            "Authorization": f"Bearer {LINKEDIN_ACCESS_TOKEN}",
            "LinkedIn-Version": "202401",
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req) as resp:
            logger.info("Posted to LinkedIn successfully (status %d)", resp.status)
    except urllib.error.HTTPError as exc:
        body = exc.read().decode()
        logger.error("LinkedIn API error %d: %s", exc.code, body)
        raise
