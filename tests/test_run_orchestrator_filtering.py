"""Integration tests for Slice 6: Negative filtering in the full orchestrator pipeline.

Tests that excluded candidates are persisted with exclusion_reason but do not
appear in the final user-facing ideas list.
"""

import pytest
import sqlite3
from datetime import datetime, timezone, date

from app.agent.sessions import DeepDiveResult, Citation, ShortlistCandidate
from app.fakes.fake_sessions import FakeHaikuSession, DEFAULT_SHORTLIST
from app.run_orchestrator import RunOrchestrator
from app.db import db_session, get_candidates_for_run
from app.sources.base import NormalizedItem


@pytest.fixture
def fake_sources_list():
    """Minimal fake sourcing data for orchestrator test.

    Includes Bhavcopy-style close prices for every ticker used across this
    module's tests (CLEAN, PUMP, FRESH, STALE) so entry-price resolution
    succeeds for surviving candidates -- otherwise they'd be dropped before
    ever reaching the ideas table for lacking a buy price.
    """
    items = [
        NormalizedItem(
            source="moneycontrol_rss",
            headline="Tech stock news",
            url="https://example.com/1",
            published_at=datetime.now(timezone.utc),
            snippet="A tech stock update",
            ticker=None,
            close=None,
            prev_close=None,
            volume=None,
            pe_ratio=None,
            market_cap_cr=None,
            indicator_name=None,
            indicator_value=None,
        ),
    ]
    for ticker, close in [
        ("CLEAN", 500.0), ("PUMP", 50.0), ("FRESH", 300.0), ("STALE", 200.0),
    ]:
        items.append(
            NormalizedItem(
                source="nse_bhavcopy",
                headline=f"{ticker} EOD",
                url=f"https://example.com/{ticker}",
                published_at=datetime.now(timezone.utc),
                snippet=f"{ticker} EOD price",
                ticker=ticker,
                close=close,
            )
        )
    return items


@pytest.mark.asyncio
async def test_fake_run_excludes_pump_and_dump_candidate(fake_sources_list):
    """A pump-and-dump-shaped candidate is excluded from final output but persisted for audit."""
    # Configure FakeHaikuSession with one pump-and-dump-triggering candidate and one clean
    clean_candidate = DeepDiveResult(
        ticker="CLEAN",
        catalyst_subscore=30,
        catalyst_reasoning="Strong catalyst",
        sector_momentum_subscore=25,
        sector_momentum_reasoning="Good momentum",
        macro_subscore=20,
        macro_reasoning="Neutral macro",
        citations=[Citation(
            source="moneycontrol_rss",
            headline="Good news",
            url="https://example.com/clean",
            published_at="2026-10-12",
        )],
        daily_volume=500_000,
        avg_20day_volume=500_000,
        institutional_ownership_pct=25.0,
        promotional_chatter_flag=False,
        catalyst_mentioned_date="2026-10-12",
        nse_announcement_date="2026-10-11",
    )

    pump_and_dump_candidate = DeepDiveResult(
        ticker="PUMP",
        catalyst_subscore=20,
        catalyst_reasoning="Weak catalyst with chatter",
        sector_momentum_subscore=15,
        sector_momentum_reasoning="Weak momentum",
        macro_subscore=20,
        macro_reasoning="Neutral macro",
        citations=[Citation(
            source="moneycontrol_rss",
            headline="Hyped news",
            url="https://example.com/pump",
            published_at="2026-10-12",
        )],
        daily_volume=40_000,
        avg_20day_volume=None,
        institutional_ownership_pct=1.0,  # Well below 5% threshold
        promotional_chatter_flag=True,    # All three signals present
        catalyst_mentioned_date="2026-10-12",
        nse_announcement_date=None,
    )

    shortlist = [
        ShortlistCandidate(ticker="CLEAN", reason="Strong fundamentals"),
        ShortlistCandidate(ticker="PUMP", reason="Hyped chatter"),
    ]

    deep_dives = {
        "CLEAN": clean_candidate,
        "PUMP": pump_and_dump_candidate,
    }

    fake_session = FakeHaikuSession(
        shortlist=shortlist,
        deep_dives=deep_dives,
    )

    orchestrator = RunOrchestrator(haiku_session=fake_session)

    # Create a run row manually for testing
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), "running"),
        )
        run_id = cursor.lastrowid

    # Insert fake sourcing items
    with db_session() as conn:
        from app.db import insert_sweep_items
        insert_sweep_items(conn, run_id, fake_sources_list)

    # Execute the LLM stages
    await orchestrator._run_llm_stages(run_id)

    # Query the ideas table to verify only CLEAN appears
    with db_session() as conn:
        ideas = conn.execute(
            "SELECT ticker, excluded, exclusion_reason FROM ideas WHERE run_id = ? ORDER BY excluded ASC",
            (run_id,),
        ).fetchall()

    # Should have two rows: CLEAN (excluded=0), PUMP (excluded=1)
    assert len(ideas) == 2

    clean_idea = ideas[0]
    pump_idea = ideas[1]

    assert clean_idea["ticker"] == "CLEAN"
    assert clean_idea["excluded"] == 0
    assert clean_idea["exclusion_reason"] is None

    assert pump_idea["ticker"] == "PUMP"
    assert pump_idea["excluded"] == 1
    assert "pump_and_dump" in pump_idea["exclusion_reason"]
    assert "thin_volume=True" in pump_idea["exclusion_reason"]
    assert "no_institutional_ownership=True" in pump_idea["exclusion_reason"]
    assert "promotional_chatter_flag=True" in pump_idea["exclusion_reason"]


