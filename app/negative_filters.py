"""Slice 6: Negative filtering module (pump-and-dump + stale-news exclusion, within FR4).

This module implements two negative-filter gates that exclude candidates from the
final idea list based on:
1. Pump-and-dump indicators: thin volume AND no institutional ownership AND promotional chatter
2. Stale news: catalyst more than 5 trading days old (unless corroborated by a fresher NSE announcement)

All thresholds are defined as module-level constants, tunable for future refinement.
This module is pure (no LLM/SDK/network/DB imports) and stateless, mirroring scoring.py's discipline.

See slice-6.md §2-§3 for the full design rationale and threshold justifications.
"""

from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

# Threshold constants (tunable, per slice-6.md §2)
MIN_ABSOLUTE_VOLUME = 100_000  # Absolute floor for daily volume (shares)
MIN_RELATIVE_VOLUME_RATIO = 0.3  # Relative floor: min daily / avg_20day
MIN_INSTITUTIONAL_OWNERSHIP_PCT = 5.0  # Institutional ownership threshold (percent)
STALENESS_WINDOW_TRADING_DAYS = 5  # News older than this is "stale"


def _safe_parse_date(value: str | None) -> date | None:
    """Parses an ISO date string, or returns None for anything unparseable.

    Real Haiku output has been observed to emit the literal string "null"
    (a valid JSON string, not JSON null) for an unknown/absent date field,
    which `date.fromisoformat` would otherwise raise on and crash the whole
    run. Any value that isn't a genuine ISO date is treated the same as a
    genuinely missing date -- "unknown," not an error.
    """
    if not value:
        return None
    try:
        return date.fromisoformat(value)
    except ValueError:
        return None


class DeepDiveCandidateLike(Protocol):
    """Structural contract this module needs from Slice 4's DeepDiveResult.

    See slice-6.md §1 for the full field table and provenance of each field.
    This Protocol allows any object matching this shape (DeepDiveResult,
    test doubles, etc.) to be passed to evaluate_negative_filters.
    """
    ticker: str
    daily_volume: int | None
    avg_20day_volume: int | None
    institutional_ownership_pct: float | None
    promotional_chatter_flag: bool
    catalyst_mentioned_date: str | None  # ISO date string
    nse_announcement_date: str | None  # ISO date string


@dataclass(frozen=True)
class FilterResult:
    """Result of evaluate_negative_filters.

    excluded: bool  -- True iff this candidate should be excluded from the final list
    exclusion_reason: str | None  -- reason string (non-None iff excluded is True);
                                     None iff excluded is False
    """
    excluded: bool
    exclusion_reason: str | None


def trading_days_between(d1: date, d2: date) -> int:
    """Weekday-only count of trading days between two dates.

    NSE holiday calendar is not modeled in v1 (documented simplification per
    slice-6.md §3) — this counts weekdays only (Mon-Fri), a weekday-count
    approximation. Holiday-adjacent catalysts may be off by one trading day,
    acceptable slack for this tool's advisory (not precision) purpose.

    Args:
        d1, d2: date objects (any order)

    Returns:
        Integer count of trading days (weekdays) between them (not inclusive of endpoints).
    """
    if d1 > d2:
        d1, d2 = d2, d1
    days = 0
    current = d1
    while current < d2:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri are 0-4; Sat-Sun are 5-6
            days += 1
    return days


def _is_thin_volume(c: DeepDiveCandidateLike) -> bool:
    """Check if candidate's daily volume triggers the "thin volume" signal.

    True if EITHER:
    - daily_volume < MIN_ABSOLUTE_VOLUME (100k shares absolute floor), OR
    - avg_20day_volume is known AND daily_volume < 0.3x avg_20day_volume

    See slice-6.md §2a for rationale.
    """
    if c.daily_volume is None:
        return False
    if c.daily_volume < MIN_ABSOLUTE_VOLUME:
        return True
    if c.avg_20day_volume is not None and c.daily_volume < (
        MIN_RELATIVE_VOLUME_RATIO * c.avg_20day_volume
    ):
        return True
    return False


