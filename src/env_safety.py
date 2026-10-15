"""Check Git metadata without opening or displaying environment files."""

import logging
import os
import subprocess
from pathlib import Path


def check_env_not_tracked() -> bool:
    """Block confirmed local tracking; warn and continue in CI or on Git errors."""
    if any(os.getenv(name, "").strip().lower() == "true" for name in ("CI", "GITHUB_ACTIONS")):
        logging.warning("CI environment detected; skipping the .env tracking guard.")
        return True
    root = Path(__file__).resolve().parents[1]
    try:
        result = subprocess.run(
            ["git", "-C", str(root), "ls-files", "--", ".env"],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.SubprocessError):
        logging.warning("Cannot check .env tracking: Git is unavailable or the check failed; continuing.")
        return True
    if result.returncode != 0:
        logging.warning("Git could not verify .env tracking (exit %s); continuing.", result.returncode)
        return True
    if ".env" in result.stdout.splitlines():
        logging.error("Refusing to start: .env is tracked by Git.")
        logging.error("Remove it with git rm --cached -- .env and rotate exposed credentials.")
        return False
    return True
