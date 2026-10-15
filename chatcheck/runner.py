"""Bounded async workers with a shared request-start rate limiter."""

import asyncio
import time

from .connectors import Connector, ConnectorError
from .judge import judge, validate_checks
from .models import RunOptions, TestCase
from .storage import Storage


class RateLimiter:
    def __init__(self, requests_per_second: float):
        self.interval = 1 / requests_per_second if requests_per_second else 0
        self.next_start = 0.0
        self.lock = asyncio.Lock()

    async def wait(self):
        if not self.interval:
            return
        async with self.lock:
            await asyncio.sleep(max(0, self.next_start - time.monotonic()))
            self.next_start = time.monotonic() + self.interval


async def run_suite(
    tests: list[TestCase], connector: Connector, storage: Storage,
    options: RunOptions | None = None, *, target_name="target", suite_path="",
) -> str:
    options = options or RunOptions()
    if not tests or len({t.id for t in tests}) != len(tests):
        raise ValueError("Suite must contain tests with unique ids")
    for test in tests:
        validate_checks(test.checks)
    run_id, test_ids = storage.start_run(tests, target_name, suite_path, options)
    limiter = RateLimiter(options.rate_limit)
    work = iter(zip(tests, test_ids))

    async def worker():
        # A shared iterator consumed without an await bounds task count to concurrency.
        for test, test_id in work:
            text = error = None
            for attempt in range(1, options.retries + 2):
                await limiter.wait()
                start = time.perf_counter()
                text = error = None
                retryable = False
                try:
                    async with asyncio.timeout(options.timeout):
                        text = await connector.send(test.prompt)
                    if not isinstance(text, str):
                        raise ConnectorError("Connector returned a non-string response")
                except TimeoutError:
                    error = f"Timed out after {options.timeout:g}s"
                    retryable = True
                except ConnectorError as exc:
                    error, retryable = str(exc), exc.retryable
                except Exception as exc:
                    error = f"Unexpected connector error ({type(exc).__name__})"
                latency = (time.perf_counter() - start) * 1000
                storage.record_attempt(test_id, attempt, text, latency, error)
                if error is None or not retryable or attempt > options.retries:
                    break
                # Backoff is separate from the next attempt's timeout and latency.
                await asyncio.sleep(min(30.0, options.retry_backoff * 2 ** min(attempt - 1, 16)))
            storage.record_verdict(test_id, judge(text, test.checks, error))

    try:
        async with connector:
            async with asyncio.TaskGroup() as group:
                for _ in range(min(options.concurrency, len(tests))):
                    group.create_task(worker())
    except BaseException as exc:
        # Commit partial results even on Ctrl+C; TaskGroup cancels other workers first.
        status = "cancelled" if isinstance(exc, (asyncio.CancelledError, KeyboardInterrupt)) else "failed"
        storage.finish_run(run_id, status, f"Run interrupted ({type(exc).__name__})")
        raise
    storage.finish_run(run_id)
    return run_id
