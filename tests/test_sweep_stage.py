import pytest
from app.agent.sessions import ShortlistCandidate
from app.agent.sweep import run_sweep_stage, MAX_SHORTLIST_SIZE
from app.fakes.fake_sessions import FakeHaikuSession


@pytest.mark.asyncio
async def test_shortlist_truncated_to_max_size():
    """Verify shortlist is truncated to MAX_SHORTLIST_SIZE (18)."""
    # Create a shortlist with 25 items
    large_shortlist = [
        ShortlistCandidate(ticker=f"TICKER{i:02d}", reason=f"reason {i}")
        for i in range(25)
    ]
    fake = FakeHaikuSession(shortlist=large_shortlist)

    # Run sweep
    result = await run_sweep_stage(fake, [])

    # Verify truncation to 18 and order preservation
    assert len(result) == MAX_SHORTLIST_SIZE
    assert result == large_shortlist[:MAX_SHORTLIST_SIZE]


@pytest.mark.asyncio
async def test_shortlist_under_bound_returned_unchanged():
    """Verify shortlist under the bound is returned unchanged."""
    # Default shortlist has 3 items
    fake = FakeHaikuSession()

    result = await run_sweep_stage(fake, [])

    # Should return all 3, unchanged
    assert len(result) == 3
    assert result[0].ticker == "RELIANCE"
    assert result[1].ticker == "TATAMOTORS"
    assert result[2].ticker == "INFY"
