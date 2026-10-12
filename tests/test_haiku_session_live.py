"""Optional live test for RealHaikuSession.

This test exercises real Haiku API calls and requires:
  - claude login to be active (local authentication)
  - SWINGTRADE_RUN_LIVE_HAIKU_TEST=1 environment variable set
  - Network access to the Claude API

Skipped by default in CI and normal test runs. Run manually with:
  SWINGTRADE_RUN_LIVE_HAIKU_TEST=1 pytest tests/test_haiku_session_live.py -v -m live
"""

import os
import pytest
from datetime import datetime

from app.agent.haiku_session import RealHaikuSession
from app.agent.sessions import DeepDiveContext
from app.sources.base import NormalizedItem

pytestmark = pytest.mark.skipif(
    os.environ.get("SWINGTRADE_RUN_LIVE_HAIKU_TEST") != "1",
    reason=(
        "live Haiku SDK test opt-in only; set SWINGTRADE_RUN_LIVE_HAIKU_TEST=1 "
        "and ensure `claude login` is active"
    ),
)


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_sweep_and_deep_dive_round_trip():
    """One real sweep call followed by one real deep-dive call.

    Uses a fixed, hand-picked set of sweep items (not live-scraped sources),
    so cost and runtime are bounded and don't depend on source adapter liveness.
    """
    # Fixed test dataset (not live-sourced; bounded cost and latency)
    test_items = [
        NormalizedItem(
            source="moneycontrol_rss",
            headline="Reliance Industries refining margins improve in Q2 2026",
            url="https://example.com/reliance-q2",
            published_at=datetime(2026, 10, 10),
            snippet="Reliance refining margins hit 5-year highs in Q2.",
            ticker="RELIANCE",
        ),
        NormalizedItem(
            source="screener_in",
            headline="Infosys wins large deal with European retailer",
            url="https://example.com/infy-deal",
            published_at=datetime(2026, 10, 11),
            snippet="Infosys announced a large multi-year deal with a European retailer.",
            ticker="INFY",
        ),
    ]

    session = RealHaikuSession()
    try:
        # Real sweep call with web search/fetch enabled
        sweep_result = await session.run_sweep(test_items)
        assert sweep_result is not None
        assert isinstance(sweep_result, list)
        assert len(sweep_result) > 0

        # Pick the first shortlisted ticker for deep-dive (or use a hardcoded fallback)
        ticker = sweep_result[0].ticker if sweep_result else "RELIANCE"

        # Build context for deep-dive (use fixed test items)
        context = DeepDiveContext(
            ticker=ticker,
            items=[item for item in test_items if item.ticker == ticker or item.ticker is None],
        )

        # Real deep-dive call (tools disabled, pure reasoning)
        deep_dive_result = await session.run_deep_dive(ticker, context)
        assert deep_dive_result is not None
        assert deep_dive_result.ticker == ticker
        assert isinstance(deep_dive_result.catalyst_subscore, int)
        assert 0 <= deep_dive_result.catalyst_subscore <= 40
        assert isinstance(deep_dive_result.sector_momentum_subscore, int)
        assert 0 <= deep_dive_result.sector_momentum_subscore <= 35
        assert deep_dive_result.macro_subscore in {15, 20, 25}
        assert len(deep_dive_result.citations) > 0

    finally:
        # Clean disconnect
        await session.disconnect()


@pytest.mark.live
@pytest.mark.asyncio
async def test_live_session_disconnects_cleanly():
    """Session disconnects without error after real calls."""
    test_items = [
        NormalizedItem(
            source="test",
            headline="Test headline",
            url="https://example.com/test",
            published_at=datetime(2026, 10, 10),
            snippet="Test snippet",
            ticker="TEST",
        ),
    ]

    session = RealHaikuSession()
    try:
        # Run a sweep (may succeed or fail, doesn't matter for this test)
        try:
            await session.run_sweep(test_items)
        except Exception:
            pass  # Ignore sweep failures; we're testing disconnect
    finally:
        # Disconnect must not raise
        await session.disconnect()
        # Disconnect again should also be safe (idempotent)
        await session.disconnect()
