"""Tests for Slice 6: Negative filtering (pump-and-dump + stale-news).

Table-driven tests for each major gate, plus integration tests confirming
the exact FilterResult shape and the combined logic flow.
"""

import pytest
from dataclasses import dataclass
from datetime import date, timedelta

from app.negative_filters import (
    evaluate_negative_filters,
    evaluate_pump_and_dump,
    evaluate_stale_news,
    trading_days_between,
    FilterResult,
)


@dataclass
class FakeCandidate:
    """Test double satisfying DeepDiveCandidateLike protocol."""
    ticker: str = "TEST"
    daily_volume: int | None = None
    avg_20day_volume: int | None = None
    institutional_ownership_pct: float | None = None
    promotional_chatter_flag: bool = False
    catalyst_mentioned_date: str | None = None
    nse_announcement_date: str | None = None


class TestTradingDaysBetween:
    """Tests for the weekday-counting helper."""

    def test_same_day_returns_zero(self):
        d = date(2026, 10, 12)
        assert trading_days_between(d, d) == 0

    def test_adjacent_weekdays(self):
        # Oct 12 (Mon) to Oct 13 (Tue)
        assert trading_days_between(date(2026, 10, 12), date(2026, 10, 13)) == 1

    def test_skip_weekend(self):
        # Oct 12 (Mon) to Oct 14 (Wed) = 2 trading days
        result = trading_days_between(date(2026, 10, 12), date(2026, 10, 14))
        assert result == 2

    def test_reversed_order(self):
        # Should handle either direction
        assert trading_days_between(date(2026, 10, 14), date(2026, 10, 12)) == 2

    def test_week_span_skips_weekend(self):
        # Oct 5 (Mon) to Oct 12 (Mon) = 5 trading days
        result = trading_days_between(date(2026, 10, 5), date(2026, 10, 12))
        assert result == 5


class TestPumpAndDumpThresholds:
    """Table-driven tests for pump-and-dump exclusion criteria."""

    @pytest.mark.parametrize("daily_vol,avg_20d_vol,inst_own_pct,chatter,expected", [
        # Thin volume on absolute floor
        (99_999, None, 2.0, True, True),      # Below 100k absolute floor
        (100_000, None, 2.0, True, False),    # Exactly at floor (not < floor)
        # Thin volume on relative floor
        (150_000, 600_000, 2.0, True, True),  # 150k < 0.3*600k (180k)
        (200_000, 600_000, 2.0, True, False), # 200k >= 180k relative floor
        # Institutional ownership threshold
        (50_000, None, 10.0, True, False),    # Above 5% threshold (fails ownership leg)
        (50_000, None, 4.9, True, True),      # Just under 5% threshold
        (50_000, None, None, True, True),     # Unknown ownership treated as "none"
        # Promotional chatter (AND requirement)
        (50_000, None, 2.0, False, False),    # No chatter (fails chatter leg despite other signals)
    ])
    def test_pump_and_dump_table(self, daily_vol, avg_20d_vol, inst_own_pct, chatter, expected):
        """Pump-and-dump exclusion: ALL THREE signals must fire together."""
        c = FakeCandidate(
            daily_volume=daily_vol,
            avg_20day_volume=avg_20d_vol,
            institutional_ownership_pct=inst_own_pct,
            promotional_chatter_flag=chatter,
        )
        assert evaluate_pump_and_dump(c) == expected


