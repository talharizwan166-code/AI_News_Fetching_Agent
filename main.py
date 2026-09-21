"""
Main Application Entry Point

This is the heart of the application. When you run this file, it:
1. Fetches latest AI news from RSS feeds
2. Filters out duplicates
3. Scores and ranks articles
4. Selects the best one
5. Generates a LinkedIn post
6. Emails it to you

How to run:
    python main.py

What happens:
    - Loads configuration from .env
    - Validates all settings
    - Runs the complete pipeline
    - Logs everything for debugging
"""

import sys
from datetime import datetime
from config import config
from utils import get_logger
from services import NewsFetcher, EmailService
from agents import NewsScorer, PostGenerator
from database import NewsDatabase

logger = get_logger(__name__)


def validate_configuration() -> bool:
    """
    Validate that all required configuration is present.

    Returns:
        True if valid, False otherwise (exits on False)
    """
    logger.info("Validating configuration...")
    is_valid, missing = config.validate()

    if not is_valid:
        logger.error("Configuration validation failed!")
        logger.error(f"Missing required environment variables: {', '.join(missing)}")
        logger.error("Please check your .env file. See .env.example for reference.")
        return False

    logger.info("Configuration validated successfully")
    return True


def fetch_news() -> list:
    """
    Fetch news from all sources.

    Returns:
        List of NewsArticle objects
    """
    logger.info("=" * 60)
    logger.info("STEP 1: Fetching AI News")
    logger.info("=" * 60)

    fetcher = NewsFetcher()
    articles = fetcher.fetch_all()

    logger.info(f"Fetched {len(articles)} articles from all sources")
    return articles


def filter_duplicates(articles: list, db: NewsDatabase) -> list:
    """
    Remove articles that were already posted.

    Args:
        articles: List of NewsArticle objects
        db: Database instance

    Returns:
        Filtered list of NewsArticle objects
    """
    logger.info("=" * 60)
    logger.info("STEP 2: Filtering Duplicates")
    logger.info("=" * 60)

    unique_articles = []

    for article in articles:
        if db.is_duplicate(article):
            logger.debug(f"Skipping duplicate: {article.title}")
        else:
            unique_articles.append(article)

    logger.info(f"After filtering: {len(unique_articles)} unique articles")
    return unique_articles


def score_and_rank(articles: list) -> list:
    """
    Score articles and sort by relevance.

    Args:
        articles: List of NewsArticle objects

    Returns:
        Sorted list (highest score first)
    """
    logger.info("=" * 60)
    logger.info("STEP 3: Scoring & Ranking Articles")
    logger.info("=" * 60)

    scorer = NewsScorer()
    ranked_articles = scorer.rank_articles(articles)

    # Log top 5
    logger.info("Top 5 articles:")
    for i, article in enumerate(ranked_articles[:5], 1):
        logger.info(f"  {i}. [{article.score:.1f}] {article.title}")
        logger.info(f"     Source: {article.source}")

    return ranked_articles


def generate_linkedin_post(article):
    """
    Generate LinkedIn post using Gemini API.

    Args:
        article: NewsArticle to create post from

    Returns:
        LinkedInPost object or None if generation fails
    """
    logger.info("=" * 60)
    logger.info("STEP 4: Generating LinkedIn Post")
    logger.info("=" * 60)

    logger.info(f"Generating post for: {article.title}")

    try:
        generator = PostGenerator()
        post = generator.generate_post(article)

        if post:
            logger.info("Successfully generated LinkedIn post")
            logger.info(f"Preview: {post.hook[:100]}...")

        return post
    except Exception as e:
        logger.error(f"Failed to generate post: {str(e)}", exc_info=True)
        return None


def send_email(post):
    """
    Send the LinkedIn post draft via email.

    Args:
        post: LinkedInPost object to send

    Returns:
        True if sent successfully, False otherwise
    """
    logger.info("=" * 60)
    logger.info("STEP 5: Sending Email")
    logger.info("=" * 60)

    try:
        email_service = EmailService()
        success = email_service.send_post(post)

        if success:
            logger.info("Email sent successfully")
        else:
            logger.error("Failed to send email")

        return success
    except Exception as e:
        logger.error(f"Error sending email: {str(e)}", exc_info=True)
        return False


def main():
    """
    Main application logic.
    """
    logger.info("=" * 60)
    logger.info("AI NEWS CONTENT AGENT - STARTED")
    logger.info(f"Run time: {datetime.now().strftime('%Y-%m-%d %H:%M:%S')}")
    logger.info("=" * 60)

    try:
        # Step 0: Validate configuration
        if not validate_configuration():
            sys.exit(1)

        # Initialize database
        db = NewsDatabase()

        # Step 1: Fetch news
        articles = fetch_news()

        if not articles:
            logger.warning("No articles fetched. Exiting.")
            return

        # Step 2: Filter duplicates
        unique_articles = filter_duplicates(articles, db)

        if not unique_articles:
            logger.warning("No unique articles found. All were duplicates.")
            return

        # Step 3: Score and rank
        ranked_articles = score_and_rank(unique_articles)

        # Step 3.5: Apply diversity-aware selection
        logger.info("=" * 60)
        logger.info("STEP 3.5: Diversity-Aware Selection")
        logger.info("=" * 60)

        scorer = NewsScorer()
        diverse_candidates = scorer.select_diverse_candidates(ranked_articles)

        logger.info(f"Diverse candidates: {len(diverse_candidates)} articles")
        if len(diverse_candidates) > 1:
            logger.info("Top 3 diverse candidates:")
            for i, article in enumerate(diverse_candidates[:3], 1):
                logger.info(f"  {i}. [{article.score:.1f}] {article.source}: {article.title}")

        # Select best article from diverse candidates
        best_article = diverse_candidates[0]
        logger.info(f"Selected article: {best_article.title}")
        logger.info(f"Score: {best_article.score}")
        logger.info(f"Source: {best_article.source}")
        logger.info(f"URL: {best_article.url}")

        # Step 4: Generate LinkedIn post
        post = generate_linkedin_post(best_article)

        if not post:
            logger.error("Failed to generate LinkedIn post")
            return

        # Step 5: Send email
        success = send_email(post)

        if success:
            # Save to database to prevent duplicates
            db.save_posted_article(best_article)
            logger.info("Successfully completed all steps!")
        else:
            logger.error("Failed to send email")

    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        sys.exit(0)
    except Exception as e:
        logger.error(f"Application error: {str(e)}", exc_info=True)
        sys.exit(1)
    finally:
        logger.info("=" * 60)
        logger.info("AI NEWS CONTENT AGENT - FINISHED")
        logger.info("=" * 60)


if __name__ == "__main__":
    main()