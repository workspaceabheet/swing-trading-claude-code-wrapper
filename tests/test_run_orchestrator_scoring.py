"""Slice 5: Integration test for scoring module wired into orchestrator.

Verifies that orchestrator-persisted score/tier for every idea exactly matches
what compute_score produces standalone for that idea's persisted sub-scores.
"""

import pytest
from app.db import db_session
from app.fakes.fake_sessions import FakeHaikuSession
from app.run_orchestrator import RunOrchestrator
from app.scoring import compute_score


@pytest.mark.asyncio
async def test_fake_run_scores_match_standalone_compute_score(data_dir):
    """Full fake-driven pipeline: verify persisted score/tier match compute_score.

    This proves orchestrator wiring didn't silently diverge from the pure
    function (e.g., no accidental double-counting, no stale cached tier).
    """
    from app.sources.base import NormalizedItem
    from datetime import datetime, timezone

    fake_session = FakeHaikuSession()  # Default 3-ticker shortlist

    # Stub aggregator that returns at least one item to feed into the sweep,
    # plus Bhavcopy-style close prices for the default shortlist (RELIANCE,
    # TATAMOTORS, INFY) so entry-price resolution succeeds for all three
    # (otherwise every idea would be dropped for lacking a buy price).
    stub_items = [
        NormalizedItem(
            source="test",
            headline="test headline",
            url="http://example.com",
            published_at=datetime.now(timezone.utc),
            snippet="test snippet",
            ticker=None,
        )
    ] + [
        NormalizedItem(
            source="nse_bhavcopy",
            headline=f"{t} EOD",
            url=f"http://example.com/{t}",
            published_at=datetime.now(timezone.utc),
            snippet=f"{t} EOD price",
            ticker=t,
            close=close,
        )
        for t, close in [("RELIANCE", 2900.0), ("TATAMOTORS", 950.0), ("INFY", 1550.0)]
    ]

    class StubAgg:
        async def fetch_all(self):
            return stub_items, []

    orchestrator = RunOrchestrator(
        aggregator=StubAgg(),
        haiku_session=fake_session,
    )

    # Execute the run
    with db_session() as conn:
        run_id = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            ("2026-10-12T00:00:00+00:00",),
        ).lastrowid

    await orchestrator.execute_run(run_id)

    # Verify persisted score/tier match standalone compute_score
    with db_session() as conn:
        ideas = conn.execute(
            "SELECT ticker, sub_score_catalyst, sub_score_momentum, sub_score_macro, score, tier "
            "FROM ideas WHERE run_id = ? ORDER BY rank",
            (run_id,),
        ).fetchall()

    assert len(ideas) == 3

    for idea in ideas:
        # Call compute_score standalone with the persisted sub-scores
        standalone_result = compute_score(
            idea["sub_score_catalyst"],
            idea["sub_score_momentum"],
            idea["sub_score_macro"],
        )

        # Verify persisted score/tier match the standalone result exactly
        assert idea["score"] == standalone_result.score, (
            f"Ticker {idea['ticker']}: persisted score {idea['score']} != "
            f"compute_score result {standalone_result.score}"
        )
        assert idea["tier"] == standalone_result.tier, (
            f"Ticker {idea['ticker']}: persisted tier {idea['tier']!r} != "
            f"compute_score result {standalone_result.tier!r}"
        )
