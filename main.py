#!/usr/bin/env python3
"""
AI News Agent - Main Entry Point

Thin wrapper that:
- Configures logging from LOG_LEVEL env var
- Validates configuration
- Calls src.agent.run_agent() with optional dry-run
- Exits with non-zero code on failure
"""

import sys
import os
import logging
from datetime import datetime

# Load .env before importing config
from dotenv import load_dotenv
load_dotenv()

from src.config import config
from src.agent import run_agent


def setup_logging() -> None:
    """Configure logging from LOG_LEVEL environment variable."""
    log_level = os.getenv("LOG_LEVEL", "INFO").upper()
    numeric_level = getattr(logging, log_level, logging.INFO)

    logging.basicConfig(
        level=numeric_level,
        format="%(asctime)s | %(levelname)-8s | %(name)s | %(message)s",
        datefmt="%Y-%m-%d %H:%M:%S",
    )

    # Quiet noisy third-party loggers unless DEBUG
    if numeric_level > logging.DEBUG:
        logging.getLogger("urllib3").setLevel(logging.WARNING)
        logging.getLogger("google").setLevel(logging.WARNING)
        logging.getLogger("feedparser").setLevel(logging.WARNING)


def check_env_not_tracked() -> bool:
    """Check that .env is not tracked by git."""
    import subprocess
    try:
        result = subprocess.run(
            ["git", "ls-files", "--error-unmatch", ".env"],
            capture_output=True,
            text=True,
        )
        if result.returncode == 0:
            logging.error(".env is tracked by git! This is a security risk.")
            logging.error("Run: git rm --cached .env && echo '.env' >> .gitignore")
            return False
    except FileNotFoundError:
        # git not available, skip check
        pass
    return True


def check_secrets_rotation() -> None:
    """Remind about rotating secrets periodically."""
    import datetime
    from pathlib import Path

    env_path = Path(".env")
    if env_path.exists():
        mtime = datetime.datetime.fromtimestamp(env_path.stat().st_mtime)
        age_days = (datetime.datetime.now() - mtime).days
        if age_days > 90:
            logging.warning(
                "SECURITY REMINDER: .env file is %d days old. "
                "Consider rotating Gemini API key and Gmail app password.",
                age_days
            )


def validate_config() -> bool:
    """Validate all required configuration is present."""
    is_valid, missing = config.validate()
    if not is_valid:
        logging.error("Configuration validation failed!")
        logging.error("Missing required environment variables: %s", ", ".join(missing))
        logging.error("Check your .env file. See .env.example for reference.")
        return False
    logging.info("Configuration validated successfully")
    return True


def parse_args() -> dict:
    """Parse command-line arguments and DRY_RUN env var."""
    import argparse

    parser = argparse.ArgumentParser(description="AI News Agent")
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Run fetch->dedup->score->select->generate, print result, no email/issue/DB write",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Enable debug logging (overrides LOG_LEVEL)",
    )
    args = vars(parser.parse_args())

    # Also check DRY_RUN env var
    if not args["dry_run"] and os.getenv("DRY_RUN", "").lower() in ("1", "true", "yes"):
        args["dry_run"] = True

    return args


def main() -> int:
    """Main entry point. Returns exit code (0=success, 1=failure)."""
    args = parse_args()

    if args["verbose"]:
        os.environ["LOG_LEVEL"] = "DEBUG"

    setup_logging()

    logger = logging.getLogger(__name__)

    logger.info("=" * 60)
    logger.info("AI NEWS CONTENT AGENT - STARTED")
    logger.info("Run time: %s", datetime.now().strftime("%Y-%m-%d %H:%M:%S"))
    if args["dry_run"]:
        logger.info("MODE: DRY RUN (no email, no issue, no DB write)")
    logger.info("=" * 60)

    try:
        # Security checks
        if not check_env_not_tracked():
            return 1
        check_secrets_rotation()

        # Validate configuration
        if not validate_config():
            return 1

        # Run the agent
        result = run_agent(dry_run=args["dry_run"])

        # Determine exit code based on result
        status = result.get("status", "error")
        if status == "success":
            logger.info("=== AI News Agent finished successfully ===")
            return 0
        elif status in ("no_articles", "all_published", "below_threshold"):
            logger.warning("Agent completed with status: %s", status)
            return 0  # Not a failure - just no actionable result
        else:
            logger.error("Agent failed with status: %s", status)
            return 1

    except KeyboardInterrupt:
        logger.info("Application interrupted by user")
        return 0
    except Exception as e:
        logger.exception("Application error: %s", e)
        return 1
    finally:
        logger.info("=" * 60)
        logger.info("AI NEWS CONTENT AGENT - FINISHED")
        logger.info("=" * 60)


if __name__ == "__main__":
    sys.exit(main())
