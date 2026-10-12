import logging
from app.agent.sessions import HaikuSession, ShortlistCandidate

log = logging.getLogger(__name__)

MAX_SHORTLIST_SIZE = 18


async def run_sweep_stage(session: HaikuSession, items: list) -> list[ShortlistCandidate]:
    """Calls session.run_sweep(items) and enforces the shortlist-size bound.

    Args:
        session: A HaikuSession implementing run_sweep.
        items: list[NormalizedItem] from the completed sourcing stage.

    Returns:
        A shortlist of candidate tickers, bounded to MAX_SHORTLIST_SIZE.
    """
    shortlist = await session.run_sweep(items)
    if len(shortlist) > MAX_SHORTLIST_SIZE:
        log.warning(
            "sweep returned %d candidates, exceeding MAX_SHORTLIST_SIZE (%d); "
            "truncating to the first %d",
            len(shortlist),
            MAX_SHORTLIST_SIZE,
            MAX_SHORTLIST_SIZE,
        )
        shortlist = shortlist[:MAX_SHORTLIST_SIZE]
    return shortlist
