"""Unit tests for quick-sweep change detection logic (Slice 3, FR2/FR12)."""

import datetime as dt

import pytest

from app.quick_sweep import (
    compute_hash,
    compare_to_prior,
    format_skip_message,
    _normalize_identity_key,
    _build_identity_tuples,
)
from app.sources.base import NormalizedItem


def _make_item(
    source: str,
    headline: str = "test headline",
    ticker: str | None = None,
    published_at: dt.datetime | None = None,
    snippet: str = "test snippet",
    url: str = "https://example.com/test",
) -> NormalizedItem:
    """Helper to create a NormalizedItem with sensible defaults."""
    return NormalizedItem(
        source=source,
        headline=headline,
        url=url,
        published_at=published_at or dt.datetime(2026, 10, 12, 12, 0, 0, tzinfo=dt.timezone.utc),
        snippet=snippet,
        ticker=ticker,
    )


class TestNormalizeIdentityKey:
    """Tests for _normalize_identity_key function."""

    def test_ticker_takes_precedence(self):
        """When ticker is present, it's uppercased and used as identity."""
        item = _make_item(source="test", headline="old headline", ticker="reliance")
        assert _normalize_identity_key(item) == "RELIANCE"

    def test_headline_normalized_when_no_ticker(self):
        """When no ticker, headline is normalized (lowercase, no punctuation)."""
        item = _make_item(source="test", headline="RBI Cuts Rates!", ticker=None)
        assert _normalize_identity_key(item) == "rbi cuts rates"

    def test_punctuation_removed_from_headline(self):
        """Punctuation is stripped from headline normalization."""
        item = _make_item(source="test", headline="Test! @ # $ % Headline", ticker=None)
        assert _normalize_identity_key(item) == "test headline"

    def test_whitespace_collapsed_in_headline(self):
        """Multiple whitespace runs are collapsed to single space."""
        item = _make_item(
            source="test",
            headline="Test    \t   \n   Headline",
            ticker=None,
        )
        assert _normalize_identity_key(item) == "test headline"

    def test_headline_stripped_of_leading_trailing_whitespace(self):
        """Leading and trailing whitespace is stripped."""
        item = _make_item(source="test", headline="  test headline  ", ticker=None)
        assert _normalize_identity_key(item) == "test headline"


class TestBuildIdentityTuples:
    """Tests for _build_identity_tuples function."""

    def test_creates_tuples_with_date_truncation(self):
        """Identity tuples use calendar date (YYYY-MM-DD), not full timestamp."""
        items = [
            _make_item(
                source="src1",
                headline="test",
                ticker="ABC",
                published_at=dt.datetime(2026, 10, 12, 15, 30, 45, tzinfo=dt.timezone.utc),
            ),
        ]
        tuples = _build_identity_tuples(items)
        # Should have one tuple: (source, identity_key, date)
        assert len(tuples) == 1
        assert ("src1", "ABC", "2026-10-12") in tuples

    def test_deduplicates_identical_tuples(self):
        """Identical tuples from different sources collapse into one."""
        items = [
            _make_item(
                source="src1",
                headline="test",
                ticker="ABC",
                published_at=dt.datetime(2026, 10, 12, 0, 0, 0, tzinfo=dt.timezone.utc),
            ),
            _make_item(
                source="src2",
                headline="different",
                ticker="ABC",
                published_at=dt.datetime(2026, 10, 12, 12, 0, 0, tzinfo=dt.timezone.utc),
            ),
        ]
        tuples = _build_identity_tuples(items)
        # Both have ticker ABC with same date; tuples are (source, identity, date).
        # These are DIFFERENT tuples because source is different.
        assert len(tuples) == 2

    def test_empty_list_produces_empty_set(self):
        """Empty item list produces empty tuple set."""
        tuples = _build_identity_tuples([])
        assert len(tuples) == 0


