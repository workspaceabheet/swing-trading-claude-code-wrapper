"""Unit + integration tests for entry/target/hold_days (tech-spec §4 FR6, §8).

Covers:
- Entry-price resolution from a ticker's Bhavcopy close price in its
  DeepDiveContext (ticker found vs. not found).
- Target-price arithmetic (entry * (1 + expected_move_pct/100), rounded).
- Full fake-driven orchestrator run produces non-zero, non-placeholder
  entry/target/hold_days for at least one real idea.
"""

import datetime as dt

import pytest

from app.agent.sessions import DeepDiveContext, FinalCandidate, Citation
from app.assembly import assemble
from app.db import db_session
from app.fakes.fake_sessions import FakeHaikuSession
from app.run_orchestrator import (
    RunOrchestrator,
    _resolve_entry_price,
    _compute_target_price,
)
from app.sources.base import NormalizedItem


def _bhav_item(ticker: str, close: float) -> NormalizedItem:
    return NormalizedItem(
        source="nse_bhavcopy",
        headline=f"{ticker} EOD",
        url=f"https://example.com/nse_bhavcopy/{ticker}",
        published_at=dt.datetime.now(dt.timezone.utc),
        snippet=f"{ticker} EOD price",
        ticker=ticker,
        close=close,
    )


class TestResolveEntryPrice:
    def test_ticker_found_returns_bhavcopy_close(self):
        """A ticker with a matching Bhavcopy item resolves to its close price."""
        context = DeepDiveContext(
            ticker="RELIANCE",
            items=[_bhav_item("RELIANCE", 2904.50)],
        )
        assert _resolve_entry_price(context) == 2904.50

    def test_ticker_not_found_returns_none(self):
        """No matching Bhavcopy item for this ticker -> None (never fabricated)."""
        context = DeepDiveContext(
            ticker="RELIANCE",
            items=[_bhav_item("TATAMOTORS", 950.0)],  # a different ticker
        )
        assert _resolve_entry_price(context) is None

    def test_empty_context_returns_none(self):
        """No items at all -> None."""
        context = DeepDiveContext(ticker="RELIANCE", items=[])
        assert _resolve_entry_price(context) is None

    def test_none_context_returns_none(self):
        """Missing context entirely (ticker had no context built) -> None."""
        assert _resolve_entry_price(None) is None

    def test_general_market_item_with_no_ticker_is_ignored(self):
        """A ticker=None general-market item's close is never mistaken for
        this ticker's own Bhavcopy price -- only an exact ticker match on
        the item counts."""
        context = DeepDiveContext(
            ticker="RELIANCE",
            items=[
                NormalizedItem(
                    source="moneycontrol_rss",
                    headline="market update",
                    url="https://example.com/market",
                    published_at=dt.datetime.now(dt.timezone.utc),
                    snippet="general market snippet",
                    ticker=None,
                    close=9999.0,  # should never be picked up for RELIANCE
                )
            ],
        )
        assert _resolve_entry_price(context) is None

    def test_picks_the_matching_item_among_several(self):
        """When the context has several items (general + other tickers +
        this ticker), only this ticker's own Bhavcopy item is used."""
        context = DeepDiveContext(
            ticker="INFY",
            items=[
                _bhav_item("RELIANCE", 2900.0),
                NormalizedItem(
                    source="moneycontrol_rss", headline="general", url="https://x",
                    published_at=dt.datetime.now(dt.timezone.utc), snippet="s", ticker=None,
                ),
                _bhav_item("INFY", 1555.75),
            ],
        )
        assert _resolve_entry_price(context) == 1555.75


