"""Verifies run_deep_dive_stage actually executes deep-dive calls concurrently,
and that concurrency is bounded by MAX_CONCURRENT_DEEP_DIVES.
"""

import asyncio
import time

import pytest

from app.agent.deep_dive import MAX_CONCURRENT_DEEP_DIVES, run_deep_dive_stage
from app.agent.sessions import DeepDiveContext, DeepDiveResult, ShortlistCandidate


class _SleepyFakeSession:
    """A fake HaikuSession whose run_deep_dive sleeps briefly and records
    start/end wall-clock timestamps per call, so tests can assert that
    multiple calls' time windows overlap (true concurrency), not just that
    they all eventually complete.
    """

    def __init__(self, delay: float = 0.05):
        self.delay = delay
        self.windows: list[tuple[float, float]] = []

    async def run_sweep(self, items):  # pragma: no cover - unused here
        raise NotImplementedError

    async def run_deep_dive(self, ticker: str, context: DeepDiveContext) -> DeepDiveResult:
        start = time.monotonic()
        await asyncio.sleep(self.delay)
        end = time.monotonic()
        self.windows.append((start, end))
        return DeepDiveResult(
            ticker=ticker,
            catalyst_subscore=10, catalyst_reasoning="x",
            sector_momentum_subscore=10, sector_momentum_reasoning="x",
            macro_subscore=15, macro_reasoning="x",
            citations=[],
        )

    async def disconnect(self) -> None:
        pass


class _ConcurrencyTrackingFakeSession:
    """A fake HaikuSession that tracks how many run_deep_dive calls are
    in-flight simultaneously, to verify the semaphore cap is respected.
    """

    def __init__(self, delay: float = 0.02):
        self.delay = delay
        self._in_flight = 0
        self.max_in_flight = 0

    async def run_sweep(self, items):  # pragma: no cover - unused here
        raise NotImplementedError

    async def run_deep_dive(self, ticker: str, context: DeepDiveContext) -> DeepDiveResult:
        self._in_flight += 1
        self.max_in_flight = max(self.max_in_flight, self._in_flight)
        try:
            await asyncio.sleep(self.delay)
        finally:
            self._in_flight -= 1
        return DeepDiveResult(
            ticker=ticker,
            catalyst_subscore=10, catalyst_reasoning="x",
            sector_momentum_subscore=10, sector_momentum_reasoning="x",
            macro_subscore=15, macro_reasoning="x",
            citations=[],
        )

    async def disconnect(self) -> None:
        pass


def _shortlist(n: int) -> list[ShortlistCandidate]:
    return [ShortlistCandidate(ticker=f"T{i:02d}", reason="r") for i in range(n)]


@pytest.mark.asyncio
async def test_deep_dive_calls_run_concurrently_not_sequentially():
    """With N tickers each sleeping `delay` seconds, concurrent execution
    should take close to one `delay`, not N * delay -- and the recorded
    start/end windows should overlap in time.
    """
    n = 5
    delay = 0.05
    fake = _SleepyFakeSession(delay=delay)
    shortlist = _shortlist(n)
    context_by_ticker = {c.ticker: DeepDiveContext(ticker=c.ticker, items=[]) for c in shortlist}

    wall_start = time.monotonic()
    results = await run_deep_dive_stage(fake, shortlist, context_by_ticker)
    wall_elapsed = time.monotonic() - wall_start

    assert len(results) == n
    # Sequential execution would take ~ n * delay (0.25s); concurrent execution
    # (bounded by a semaphore >= n) should take well under that.
    assert wall_elapsed < (n * delay) * 0.7, (
        f"expected concurrent execution to be faster than sequential; "
        f"took {wall_elapsed:.3f}s, sequential would be ~{n * delay:.3f}s"
    )

    # Assert that at least two calls' time windows actually overlap (true
    # concurrency, not just "all eventually completed").
    windows = fake.windows
    assert len(windows) == n
    overlap_found = any(
        a_start < b_end and b_start < a_end
        for i, (a_start, a_end) in enumerate(windows)
        for j, (b_start, b_end) in enumerate(windows)
        if i != j
    )
    assert overlap_found, f"expected overlapping call windows, got {windows}"


@pytest.mark.asyncio
async def test_concurrency_is_capped_at_max_concurrent_deep_dives():
    """No more than MAX_CONCURRENT_DEEP_DIVES calls should be in flight at once,
    even with more tickers than the cap.
    """
    n = MAX_CONCURRENT_DEEP_DIVES * 3
    fake = _ConcurrencyTrackingFakeSession(delay=0.02)
    shortlist = _shortlist(n)
    context_by_ticker = {c.ticker: DeepDiveContext(ticker=c.ticker, items=[]) for c in shortlist}

    results = await run_deep_dive_stage(fake, shortlist, context_by_ticker)

    assert len(results) == n
    assert fake.max_in_flight <= MAX_CONCURRENT_DEEP_DIVES
    # Also sanity-check the cap is actually being exercised (not trivially 1).
    assert fake.max_in_flight == MAX_CONCURRENT_DEEP_DIVES
