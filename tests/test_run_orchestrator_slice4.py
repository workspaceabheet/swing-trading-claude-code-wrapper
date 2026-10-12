import pytest
from pathlib import Path

from app.db import db_session, get_connection, get_candidates_for_run
from app.fakes.fake_sessions import FakeHaikuSession
from app.run_orchestrator import RunOrchestrator
from app.sources.aggregator import SourcingAggregator
from app.sources.base import NormalizedItem


@pytest.mark.asyncio
async def test_full_run_produces_shortlist_bound_and_candidate_rows(data_dir):
    """Verify sweep shortlist bound is enforced end-to-end through persistence."""

    # Create a 25-item large shortlist to test truncation
    from app.agent.sessions import ShortlistCandidate, Citation, DeepDiveResult
    large_shortlist = [
        ShortlistCandidate(ticker=f"T{i:02d}", reason=f"reason {i}")
        for i in range(25)
    ]
    # Create matching deep_dives for all 25 tickers
    # Note: macro_subscore must be one of {15, 20, 25} per tech-spec §6
    deep_dives = {
        f"T{i:02d}": DeepDiveResult(
            ticker=f"T{i:02d}",
            catalyst_subscore=min(10 + i, 40),  # cap at max 40
            catalyst_reasoning=f"catalyst reasoning {i}",
            sector_momentum_subscore=min(10 + i, 35),  # cap at max 35
            sector_momentum_reasoning=f"momentum reasoning {i}",
            macro_subscore=15 + (i % 2) * 5,  # cycle through 15, 20, alternating (never 25 for simplicity)
            macro_reasoning=f"macro reasoning {i}",
            citations=[Citation(
                source="test",
                headline=f"headline {i}",
                url=f"http://example.com/{i}",
                published_at="2026-10-01",
            )],
        )
        for i in range(25)
    }
    fake_session = FakeHaikuSession(shortlist=large_shortlist, deep_dives=deep_dives)

    # Stub sourcing with a few items, plus a Bhavcopy-style close price for
    # every T00-T24 ticker so entry-price resolution succeeds for all of
    # them (otherwise every idea would be dropped for lacking a buy price --
    # see run_orchestrator._resolve_entry_price).
    import datetime as dt
    stub_items = [
        NormalizedItem(
            source="stub",
            headline="dummy headline",
            url="http://example.com",
            published_at=dt.datetime.now(dt.timezone.utc),
            snippet="dummy snippet",
            ticker=None,
        )
    ] + [
        NormalizedItem(
            source="nse_bhavcopy",
            headline=f"T{i:02d} EOD",
            url=f"http://example.com/T{i:02d}",
            published_at=dt.datetime.now(dt.timezone.utc),
            snippet=f"T{i:02d} EOD price",
            ticker=f"T{i:02d}",
            close=100.0 + i,
        )
        for i in range(25)
    ]

    class StubAgg:
        async def fetch_all(self):
            return stub_items, []

    orchestrator = RunOrchestrator(
        aggregator=StubAgg(),
        haiku_session=fake_session,
    )

    # Execute
    with db_session() as conn:
        run_id = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            ("2026-10-12T00:00:00+00:00",),
        ).lastrowid

    await orchestrator.execute_run(run_id)

    # Verify candidates table has exactly 18 rows (MAX_SHORTLIST_SIZE)
    with db_session() as conn:
        candidates = get_candidates_for_run(conn, run_id)
        ideas = conn.execute(
            "SELECT ticker FROM ideas WHERE run_id = ? ORDER BY rank",
            (run_id,),
        ).fetchall()

    assert len(candidates) == 18, f"expected 18 candidates, got {len(candidates)}"
    # Slice 9: ideas are capped at 10 (top 10 by score after assembly)
    assert len(ideas) == 10, f"expected 10 ideas (capped by assembly), got {len(ideas)}"


@pytest.mark.asyncio
async def test_full_run_one_deep_dive_call_per_shortlisted_ticker(data_dir):
    """Verify one deep_dive call per shortlisted ticker."""

    fake_session = FakeHaikuSession()  # Default 3-ticker shortlist

    class StubAgg:
        async def fetch_all(self):
            return [], []

    orchestrator = RunOrchestrator(
        aggregator=StubAgg(),
        haiku_session=fake_session,
    )

    with db_session() as conn:
        run_id = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            ("2026-10-12T00:00:00+00:00",),
        ).lastrowid

    await orchestrator.execute_run(run_id)

    # Verify exactly one sweep call and one deep_dive per shortlisted ticker
    assert len(fake_session.sweep_calls) == 1
    assert len(fake_session.deep_dive_calls) == 3  # RELIANCE, TATAMOTORS, INFY