class TestComputeTargetPrice:
    @pytest.mark.parametrize(
        "entry,expected_move_pct,expected_target",
        [
            (100.0, 10.0, 110.0),
            (100.0, -5.0, 95.0),
            (2904.50, 8.5, 3151.38),  # 2904.5 * 1.085 = 3151.3825 -> rounds to 3151.38
            (1550.0, 0.0, 1550.0),
            (999.99, 3.333, 1033.32),  # rounding to 2 decimal places
            (50.0, -20.0, 40.0),
        ],
    )
    def test_target_arithmetic_and_rounding(self, entry, expected_move_pct, expected_target):
        assert _compute_target_price(entry, expected_move_pct) == expected_target

    def test_target_is_a_float_rounded_to_two_decimals(self):
        target = _compute_target_price(333.335, 1.0)
        # round(333.335 * 1.01, 2) -- just verify it's rounded, not an exact
        # literal (banker's rounding/float repr quirks aside).
        assert target == round(333.335 * 1.01, 2)


class TestAssemblyDropsUnresolvedEntry:
    def _candidate(self, ticker, entry, score=80, tier="green"):
        return FinalCandidate(
            ticker=ticker,
            score=score,
            tier=tier,
            sub_score_catalyst=30,
            sub_score_momentum=30,
            sub_score_macro=20,
            citations=[Citation(
                source="test", headline="h", url="https://example.com/c",
                published_at="2026-10-10",
            )],
            polished_rationale="rationale",
            ranking_commentary_fragment="fragment",
            entry=entry,
            target=entry * 1.05 if entry else 0.0,
            hold_days=7,
        )

    def test_zero_entry_is_dropped_before_ranking(self):
        """A candidate with no resolvable entry price (entry=0.0, the
        dataclass default -- never a real Bhavcopy price) is dropped by
        assemble(), same as the existing no-citation hard constraint."""
        candidates = [
            self._candidate("GOOD", entry=100.0),
            self._candidate("NOPRICE", entry=0.0),
        ]
        ideas = assemble(candidates)
        tickers = {idea.ticker for idea in ideas}
        assert tickers == {"GOOD"}
        assert "NOPRICE" not in tickers


@pytest.mark.asyncio
async def test_full_fake_run_produces_real_nonzero_entry_target_hold_days(data_dir):
    """Integration: a full fake-driven orchestrator run produces genuinely
    non-zero, non-placeholder entry/target/hold_days for real ideas --
    proving the end-to-end wiring (Bhavcopy close -> entry, Haiku
    expected_move_pct -> target, Haiku hold_days -> persisted hold_days),
    not the old hardcoded 0.0/0.0/0 placeholder."""
    fake_session = FakeHaikuSession()  # Default shortlist: RELIANCE, TATAMOTORS, INFY

    bhav_items = [
        _bhav_item("RELIANCE", 2900.0),
        _bhav_item("TATAMOTORS", 950.0),
        _bhav_item("INFY", 1550.0),
    ]

    class StubAgg:
        async def fetch_all(self):
            return bhav_items, []

    orchestrator = RunOrchestrator(aggregator=StubAgg(), haiku_session=fake_session)

    with db_session() as conn:
        run_id = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            ("2026-10-12T00:00:00+00:00",),
        ).lastrowid

    await orchestrator.execute_run(run_id)

    with db_session() as conn:
        ideas = conn.execute(
            "SELECT ticker, entry, target, hold_days FROM ideas WHERE run_id = ? "
            "AND excluded = 0 ORDER BY rank",
            (run_id,),
        ).fetchall()

    assert len(ideas) > 0, "no ideas produced by the run"

    reliance = next(i for i in ideas if i["ticker"] == "RELIANCE")
    assert reliance["entry"] == 2900.0  # matches the Bhavcopy close fed in above
    assert reliance["entry"] != 0.0
    assert reliance["target"] != 0.0
    assert reliance["target"] == round(2900.0 * 1.085, 2)  # expected_move_pct=8.5 in fake data
    assert reliance["hold_days"] == 9  # hold_days from fake RELIANCE deep-dive
    assert reliance["hold_days"] != 0

    for idea in ideas:
        assert idea["entry"] > 0, f"{idea['ticker']}: entry is non-positive placeholder"
        assert idea["hold_days"] > 0, f"{idea['ticker']}: hold_days is placeholder 0"
