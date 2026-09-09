import json
import logging
import os
import urllib.request
import urllib.error

logger = logging.getLogger(__name__)

GITHUB_TOKEN = os.getenv("GITHUB_TOKEN", "")
GITHUB_REPOSITORY = os.getenv("GITHUB_REPOSITORY", "")

_API_BASE = "https://api.github.com"


def _github_request(method: str, path: str, data: dict | None = None) -> dict:
    url = f"{_API_BASE}{path}"
    body = json.dumps(data).encode() if data else None

    req = urllib.request.Request(
        url,
        data=body,
        headers={
            "Authorization": f"Bearer {GITHUB_TOKEN}",
            "Accept": "application/vnd.github+json",
            "Content-Type": "application/json",
        },
        method=method,
    )

    with urllib.request.urlopen(req) as resp:
        return json.loads(resp.read())


def _ensure_label_exists(name: str, color: str = "FFA500") -> None:
    try:
        _github_request("POST", f"/repos/{GITHUB_REPOSITORY}/labels", {
            "name": name,
            "color": color,
            "description": "Pending LinkedIn post approval",
        })
    except urllib.error.HTTPError as exc:
        if exc.code == 422:
            pass
        else:
            raise


def create_approval_issue(
    title: str, article_url: str, linkedin_post: str,
) -> str:
    if not GITHUB_TOKEN or not GITHUB_REPOSITORY:
        raise ValueError("GITHUB_TOKEN and GITHUB_REPOSITORY must be set")

    _ensure_label_exists("linkedin-pending")

    body = (
        f"## LinkedIn Post Approval\n\n"
        f"**Article:** [{title}]({article_url})\n\n"
        f"<!-- ARTICLE_URL:{article_url} -->\n"
        f"<!-- ARTICLE_TITLE:{title} -->\n\n"
        f"### Generated LinkedIn Post\n\n"
        f"<!-- POST_START -->\n{linkedin_post}\n<!-- POST_END -->\n\n"
        f"---\n"
        f"Comment **`approve`** to post this to LinkedIn.\n\n"
        f"Comment **`reject`** to skip.\n"
    )

    result = _github_request("POST", f"/repos/{GITHUB_REPOSITORY}/issues", {
        "title": f"LinkedIn Post: {title}",
        "body": body,
        "labels": ["linkedin-pending"],
    })

    issue_url = result["html_url"]
    logger.info("Created approval issue: %s", issue_url)
    return issue_url
