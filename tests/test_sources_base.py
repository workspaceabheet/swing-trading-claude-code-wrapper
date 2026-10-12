import datetime as dt

import pytest

from app.sources.base import SNIPPET_MAX_CHARS, NormalizedItem, make_snippet


def test_make_snippet_truncates_long_text():
    raw = "x" * 2000
    snippet = make_snippet(raw)
    assert len(snippet) <= SNIPPET_MAX_CHARS + 3
    assert snippet.endswith("...")
    assert raw not in snippet


def test_make_snippet_strips_html_tags():
    raw = "<p>Reliance <b>surges</b> on strong earnings...</p>"
    snippet = make_snippet(raw)
    assert "<" not in snippet
    assert ">" not in snippet
    assert "Reliance" in snippet
    assert "surges" in snippet


def test_normalized_item_rejects_oversized_snippet():
    with pytest.raises(ValueError):
        NormalizedItem(
            source="moneycontrol_rss",
            headline="headline",
            url="https://example.com/a",
            published_at=dt.datetime.now(dt.timezone.utc),
            snippet="x" * 1000,
        )
