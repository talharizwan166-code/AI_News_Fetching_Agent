import logging
from typing import Any

from src.fetcher import fetch_all_feeds, Article
from src.dedup import deduplicate, filter_published
from src.scorer import score_and_rank
from src.selector import select_best_article
from src.generator import generate_linkedin_post
from src.emailer import send_email
from src.github_issues import create_approval_issue
from src.database import init_db, save_article
from src.config import DB_PATH, MIN_QUALITY_THRESHOLD, MIN_AI_RELEVANCE

logger = logging.getLogger(__name__)


def _filter_by_ai_relevance(articles: list[Article], min_ai_relevance: float) -> list[Article]:
    """Filter out articles with AI relevance below threshold."""
    from src.scorer import ai_relevance_score

    filtered = []
    for article in articles:
        text = f"{article.title} {article.summary}"
        ai_score = ai_relevance_score(text)
        if ai_score >= min_ai_relevance:
            filtered.append(article)
        else:
            logger.debug("Filtered out (low AI relevance %.2f): %s", ai_score, article.title)
    return filtered


def run_agent(dry_run: bool = False) -> dict[str, Any]:
    """
    Run the AI News Agent pipeline.

    Args:
        dry_run: If True, run fetch->dedup->score->select->generate but skip
                 email, issue creation, and DB write. Print result instead.

    Returns:
        Dict with status and relevant info.
    """
    logger.info("=== AI News Agent starting ===")
    if dry_run:
        logger.info("DRY RUN MODE: No email, no issue, no DB write")

    if not dry_run:
        init_db(DB_PATH)

    logger.info("Step 1: Fetching articles...")
    articles = fetch_all_feeds()
    if not articles:
        logger.warning("No articles fetched. Exiting.")
        return {"status": "no_articles"}

    logger.info("Step 2: Deduplicating %d articles...", len(articles))
    articles = deduplicate(articles)
    logger.info("After dedup: %d articles", len(articles))

    logger.info("Step 3: Removing already-published articles...")
    articles = filter_published(articles, db_path=DB_PATH, read_only=dry_run)
    logger.info("After removing already-published: %d articles", len(articles))

    if not articles:
        logger.warning("All articles already published. Exiting.")
        return {"status": "all_published"}

    logger.info("Step 3: Filtering by AI relevance (min=%.2f)...", MIN_AI_RELEVANCE)
    articles = _filter_by_ai_relevance(articles, MIN_AI_RELEVANCE)
    logger.info("After AI relevance filter: %d articles", len(articles))

    if not articles:
        logger.warning("No articles met AI relevance threshold. Exiting.")
        return {"status": "below_threshold"}

    logger.info("Step 4: Scoring and ranking...")
    articles = score_and_rank(articles)

    logger.info("Step 5: Selecting best article with source diversity...")
    best = select_best_article(articles, min_threshold=MIN_QUALITY_THRESHOLD)
    if best is None:
        logger.warning("No article met the quality threshold (min=%.2f). Exiting.", MIN_QUALITY_THRESHOLD)
        return {"status": "below_threshold"}

    logger.info("Selected: [%s] %s (score=%.4f)", best.source, best.title, best.score)

    logger.info("Step 6: Generating LinkedIn post...")
    try:
        linkedin_post = generate_linkedin_post(best)
    except Exception as exc:
        logger.error("LinkedIn post generation failed: %s", exc)
        if dry_run:
            logger.info("DRY RUN: Would exit with gemini_failed status")
            return {"status": "gemini_failed", "article": best.title, "source": best.source, "error": str(exc)}
        logger.error("Gemini failure - skipping issue creation and DB save. Next run will retry.")
        return {"status": "gemini_failed", "article": best.title, "source": best.source, "error": str(exc)}

    if dry_run:
        logger.info("=" * 60)
        logger.info("DRY RUN RESULT")
        logger.info("=" * 60)
        logger.info("Article: %s", best.title)
        logger.info("Source: %s", best.source)
        logger.info("URL: %s", best.url)
        logger.info("Score: %.4f", best.score)
        logger.info("Generated LinkedIn Post:")
        logger.info("-" * 40)
        logger.info("%s", linkedin_post)
        logger.info("-" * 40)
        logger.info("DRY RUN COMPLETE - No email sent, no issue created, no DB write")
        return {
            "status": "success",
            "article": best.title,
            "source": best.source,
            "score": best.score,
            "dry_run": True,
        }

    logger.info("Step 7: Creating approval issue...")
    issue_url = ""
    try:
        issue_url = create_approval_issue(best.title, best.url, linkedin_post)
    except Exception as exc:
        logger.warning("Could not create GitHub issue: %s", exc)

    logger.info("Step 8: Sending email...")
    email_delivered = False
    try:
        send_email(best, linkedin_post, issue_url)
        email_delivered = True
    except Exception as exc:
        logger.error("Failed to send email: %s", exc)

    if not issue_url and not email_delivered:
        logger.error("Post was not delivered. Leaving article unpublished for retry.")
        return {"status": "delivery_failed", "article": best.title, "source": best.source}

    logger.info("Step 9: Saving to database...")
    save_article(
        url=best.url,
        title=best.title,
        source=best.source,
        score=best.score,
        linkedin_post=linkedin_post,
        published_at=best.published_at,
        db_path=DB_PATH,
    )

    logger.info("=== AI News Agent finished successfully ===")
    return {
        "status": "success",
        "article": best.title,
        "source": best.source,
        "score": best.score,
    }