@pytest.mark.asyncio
async def test_fake_run_excludes_stale_news_candidate(fake_sources_list):
    """A stale-news-shaped candidate is excluded from final output but persisted for audit."""
    clean_candidate = DeepDiveResult(
        ticker="FRESH",
        catalyst_subscore=30,
        catalyst_reasoning="Recent catalyst",
        sector_momentum_subscore=25,
        sector_momentum_reasoning="Good momentum",
        macro_subscore=20,
        macro_reasoning="Neutral macro",
        citations=[Citation(
            source="moneycontrol_rss",
            headline="Fresh news",
            url="https://example.com/fresh",
            published_at="2026-10-12",
        )],
        daily_volume=500_000,
        avg_20day_volume=500_000,
        institutional_ownership_pct=25.0,
        promotional_chatter_flag=False,
        catalyst_mentioned_date="2026-10-12",
        nse_announcement_date="2026-10-11",
    )

    stale_candidate = DeepDiveResult(
        ticker="STALE",
        catalyst_subscore=28,
        catalyst_reasoning="Old catalyst but clean signals",
        sector_momentum_subscore=24,
        sector_momentum_reasoning="Good momentum",
        macro_subscore=20,
        macro_reasoning="Neutral macro",
        citations=[Citation(
            source="moneycontrol_rss",
            headline="Old news",
            url="https://example.com/stale",
            published_at="2026-09-28",
        )],
        daily_volume=500_000,
        avg_20day_volume=500_000,
        institutional_ownership_pct=25.0,
        promotional_chatter_flag=False,
        catalyst_mentioned_date="2026-09-28",  # 10+ trading days old
        nse_announcement_date=None,  # No fresh corroboration
    )

    shortlist = [
        ShortlistCandidate(ticker="FRESH", reason="Recent catalyst"),
        ShortlistCandidate(ticker="STALE", reason="Old catalyst"),
    ]

    deep_dives = {
        "FRESH": clean_candidate,
        "STALE": stale_candidate,
    }

    fake_session = FakeHaikuSession(
        shortlist=shortlist,
        deep_dives=deep_dives,
    )

    orchestrator = RunOrchestrator(haiku_session=fake_session)

    # Create a run row
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), "running"),
        )
        run_id = cursor.lastrowid

    # Insert fake sourcing items
    with db_session() as conn:
        from app.db import insert_sweep_items
        insert_sweep_items(conn, run_id, fake_sources_list)

    # Execute the LLM stages
    await orchestrator._run_llm_stages(run_id)

    # Query the ideas table
    with db_session() as conn:
        ideas = conn.execute(
            "SELECT ticker, excluded, exclusion_reason FROM ideas WHERE run_id = ? ORDER BY excluded ASC",
            (run_id,),
        ).fetchall()

    assert len(ideas) == 2

    fresh_idea = ideas[0]
    stale_idea = ideas[1]

    assert fresh_idea["ticker"] == "FRESH"
    assert fresh_idea["excluded"] == 0
    assert fresh_idea["exclusion_reason"] is None

    assert stale_idea["ticker"] == "STALE"
    assert stale_idea["excluded"] == 1
    assert "stale_news" in stale_idea["exclusion_reason"]


@pytest.mark.asyncio
async def test_fake_run_keeps_clean_candidate(fake_sources_list):
    """A fully clean candidate with no filter triggers survives to final output."""
    clean_candidate = DeepDiveResult(
        ticker="CLEAN",
        catalyst_subscore=32,
        catalyst_reasoning="Strong catalyst",
        sector_momentum_subscore=28,
        sector_momentum_reasoning="Strong momentum",
        macro_subscore=20,
        macro_reasoning="Neutral macro",
        citations=[Citation(
            source="moneycontrol_rss",
            headline="Good news",
            url="https://example.com/clean",
            published_at="2026-10-12",
        )],
        daily_volume=5_200_000,
        avg_20day_volume=5_100_000,
        institutional_ownership_pct=25.5,
        promotional_chatter_flag=False,
        catalyst_mentioned_date="2026-10-10",
        nse_announcement_date="2026-10-09",
    )

    shortlist = [
        ShortlistCandidate(ticker="CLEAN", reason="Strong fundamentals"),
    ]

    deep_dives = {
        "CLEAN": clean_candidate,
    }

    fake_session = FakeHaikuSession(
        shortlist=shortlist,
        deep_dives=deep_dives,
    )

    orchestrator = RunOrchestrator(haiku_session=fake_session)

    # Create a run row
    with db_session() as conn:
        cursor = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, ?)",
            (datetime.now(timezone.utc).isoformat(), "running"),
        )
        run_id = cursor.lastrowid

    # Insert fake sourcing items
    with db_session() as conn:
        from app.db import insert_sweep_items
        insert_sweep_items(conn, run_id, fake_sources_list)

    # Execute the LLM stages
    await orchestrator._run_llm_stages(run_id)

    # Query the ideas table
    with db_session() as conn:
        ideas = conn.execute(
            "SELECT ticker, excluded, exclusion_reason, score FROM ideas WHERE run_id = ?",
            (run_id,),
        ).fetchall()

    assert len(ideas) == 1

    idea = ideas[0]
    assert idea["ticker"] == "CLEAN"
    assert idea["excluded"] == 0
    assert idea["exclusion_reason"] is None
    assert idea["score"] == 80  # 32 + 28 + 20
