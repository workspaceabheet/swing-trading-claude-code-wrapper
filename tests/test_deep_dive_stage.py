import pytest
from app.agent.sessions import DeepDiveContext
from app.agent.deep_dive import run_deep_dive_stage
from app.fakes.fake_sessions import FakeHaikuSession, DEFAULT_SHORTLIST


@pytest.mark.asyncio
async def test_one_deep_dive_call_per_shortlisted_ticker():
    """Verify one deep_dive call per shortlist item when all succeed."""
    fake = FakeHaikuSession()
    context_by_ticker = {
        "RELIANCE": DeepDiveContext(ticker="RELIANCE", items=[]),
        "TATAMOTORS": DeepDiveContext(ticker="TATAMOTORS", items=[]),
        "INFY": DeepDiveContext(ticker="INFY", items=[]),
    }

    result = await run_deep_dive_stage(fake, DEFAULT_SHORTLIST, context_by_ticker)

    # All 3 should succeed. Note: calls run concurrently (asyncio.gather), so
    # completion order is not guaranteed -- but gather's result list preserves
    # the input (shortlist) order regardless of completion order.
    assert len(result) == 3
    tickers = [r.ticker for r in result]
    assert tickers == ["RELIANCE", "TATAMOTORS", "INFY"]

    # Verify call recording by count/membership, not completion order (concurrent
    # calls may complete out of order).
    assert len(fake.deep_dive_calls) == 3
    call_tickers = {call[0] for call in fake.deep_dive_calls}
    assert call_tickers == {"RELIANCE", "TATAMOTORS", "INFY"}


@pytest.mark.asyncio
async def test_per_stock_failure_is_skipped_and_run_continues():
    """Verify one ticker's failure doesn't abort the run; others succeed."""
    fake = FakeHaikuSession(fail_tickers={"TATAMOTORS"})
    context_by_ticker = {
        "RELIANCE": DeepDiveContext(ticker="RELIANCE", items=[]),
        "TATAMOTORS": DeepDiveContext(ticker="TATAMOTORS", items=[]),
        "INFY": DeepDiveContext(ticker="INFY", items=[]),
    }

    result = await run_deep_dive_stage(fake, DEFAULT_SHORTLIST, context_by_ticker)

    # Only 2 should be in results (RELIANCE and INFY; TATAMOTORS failed and was skipped)
    assert len(result) == 2
    tickers = [r.ticker for r in result]
    assert tickers == ["RELIANCE", "INFY"]
    assert "TATAMOTORS" not in tickers

    # Verify all 3 calls were attempted (not just 2), by count/membership since
    # concurrent calls may complete out of order.
    assert len(fake.deep_dive_calls) == 3
    call_tickers = {call[0] for call in fake.deep_dive_calls}
    assert call_tickers == {"RELIANCE", "TATAMOTORS", "INFY"}
