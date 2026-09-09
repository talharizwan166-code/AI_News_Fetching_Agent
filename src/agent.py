import logging
from src.fetcher import fetch_all_feeds, Article
from src.dedup import deduplicate
from src.scorer import score_and_rank
from src.selector import select_best_article
from src.generator import generate_linkedin_post
from src.emailer import send_email
from src.github_issues import create_approval_issue
from src.database import init_db, is_already_published, save_article, get_published_urls

logger = logging.getLogger(__name__)


def run_agent() -> dict:
    logger.info("=== AI News Agent starting ===")

    init_db()

    logger.info("Step 1: Fetching articles...")
    articles = fetch_all_feeds()
    if not articles:
        logger.warning("No articles fetched. Exiting.")
        return {"status": "no_articles"}

    logger.info("Step 2: Deduplicating %d articles...", len(articles))
    articles = deduplicate(articles)
    logger.info("After dedup: %d articles", len(articles))

    published_urls = get_published_urls()
    articles = [a for a in articles if a.url not in published_urls]
    logger.info("After removing already-published: %d articles", len(articles))

    if not articles:
        logger.warning("All articles already published. Exiting.")
        return {"status": "all_published"}

    logger.info("Step 3: Scoring and ranking...")
    articles = score_and_rank(articles)

    logger.info("Step 4: Selecting best article with source diversity...")
    best = select_best_article(articles)
    if best is None:
        logger.warning("No article met the quality threshold. Exiting.")
        return {"status": "below_threshold"}

    logger.info("Selected: [%s] %s (score=%.4f)", best.source, best.title, best.score)

    logger.info("Step 5: Generating LinkedIn post...")
    try:
        linkedin_post = generate_linkedin_post(best)
    except Exception as exc:
        logger.warning("LinkedIn post generation failed: %s. Sending email without it.", exc)
        linkedin_post = "(LinkedIn post could not be generated — the AI service was unavailable.)"

    logger.info("Step 6: Creating approval issue...")
    issue_url = ""
    try:
        issue_url = create_approval_issue(best.title, best.url, linkedin_post)
    except Exception as exc:
        logger.warning("Could not create GitHub issue: %s", exc)

    logger.info("Step 7: Sending email...")
    send_email(best, linkedin_post, issue_url)

    logger.info("Step 8: Saving to database...")
    save_article(
        url=best.url,
        title=best.title,
        source=best.source,
        score=best.score,
        linkedin_post=linkedin_post,
        published_at=best.published_at,
    )

    logger.info("=== AI News Agent finished successfully ===")
    return {
        "status": "success",
        "article": best.title,
        "source": best.source,
        "score": best.score,
    }
