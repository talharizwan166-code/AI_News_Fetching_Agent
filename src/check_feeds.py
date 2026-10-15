#!/usr/bin/env python3
"""
Check RSS Feeds - Verify all configured RSS feeds are alive and accessible.

Usage:
    python -m src.check_feeds
    python -m src.check_feeds --timeout 10
    python -m src.check_feeds --verbose
"""

import argparse
import sys
import time
from concurrent.futures import ThreadPoolExecutor, as_completed

import feedparser
import requests

from src.config import RSS_FEEDS, FETCH_TIMEOUT_SECONDS


def check_feed(name: str, url: str, timeout: int) -> tuple[str, bool, str, float]:
    """
    Check a single RSS feed.

    Returns:
        (name, is_alive, status_message, response_time_ms)
    """
    start = time.perf_counter()
    try:
        resp = requests.get(
            url,
            timeout=timeout,
            headers={"User-Agent": "AINewsAgent/1.0 (Feed Check)"},
            allow_redirects=True,
        )
        elapsed_ms = (time.perf_counter() - start) * 1000

        if resp.status_code == 200:
            feed = feedparser.parse(resp.content)
            if feed.entries or (feed.version and not feed.bozo):
                return name, True, f"OK ({elapsed_ms:.0f}ms, {len(feed.entries)} entries)", elapsed_ms
            return name, False, f"HTTP 200 but not a usable RSS/Atom feed ({elapsed_ms:.0f}ms)", elapsed_ms

        return name, False, f"HTTP {resp.status_code} ({elapsed_ms:.0f}ms)", elapsed_ms

    except requests.Timeout:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return name, False, f"Timeout after {timeout}s ({elapsed_ms:.0f}ms)", elapsed_ms
    except requests.RequestException as exc:
        elapsed_ms = (time.perf_counter() - start) * 1000
        return name, False, f"Error: {exc} ({elapsed_ms:.0f}ms)", elapsed_ms


def check_all_feeds(
    feeds: dict[str, str] | None = None,
    timeout: int = FETCH_TIMEOUT_SECONDS,
    max_workers: int = 5,
) -> list[tuple[str, bool, str, float]]:
    """Check all feeds concurrently."""
    if feeds is None:
        feeds = RSS_FEEDS

    results = []
    with ThreadPoolExecutor(max_workers=max_workers) as executor:
        future_to_name = {
            executor.submit(check_feed, name, url, timeout): name
            for name, url in feeds.items()
        }
        for future in as_completed(future_to_name):
            results.append(future.result())

    # Sort by name for consistent output
    results.sort(key=lambda x: x[0])
    return results


def print_results(results: list[tuple[str, bool, str, float]], verbose: bool = False) -> int:
    """Print check results. Returns exit code (0 = all alive, 1 = some dead)."""
    alive_count = sum(1 for r in results if r[1])
    dead_count = len(results) - alive_count

    print(f"\n{'='*70}")
    print(f"RSS Feed Health Check - {alive_count}/{len(results)} alive")
    print(f"{'='*70}")

    for name, is_alive, msg, elapsed_ms in results:
        status = "✅ ALIVE" if is_alive else "❌ DEAD"
        print(f"  {status} | {name:<30} | {msg}")
        if verbose and not is_alive:
            print(f"      └─ URL: {RSS_FEEDS.get(name, 'N/A')}")

    print(f"{'='*70}")

    if dead_count > 0:
        print(f"\n⚠️  {dead_count} feed(s) are not accessible.")
        print("   Consider fixing or replacing dead feeds.")
        print("   Minimum 6 live sources required for production.")
        return 1

    print("\n✅ All feeds are healthy!")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Check RSS feed health")
    parser.add_argument(
        "--timeout",
        type=int,
        default=FETCH_TIMEOUT_SECONDS,
        help=f"Request timeout in seconds (default: {FETCH_TIMEOUT_SECONDS})",
    )
    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Show URLs for dead feeds",
    )
    parser.add_argument(
        "--workers",
        type=int,
        default=5,
        help="Max concurrent workers (default: 5)",
    )
    args = parser.parse_args()
    if args.timeout <= 0 or args.workers <= 0:
        parser.error("--timeout and --workers must be positive")

    print(f"Checking {len(RSS_FEEDS)} RSS feeds (timeout={args.timeout}s)...")
    results = check_all_feeds(timeout=args.timeout, max_workers=args.workers)
    return print_results(results, verbose=args.verbose)


if __name__ == "__main__":
    sys.exit(main())
