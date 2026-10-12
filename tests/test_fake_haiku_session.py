import pytest
from app.agent.sessions import (
    Citation, DeepDiveContext, DeepDiveResult, ShortlistCandidate,
)
from app.fakes.fake_sessions import (
    DEFAULT_SHORTLIST, DEFAULT_DEEP_DIVES, FakeHaikuSession
)


@pytest.mark.asyncio
async def test_run_sweep_returns_default_shortlist_and_records_call():
    """Verify sweep returns DEFAULT_SHORTLIST and records the call."""
    fake = FakeHaikuSession()
    items = [{"ticker": "DUMMY"}]  # dummy items

    result = await fake.run_sweep(items)

    assert result == DEFAULT_SHORTLIST
    assert len(fake.sweep_calls) == 1
    assert fake.sweep_calls[0] == items


@pytest.mark.asyncio
async def test_run_deep_dive_returns_canned_result_and_records_call():
    """Verify deep_dive returns canned result and records the call."""
    fake = FakeHaikuSession()
    ctx = DeepDiveContext(ticker="RELIANCE", items=[])

    result = await fake.run_deep_dive("RELIANCE", ctx)

    assert result == DEFAULT_DEEP_DIVES["RELIANCE"]
    assert len(fake.deep_dive_calls) == 1
    assert fake.deep_dive_calls[0] == ("RELIANCE", ctx)


@pytest.mark.asyncio
async def test_run_deep_dive_unknown_ticker_raises_keyerror():
    """Verify unknown ticker raises KeyError."""
    fake = FakeHaikuSession()
    ctx = DeepDiveContext(ticker="UNKNOWN", items=[])

    with pytest.raises(KeyError, match="no canned deep-dive for"):
        await fake.run_deep_dive("UNKNOWN", ctx)


@pytest.mark.asyncio
async def test_fail_tickers_set_raises_runtimeerror_for_configured_ticker():
    """Verify fail_tickers set causes RuntimeError for configured tickers."""
    fake = FakeHaikuSession(fail_tickers={"TATAMOTORS"})

    # TATAMOTORS should fail
    ctx = DeepDiveContext(ticker="TATAMOTORS", items=[])
    with pytest.raises(RuntimeError, match="fake deep-dive failure for TATAMOTORS"):
        await fake.run_deep_dive("TATAMOTORS", ctx)

    # RELIANCE should succeed
    ctx = DeepDiveContext(ticker="RELIANCE", items=[])
    result = await fake.run_deep_dive("RELIANCE", ctx)
    assert result == DEFAULT_DEEP_DIVES["RELIANCE"]


@pytest.mark.asyncio
async def test_fail_tickers_dict_raises_the_given_exception():
    """Verify fail_tickers dict raises the exact exception provided."""
    custom_error = ValueError("boom")
    fake = FakeHaikuSession(fail_tickers={"INFY": custom_error})

    ctx = DeepDiveContext(ticker="INFY", items=[])
    with pytest.raises(ValueError, match="boom"):
        await fake.run_deep_dive("INFY", ctx)


@pytest.mark.asyncio
async def test_custom_shortlist_and_deep_dives_override_defaults():
    """Verify custom shortlist and deep_dives override defaults."""
    custom_shortlist = [ShortlistCandidate(ticker="CUSTOM", reason="custom reason")]
    custom_result = DeepDiveResult(
        ticker="CUSTOM",
        catalyst_subscore=30,
        catalyst_reasoning="test",
        sector_momentum_subscore=25,
        sector_momentum_reasoning="test",
        macro_subscore=20,
        macro_reasoning="test",
        citations=[Citation(
            source="test",
            headline="test",
            url="http://test.com",
            published_at="2026-10-01",
        )],
    )
    custom_deep_dives = {"CUSTOM": custom_result}

    fake = FakeHaikuSession(
        shortlist=custom_shortlist,
        deep_dives=custom_deep_dives,
    )

    # Test shortlist
    shortlist = await fake.run_sweep([])
    assert shortlist == custom_shortlist

    # Test deep dive
    ctx = DeepDiveContext(ticker="CUSTOM", items=[])
    result = await fake.run_deep_dive("CUSTOM", ctx)
    assert result == custom_result
