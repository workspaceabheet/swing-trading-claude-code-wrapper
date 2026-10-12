"""Integration tests for Slice 8: compilation stage wired into orchestrator."""

import datetime as dt

import pytest
from app.db import db_session, get_candidates_for_run
from app.run_orchestrator import RunOrchestrator
from app.fakes.fake_sessions import FakeHaikuSession, FakeCompilationSession
from app.sources.base import NormalizedItem


class _StubAgg:
    """No-op sourcing aggregator: returns instantly, zero failures, but with
    Bhavcopy-style close prices for the default FakeHaikuSession shortlist
    (RELIANCE, TATAMOTORS, INFY) so entry-price resolution succeeds --
    otherwise every idea would be dropped before assembly for lacking a buy
    price. Without a real aggregator, RunOrchestrator defaults to a REAL
    SourcingAggregator() that hits live Moneycontrol/Bhavcopy/Screener.in/
    Trading Economics -- turning a fast offline unit test into a slow (or
    hanging) live-network test. Mirrors the pattern in
    tests/test_run_orchestrator_slice4.py."""

    async def fetch_all(self):
        items = [
            NormalizedItem(
                source="nse_bhavcopy",
                headline=f"{t} EOD",
                url=f"http://example.com/{t}",
                published_at=dt.datetime.now(dt.timezone.utc),
                snippet=f"{t} EOD price",
                ticker=t,
                close=close,
            )
            for t, close in [("RELIANCE", 2900.0), ("TATAMOTORS", 950.0), ("INFY", 1550.0)]
        ]
        return items, []


@pytest.mark.asyncio
async def test_full_run_with_fake_compilation_populates_polished_fields(data_dir):
    """Verify that a full orchestrator run with fake compilation populates
    polished_rationale and ranking_commentary fields in the ideas table."""
    # Create orchestrator with fake sessions
    haiku = FakeHaikuSession()
    compilation = FakeCompilationSession()
    orchestrator = RunOrchestrator(
        aggregator=_StubAgg(), haiku_session=haiku, compilation_session=compilation
    )

    # Create run
    run_id = None
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (datetime('now'), 'running')"
        )
        run_id = cursor.lastrowid

    # Execute the full pipeline
    await orchestrator.execute_run(run_id)

    # Query ideas table to verify polished fields are populated
    with db_session() as conn:
        ideas = conn.execute(
            "SELECT ticker, score, tier, polished_rationale, ranking_commentary FROM ideas "
            "WHERE run_id = ? AND excluded = 0 ORDER BY rank",
            (run_id,),
        ).fetchall()

    # Check results
    assert len(ideas) > 0, "No ideas produced by run"

    for idea in ideas:
        ticker, score, tier, polished_rationale, ranking_commentary = idea
        assert score is not None, f"{ticker}: score is None (should be non-null from Slice 5)"
        assert tier is not None, f"{ticker}: tier is None (should be non-null from Slice 5)"
        assert polished_rationale, f"{ticker}: polished_rationale is empty (should be populated by Slice 8)"
        assert ranking_commentary, f"{ticker}: ranking_commentary is empty (should be populated by Slice 8)"

        # Verify the fake's canned prefix is there
        assert "[FAKE polished]" in polished_rationale
        assert "[FAKE fragment]" in ranking_commentary


@pytest.mark.asyncio
async def test_compilation_call_count_exactly_one_per_run(data_dir):
    """Verify that exactly one compilation call is made per run, regardless of candidate count."""
    haiku = FakeHaikuSession()
    compilation = FakeCompilationSession()
    orchestrator = RunOrchestrator(
        aggregator=_StubAgg(), haiku_session=haiku, compilation_session=compilation
    )

    # Create run
    run_id = None
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (datetime('now'), 'running')"
        )
        run_id = cursor.lastrowid

    # Execute
    await orchestrator.execute_run(run_id)

    # Verify compilation was called exactly once
    assert len(compilation.calls) == 1, \
        f"Expected 1 compilation call, got {len(compilation.calls)}"

    # Verify all surviving candidates were in that one call
    call_tickers = compilation.calls[0]
    assert len(call_tickers) == len(haiku.deep_dives), \
        f"Compilation call included {len(call_tickers)} tickers, " \
        f"expected all {len(haiku.deep_dives)} fake deep dives"
