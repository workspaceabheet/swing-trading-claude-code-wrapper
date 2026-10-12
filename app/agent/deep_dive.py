import asyncio
import logging
from app.agent.sessions import HaikuSession, ShortlistCandidate, DeepDiveContext, DeepDiveResult

log = logging.getLogger(__name__)

# Conservative default cap on concurrent deep-dive Haiku calls in flight at once.
# Each call is an independent ClaudeSDKClient connect/query/disconnect cycle (see
# haiku_session.RealHaikuSession.run_deep_dive), so raising this trades API/rate-limit
# pressure for lower wall-clock time. Tunable later.
MAX_CONCURRENT_DEEP_DIVES = 5


async def run_deep_dive_stage(
    session: HaikuSession,
    shortlist: list[ShortlistCandidate],
    context_by_ticker: dict[str, DeepDiveContext],
) -> list[DeepDiveResult]:
    """Runs session.run_deep_dive concurrently across the shortlist, bounded by a
    semaphore capped at MAX_CONCURRENT_DEEP_DIVES.

    Implements per-ticker isolation: a failure for one ticker does not abort the
    run or affect other in-flight calls. Tickers with missing contexts are passed
    an empty DeepDiveContext.

    Args:
        session: A HaikuSession implementing run_deep_dive.
        shortlist: list[ShortlistCandidate] from the sweep stage.
        context_by_ticker: dict[ticker, DeepDiveContext] pre-built by the orchestrator.

    Returns:
        list[DeepDiveResult] for all tickers that succeeded (failures are skipped),
        in the same relative order as `shortlist`.
    """
    semaphore = asyncio.Semaphore(MAX_CONCURRENT_DEEP_DIVES)

    async def _run_one(candidate: ShortlistCandidate) -> DeepDiveResult | None:
        ticker = candidate.ticker
        context = context_by_ticker.get(ticker, DeepDiveContext(ticker=ticker, items=[]))
        async with semaphore:
            try:
                return await session.run_deep_dive(ticker, context)
            except Exception:
                log.warning("deep-dive failed for %s; skipping", ticker, exc_info=True)
                return None

    outcomes = await asyncio.gather(
        *(_run_one(candidate) for candidate in shortlist),
        return_exceptions=True,
    )

    results: list[DeepDiveResult] = []
    for candidate, outcome in zip(shortlist, outcomes):
        if isinstance(outcome, BaseException):
            log.warning("deep-dive failed for %s; skipping", candidate.ticker, exc_info=outcome)
            continue
        if outcome is not None:
            results.append(outcome)
    return results