class TestComputeHash:
    """Tests for compute_hash function."""

    def test_identical_item_sets_produce_identical_hash(self):
        """Two item sets with same content but different order/snippet/url produce same hash."""
        items1 = [
            _make_item(source="src1", headline="headline1", ticker="ABC", snippet="old snippet1", url="https://old1.com"),
            _make_item(source="src2", headline="headline2", ticker="XYZ", snippet="old snippet2", url="https://old2.com"),
        ]
        items2 = [
            _make_item(source="src2", headline="headline2", ticker="XYZ", snippet="new snippet2", url="https://new2.com"),
            _make_item(source="src1", headline="headline1", ticker="ABC", snippet="new snippet1", url="https://new1.com"),
        ]
        # Same identity tuples despite different order, snippet, url
        hash1 = compute_hash(items1)
        hash2 = compute_hash(items2)
        assert hash1 == hash2

    def test_new_headline_changes_hash(self):
        """Adding a new item to the set changes the hash."""
        items1 = [
            _make_item(source="src1", headline="headline1", ticker="ABC"),
        ]
        items2 = items1 + [
            _make_item(source="src2", headline="headline2", ticker="XYZ"),
        ]
        hash1 = compute_hash(items1)
        hash2 = compute_hash(items2)
        assert hash1 != hash2

    def test_removed_item_changes_hash(self):
        """Removing an item from the set changes the hash."""
        items_baseline = [
            _make_item(source="src1", headline="headline1", ticker="ABC"),
            _make_item(source="src2", headline="headline2", ticker="XYZ"),
        ]
        items_without_first = items_baseline[1:]
        hash_baseline = compute_hash(items_baseline)
        hash_without = compute_hash(items_without_first)
        assert hash_baseline != hash_without

    def test_snippet_only_difference_does_not_change_hash(self):
        """Same identity tuples, different snippet → identical hash."""
        items1 = [
            _make_item(source="src1", headline="test", ticker="ABC", snippet="snippet A"),
        ]
        items2 = [
            _make_item(source="src1", headline="test", ticker="ABC", snippet="snippet B"),
        ]
        assert compute_hash(items1) == compute_hash(items2)

    def test_url_only_difference_does_not_change_hash(self):
        """Same identity tuples, different url → identical hash."""
        items1 = [
            _make_item(source="src1", headline="test", ticker="ABC", url="https://example.com/a"),
        ]
        items2 = [
            _make_item(source="src1", headline="test", ticker="ABC", url="https://example.com/b?tracking=1"),
        ]
        assert compute_hash(items1) == compute_hash(items2)

    def test_published_time_same_day_does_not_change_hash(self):
        """Same item, published_at differing by hours but same date → identical hash."""
        items1 = [
            _make_item(
                source="src1",
                headline="test",
                ticker="ABC",
                published_at=dt.datetime(2026, 10, 12, 0, 0, 0, tzinfo=dt.timezone.utc),
            ),
        ]
        items2 = [
            _make_item(
                source="src1",
                headline="test",
                ticker="ABC",
                published_at=dt.datetime(2026, 10, 12, 23, 59, 59, tzinfo=dt.timezone.utc),
            ),
        ]
        assert compute_hash(items1) == compute_hash(items2)

    def test_published_date_change_changes_hash(self):
        """Same item, published_at moved to next calendar day → different hash."""
        items1 = [
            _make_item(
                source="src1",
                headline="test",
                ticker="ABC",
                published_at=dt.datetime(2026, 10, 12, 23, 59, 59, tzinfo=dt.timezone.utc),
            ),
        ]
        items2 = [
            _make_item(
                source="src1",
                headline="test",
                ticker="ABC",
                published_at=dt.datetime(2026, 10, 13, 0, 0, 0, tzinfo=dt.timezone.utc),
            ),
        ]
        assert compute_hash(items1) != compute_hash(items2)

    def test_headline_case_and_punctuation_normalization(self):
        """Two headline-only items differing by case/punctuation → identical hash."""
        items1 = [
            _make_item(source="src1", headline="RBI Cuts Rates!", ticker=None),
        ]
        items2 = [
            _make_item(source="src1", headline="rbi cuts rates", ticker=None),
        ]
        assert compute_hash(items1) == compute_hash(items2)

    def test_headline_vs_ticker_identity_precedence(self):
        """Item with ticker uses ticker identity even if headline changes."""
        items1 = [
            _make_item(source="src1", headline="Old headline", ticker="ABC"),
        ]
        items2 = [
            _make_item(source="src1", headline="Completely new headline", ticker="ABC"),
        ]
        assert compute_hash(items1) == compute_hash(items2)

    def test_hash_is_hex_string(self):
        """Hash is a valid SHA-256 hex digest (64 chars)."""
        items = [_make_item(source="src1", headline="test", ticker="ABC")]
        hash_val = compute_hash(items)
        assert isinstance(hash_val, str)
        assert len(hash_val) == 64
        # Check it's valid hex
        int(hash_val, 16)


class TestCompareToPrior:
    """Tests for compare_to_prior function."""

    def test_identical_hashes_not_material(self):
        """Same hash in current and prior → not material."""
        hash_val = "abc123"
        result = compare_to_prior(hash_val, hash_val)
        assert result.material_change is False
        assert result.current_hash == hash_val
        assert result.prior_hash == hash_val

    def test_different_hashes_material(self):
        """Different hashes → material change."""
        result = compare_to_prior("abc123", "def456")
        assert result.material_change is True
        assert result.current_hash == "abc123"
        assert result.prior_hash == "def456"

    def test_no_prior_run_is_material(self):
        """No prior run (prior_hash=None) → always material."""
        result = compare_to_prior("abc123", None)
        assert result.material_change is True
        assert result.current_hash == "abc123"
        assert result.prior_hash is None


class TestFormatSkipMessage:
    """Tests for format_skip_message function."""

    def test_exact_message_text(self):
        """Message matches the spec's exact template."""
        message = format_skip_message(42, "2026-10-12T12:00:00+00:00")
        assert message == (
            "No material change detected since the last run — showing results from "
            "run #42 (completed 2026-10-12T12:00:00+00:00)."
        )

    def test_message_includes_prior_run_id(self):
        """Message includes the source_run_id."""
        message = format_skip_message(99, "2026-10-01T00:00:00Z")
        assert "#99" in message

    def test_message_includes_prior_finished_at(self):
        """Message includes the prior run's finished_at timestamp."""
        finished_at = "2026-10-11T15:30:45Z"
        message = format_skip_message(7, finished_at)
        assert finished_at in message
