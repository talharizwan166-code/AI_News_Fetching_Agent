import json
import logging
import urllib.request
import urllib.error

from src.config import LINKEDIN_ACCESS_TOKEN, LINKEDIN_PERSON_URN, LINKEDIN_API_VERSION

logger = logging.getLogger(__name__)


class LinkedInAPIError(ValueError):
    """A publish failure with a safe message and machine-readable HTTP status."""

    def __init__(self, status_code: int, message: str):
        super().__init__(message)
        self.status_code = status_code


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
            "LinkedIn-Version": LINKEDIN_API_VERSION,
            "Content-Type": "application/json",
            "X-Restli-Protocol-Version": "2.0.0",
        },
        method="POST",
    )

    try:
        with urllib.request.urlopen(req, timeout=30) as resp:
            logger.info("Posted to LinkedIn successfully (status %d)", resp.status)
    except urllib.error.HTTPError as exc:
        # Provider response bodies may contain private details; log only the status.
        logger.error("LinkedIn API error (HTTP %d)", exc.code)
        if exc.code == 401:
            raise LinkedInAPIError(401, "LinkedIn token expired or invalid (401). Renew authorization and update the GitHub Secrets.") from exc
        if exc.code == 426:
            raise LinkedInAPIError(426, "LinkedIn API version is no longer supported (426). Set LINKEDIN_API_VERSION to a supported YYYYMM value.") from exc
        raise
    except urllib.error.URLError as exc:
        logger.error("LinkedIn network error: %s", exc)
        raise