class TestStalenessThresholds:
    """Table-driven tests for stale-news exclusion criteria."""

    def _days_back(self, run_date: date, trading_days_back: int) -> date:
        """Calculate a date N trading days in the past from run_date."""
        candidate = run_date
        count = 0
        while count < trading_days_back:
            candidate -= timedelta(days=1)
            if candidate.weekday() < 5:  # Weekday
                count += 1
        return candidate

    def test_catalyst_within_window(self):
        """Catalyst exactly at 5-day window edge should not be stale."""
        run_date = date(2026, 10, 12)
        catalyst_date = self._days_back(run_date, 5)  # Oct 5

        c = FakeCandidate(
            catalyst_mentioned_date=catalyst_date.isoformat(),
            nse_announcement_date=None,
        )

        assert evaluate_stale_news(c, run_date) == False

    def test_catalyst_past_window(self):
        """Catalyst 6 days old (past window) should be stale."""
        run_date = date(2026, 10, 12)
        catalyst_date = self._days_back(run_date, 6)  # 6 days back

        c = FakeCandidate(
            catalyst_mentioned_date=catalyst_date.isoformat(),
            nse_announcement_date=None,
        )

        assert evaluate_stale_news(c, run_date) == True

    def test_stale_catalyst_but_fresh_announcement(self):
        """Stale catalyst with fresh NSE announcement should not be stale."""
        run_date = date(2026, 10, 12)
        catalyst_date = self._days_back(run_date, 10)  # 10 days old
        announcement_date = self._days_back(run_date, 3)  # 3 days old (within window)

        c = FakeCandidate(
            catalyst_mentioned_date=catalyst_date.isoformat(),
            nse_announcement_date=announcement_date.isoformat(),
        )

        assert evaluate_stale_news(c, run_date) == False

    def test_stale_catalyst_stale_announcement(self):
        """Stale catalyst with equally stale announcement should be stale."""
        run_date = date(2026, 10, 12)
        catalyst_date = self._days_back(run_date, 10)  # 10 days old
        announcement_date = self._days_back(run_date, 8)  # 8 days old (outside window)

        c = FakeCandidate(
            catalyst_mentioned_date=catalyst_date.isoformat(),
            nse_announcement_date=announcement_date.isoformat(),
        )

        assert evaluate_stale_news(c, run_date) == True

    def test_stale_catalyst_no_announcement(self):
        """Stale catalyst with no announcement should be stale."""
        run_date = date(2026, 10, 12)
        catalyst_date = self._days_back(run_date, 10)  # 10 days old

        c = FakeCandidate(
            catalyst_mentioned_date=catalyst_date.isoformat(),
            nse_announcement_date=None,
        )

        assert evaluate_stale_news(c, run_date) == True


class TestFilterResultContract:
    """Tests for the FilterResult shape and exclusion_reason invariant."""

    def test_pump_and_dump_excluded(self):
        """Pump-and-dump candidate returns excluded=True with reason."""
        run_date = date(2026, 10, 12)
        c = FakeCandidate(
            daily_volume=45_000,
            avg_20day_volume=None,
            institutional_ownership_pct=2.0,
            promotional_chatter_flag=True,
        )

        result = evaluate_negative_filters(c, run_date)
        assert result.excluded == True
        assert "pump_and_dump" in result.exclusion_reason
        assert "thin_volume=True" in result.exclusion_reason
        assert "no_institutional_ownership=True" in result.exclusion_reason
        assert "promotional_chatter_flag=True" in result.exclusion_reason

    def test_stale_news_excluded(self):
        """Stale-news candidate returns excluded=True with reason."""
        run_date = date(2026, 10, 12)
        catalyst_date = date(2026, 9, 28)  # Old

        c = FakeCandidate(
            daily_volume=500_000,
            avg_20day_volume=500_000,
            institutional_ownership_pct=15.0,
            promotional_chatter_flag=False,
            catalyst_mentioned_date=catalyst_date.isoformat(),
            nse_announcement_date=None,
        )

        result = evaluate_negative_filters(c, run_date)
        assert result.excluded == True
        assert "stale_news" in result.exclusion_reason

    def test_clean_candidate_not_excluded(self):
        """Clean candidate returns excluded=False with None reason."""
        run_date = date(2026, 10, 12)

        c = FakeCandidate(
            daily_volume=500_000,
            avg_20day_volume=500_000,
            institutional_ownership_pct=15.0,
            promotional_chatter_flag=False,
            catalyst_mentioned_date="2026-10-12",
            nse_announcement_date="2026-10-11",
        )

        result = evaluate_negative_filters(c, run_date)
        assert result.excluded == False
        assert result.exclusion_reason is None

    def test_both_triggers_pump_and_dump_precedence(self):
        """When both triggers fire, pump-and-dump takes precedence."""
        run_date = date(2026, 10, 12)

        c = FakeCandidate(
            daily_volume=45_000,
            avg_20day_volume=None,
            institutional_ownership_pct=2.0,
            promotional_chatter_flag=True,
            catalyst_mentioned_date="2026-09-28",  # Stale
            nse_announcement_date=None,
        )

        result = evaluate_negative_filters(c, run_date)
        assert result.excluded == True
        assert "pump_and_dump" in result.exclusion_reason  # Not "stale_news"
