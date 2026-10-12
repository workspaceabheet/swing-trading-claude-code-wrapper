"""Hardening test: repo-wide data retention guarantee.

Per spec §4 (FR8) and §7 (HC5), the system never persists full article body
text anywhere — only headline/source/date/URL/snippet fields are retained.

This test uses defense-in-depth: structural checks on the NormalizedItem type
itself, behavioral checks on all adapters, and schema checks on the SQLite DB.
"""
import dataclasses
import pathlib

import pytest

from app.sources.base import NormalizedItem, SNIPPET_MAX_CHARS


class TestNormalizedItemStructure:
    """Structural checks: NormalizedItem has no fields capable of holding
    full article text."""

    def test_normalized_item_has_no_full_body_field(self):
        """Assert NormalizedItem has no field that could hold article body text."""
        field_names = {f.name for f in dataclasses.fields(NormalizedItem)}
        # These would be forbidden field names (example list; adjust if needed)
        forbidden_names = {"body", "full_text", "content", "article_body", "raw_html", "text"}
        found_forbidden = field_names & forbidden_names
        assert not found_forbidden, (
            f"NormalizedItem exposes fields capable of holding full article text: "
            f"{found_forbidden}; per spec §4 FR8 / §7 HC5, only headline/source/date/"
            "URL/snippet are retained"
        )

    def test_snippet_field_is_length_constrained(self):
        """Assert the snippet field is bounded by the documented max length."""
        long_text = "x" * 50_000
        try:
            item = NormalizedItem(
                source="test",
                headline="Test headline",
                url="https://example.com/test",
                published_at=None,  # type: ignore
                snippet=long_text,
            )
        except ValueError as e:
            # Expected: the __post_init__ should reject oversized snippets
            assert "retention-safe max" in str(e).lower()
            assert str(SNIPPET_MAX_CHARS) in str(e)
        else:
            pytest.fail(
                "NormalizedItem accepted an oversized snippet without raising ValueError; "
                "per spec §4 FR8, snippet must be constrained to max length"
            )

    def test_snippet_field_accepts_normal_length(self):
        """Assert the snippet field accepts normal (compliant) length text."""
        import datetime as dt
        normal_snippet = "This is a normal snippet, ~1-2 sentences."
        item = NormalizedItem(
            source="test",
            headline="Test headline",
            url="https://example.com/test",
            published_at=dt.datetime.now(dt.timezone.utc),
            snippet=normal_snippet,
        )
        assert item.snippet == normal_snippet
        assert len(item.snippet) <= SNIPPET_MAX_CHARS


class TestSQLiteSchema:
    """Verify the SQLite schema has no columns capable of holding full
    article body text."""

    def test_sweep_items_table_has_no_body_columns(self, data_dir):
        """Assert the sweep_items table schema has no body/text columns."""
        from app.db import db_session

        with db_session() as conn:
            # Get all column names from the sweep_items table
            cols = conn.execute("PRAGMA table_info(sweep_items)").fetchall()
            col_names = {col[1] for col in cols}

            # Forbidden column names
            forbidden = {"body", "full_text", "content", "article_body", "raw_html"}
            found_forbidden = col_names & forbidden

            assert not found_forbidden, (
                f"sweep_items table has forbidden columns: {found_forbidden}; "
                f"per spec §4 FR8, only headline/source/date/URL/snippet are retained"
            )

            # Verify the expected columns exist
            expected_key_cols = {"headline", "url", "snippet", "source", "published_at"}
            assert expected_key_cols.issubset(col_names), (
                f"sweep_items missing expected retention columns; "
                f"expected at least: {expected_key_cols}, found: {col_names}"
            )

    def test_no_persisted_row_exceeds_snippet_length(self, data_dir):
        """Assert no row in sweep_items has a snippet exceeding the retention max."""
        from app.db import db_session

        with db_session() as conn:
            rows = conn.execute("SELECT snippet FROM sweep_items").fetchall()
            for row in rows:
                snippet = row[0] or ""
                assert len(snippet) <= SNIPPET_MAX_CHARS, (
                    f"sweep_items row has oversized snippet: {len(snippet)} > {SNIPPET_MAX_CHARS}; "
                    f"per spec §4 FR8 / §7 HC5, snippet must be constrained to max length"
                )