@pytest.mark.asyncio
async def test_full_run_per_stock_failure_skip_and_continue(data_dir):
    """Verify per-stock failure doesn't abort the run."""

    fake_session = FakeHaikuSession(fail_tickers={"TATAMOTORS"})

    # Bhavcopy-style close prices for the surviving tickers (RELIANCE, INFY)
    # so entry-price resolution succeeds -- TATAMOTORS fails the deep-dive
    # anyway so its missing price is irrelevant here.
    import datetime as dt
    bhav_items = [
        NormalizedItem(
            source="nse_bhavcopy", headline=f"{t} EOD", url=f"http://example.com/{t}",
            published_at=dt.datetime.now(dt.timezone.utc), snippet=f"{t} EOD price",
            ticker=t, close=close,
        )
        for t, close in [("RELIANCE", 2900.0), ("INFY", 1550.0)]
    ]

    class StubAgg:
        async def fetch_all(self):
            return bhav_items, []

    orchestrator = RunOrchestrator(
        aggregator=StubAgg(),
        haiku_session=fake_session,
    )

    with db_session() as conn:
        run_id = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            ("2026-10-12T00:00:00+00:00",),
        ).lastrowid

    await orchestrator.execute_run(run_id)

    # Verify run completed (not error)
    with db_session() as conn:
        run_row = conn.execute(
            "SELECT status FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
        candidates = get_candidates_for_run(conn, run_id)
        ideas = conn.execute(
            "SELECT ticker FROM ideas WHERE run_id = ? ORDER BY rank",
            (run_id,),
        ).fetchall()

    assert run_row["status"] == "complete"
    # Only 2 candidates should survive (TATAMOTORS failed and was skipped)
    assert len(candidates) == 2
    assert len(ideas) == 2
    tickers = {row["ticker"] for row in ideas}
    assert tickers == {"RELIANCE", "INFY"}


@pytest.mark.asyncio
async def test_full_run_ideas_table_populated_with_real_subscores(data_dir):
    """Verify ideas table contains real sub-scores from FakeHaikuSession."""

    fake_session = FakeHaikuSession()

    # Bhavcopy-style close prices for the default shortlist (RELIANCE,
    # TATAMOTORS, INFY) so entry-price resolution succeeds for all three.
    import datetime as dt
    bhav_items = [
        NormalizedItem(
            source="nse_bhavcopy", headline=f"{t} EOD", url=f"http://example.com/{t}",
            published_at=dt.datetime.now(dt.timezone.utc), snippet=f"{t} EOD price",
            ticker=t, close=close,
        )
        for t, close in [("RELIANCE", 2900.0), ("TATAMOTORS", 950.0), ("INFY", 1550.0)]
    ]

    class StubAgg:
        async def fetch_all(self):
            return bhav_items, []

    orchestrator = RunOrchestrator(
        aggregator=StubAgg(),
        haiku_session=fake_session,
    )

    with db_session() as conn:
        run_id = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            ("2026-10-12T00:00:00+00:00",),
        ).lastrowid

    await orchestrator.execute_run(run_id)

    # Verify sub-scores and computed score/tier match the fake session's canned values
    with db_session() as conn:
        ideas = conn.execute(
            "SELECT ticker, sub_score_catalyst, sub_score_momentum, sub_score_macro, score, tier "
            "FROM ideas WHERE run_id = ? ORDER BY rank",
            (run_id,),
        ).fetchall()

    assert len(ideas) == 3

    # Check RELIANCE (catalyst=32, sector=28, macro=20 → score=80 → green)
    reliance = [i for i in ideas if i["ticker"] == "RELIANCE"][0]
    assert reliance["sub_score_catalyst"] == 32
    assert reliance["sub_score_momentum"] == 28
    assert reliance["sub_score_macro"] == 20
    assert reliance["score"] == 80
    assert reliance["tier"] == "green"

    # Check TATAMOTORS (catalyst=24, sector=18, macro=15 → score=57 → yellow)
    tata = [i for i in ideas if i["ticker"] == "TATAMOTORS"][0]
    assert tata["sub_score_catalyst"] == 24
    assert tata["sub_score_momentum"] == 18
    assert tata["sub_score_macro"] == 15
    assert tata["score"] == 57
    assert tata["tier"] == "yellow"

    # Check INFY (catalyst=14, sector=12, macro=20 → score=46 → red)
    infy = [i for i in ideas if i["ticker"] == "INFY"][0]
    assert infy["sub_score_catalyst"] == 14
    assert infy["sub_score_momentum"] == 12
    assert infy["sub_score_macro"] == 20
    assert infy["score"] == 46
    assert infy["tier"] == "red"