def _has_no_institutional_ownership(c: DeepDiveCandidateLike) -> bool:
    """Check if candidate has no institutional ownership signal.

    True if institutional_ownership_pct is either:
    - None (data unavailable, treated as "no institutional ownership"), OR
    - < 5.0% (combined FII + DII holding below threshold)

    See slice-6.md §2b for rationale.
    """
    return (
        c.institutional_ownership_pct is None
        or c.institutional_ownership_pct < MIN_INSTITUTIONAL_OWNERSHIP_PCT
    )


def evaluate_pump_and_dump(c: DeepDiveCandidateLike) -> bool:
    """Evaluate pump-and-dump exclusion criteria.

    Returns True only when ALL THREE signals are present (AND, not OR):
    1. Thin daily volume (absolute or relative floor breached)
    2. No institutional ownership (< 5% or unknown)
    3. Promotional chatter flag set to True

    See slice-6.md §2c-§2d for the exact rubric and AND-combination rationale.
    """
    return (
        _is_thin_volume(c)
        and _has_no_institutional_ownership(c)
        and c.promotional_chatter_flag
    )


def evaluate_stale_news(c: DeepDiveCandidateLike, run_date: date) -> bool:
    """Evaluate stale-news exclusion criteria.

    Returns True if the candidate's catalyst is more than 5 trading days old
    AND there is no fresher NSE announcement within the window that corroborates it.

    See slice-6.md §3 for the exact window/corroboration semantics.

    Args:
        c: candidate with catalyst_mentioned_date and nse_announcement_date (ISO strings)
        run_date: the date of this orchestrator run (for recency calculation)

    Returns:
        True if the candidate should be excluded for staleness.
    """
    catalyst_date = _safe_parse_date(c.catalyst_mentioned_date)
    if catalyst_date is None:
        return False

    days_since_catalyst = trading_days_between(catalyst_date, run_date)

    if days_since_catalyst <= STALENESS_WINDOW_TRADING_DAYS:
        return False  # Catalyst is fresh; not stale

    # Catalyst is stale; check if there's a fresher NSE announcement
    announcement_date = _safe_parse_date(c.nse_announcement_date)
    if announcement_date is not None:
        days_since_announcement = trading_days_between(announcement_date, run_date)
        if days_since_announcement <= STALENESS_WINDOW_TRADING_DAYS:
            return False  # Fresh official corroboration resets the clock

    # Catalyst is stale and no fresh corroboration exists
    return True


def evaluate_negative_filters(
    c: DeepDiveCandidateLike, run_date: date
) -> FilterResult:
    """Evaluate all negative-filter gates for a single candidate.

    Checks in order: pump-and-dump, then stale-news. Returns FilterResult
    with excluded=True and a reason string if any gate triggers; otherwise
    excluded=False and exclusion_reason=None.

    Pump-and-dump is checked first (documented precedence per slice-6.md §7:
    a candidate triggering both pump-and-dump and stale-news is excluded
    for pump-and-dump reason).

    Args:
        c: DeepDiveResult or similar object with the required fields
        run_date: date object for the orchestrator run

    Returns:
        FilterResult(excluded: bool, exclusion_reason: str | None)
        with the invariant: exclusion_reason is None iff excluded is False.
    """
    if evaluate_pump_and_dump(c):
        return FilterResult(
            excluded=True,
            exclusion_reason=(
                f"pump_and_dump: thin_volume={_is_thin_volume(c)}, "
                f"no_institutional_ownership={_has_no_institutional_ownership(c)}, "
                f"promotional_chatter_flag={c.promotional_chatter_flag}"
            ),
        )
    if evaluate_stale_news(c, run_date):
        return FilterResult(
            excluded=True,
            exclusion_reason=(
                f"stale_news: catalyst_mentioned_date={c.catalyst_mentioned_date}, "
                f"nse_announcement_date={c.nse_announcement_date}, "
                f"run_date={run_date}, window={STALENESS_WINDOW_TRADING_DAYS}td"
            ),
        )
    return FilterResult(excluded=False, exclusion_reason=None)
