from __future__ import annotations

import dataclasses
import datetime as dt
import re
from typing import Protocol

SNIPPET_MAX_CHARS = 280  # ~1-2 sentences; hard cap, documented convention (spec FR8)

_TAG_RE = re.compile(r"<[^>]+>")
_WHITESPACE_RE = re.compile(r"\s+")


class SourceFetchError(Exception):
    """Raised by a SourceAdapter.fetch() for a genuine fetch/transport/parse
    failure (non-2xx, timeout, connection error, malformed feed). Adapters
    must never swallow a real failure into an empty list -- that decision
    belongs to the caller (the orchestrator / later the aggregator), which
    catches this and isolates the failure per-adapter."""


def make_snippet(raw_text: str, max_chars: int = SNIPPET_MAX_CHARS) -> str:
    """Truncates arbitrary input text down to the retention-safe snippet
    length. This is the ONLY function in the codebase allowed to turn a raw
    description/body string into a `NormalizedItem.snippet` value -- every
    adapter must route through it rather than assigning a raw string
    directly, so the retention guarantee holds structurally, not just by
    adapter-author discipline. Collapses whitespace, strips HTML tags if
    present (RSS <description> fields are frequently HTML-escaped markup),
    then truncates to `max_chars`, appending "..." if truncated."""
    if not raw_text:
        return ""
    no_tags = _TAG_RE.sub(" ", raw_text)
    collapsed = _WHITESPACE_RE.sub(" ", no_tags).strip()
    if len(collapsed) <= max_chars:
        return collapsed
    return collapsed[:max_chars].rstrip() + "..."


@dataclasses.dataclass(frozen=True)
class NormalizedItem:
    source: str  # e.g. "moneycontrol_rss" -- adapter's fixed name
    headline: str  # short title/label, NOT the full body
    url: str  # canonical link to the original source
    published_at: dt.datetime  # UTC; adapters must parse/normalize feed-local timestamps
    snippet: str  # <= SNIPPET_MAX_CHARS chars; MUST be produced via make_snippet()
    ticker: str | None = None  # NSE/BSE symbol if the adapter can associate one; None for most RSS items

    # --- Optional extension fields (Slice 2), populated only by the adapter
    # that owns the field; always None for adapters that don't have this
    # data. Kept flat on NormalizedItem (not a subclass hierarchy) so
    # sweep_items stays one unified, stable-column table -- see slice-2 plan
    # §2 for the rationale. All are short bounded scalars, never body text,
    # so they introduce no new retention risk beyond the snippet guard below.
    close: float | None = None  # Bhavcopy: EOD close price
    prev_close: float | None = None  # Bhavcopy: previous day's close
    volume: int | None = None  # Bhavcopy: traded quantity for the day
    pe_ratio: float | None = None  # Screener.in: trailing P/E
    market_cap_cr: float | None = None  # Screener.in: market cap, INR crore
    indicator_name: str | None = None  # Trading Economics: e.g. "India CPI YoY"
    indicator_value: str | None = None  # Trading Economics: short formatted scalar, e.g. "5.2%" -- never a raw unbounded text blob

    def __post_init__(self) -> None:
        if len(self.snippet) > SNIPPET_MAX_CHARS + 3:  # +3 tolerates the "..." suffix
            raise ValueError(
                f"snippet exceeds retention-safe max ({SNIPPET_MAX_CHARS} chars); "
                "route all snippet text through make_snippet() -- never assign raw body text"
            )


class SourceAdapter(Protocol):
    name: str

    async def fetch(self) -> list[NormalizedItem]:
        """Fetches and normalizes this source's current items. Must never
        raise for 'this source has nothing new right now' (return [] instead)
        -- only raise SourceFetchError (or let a genuine unexpected exception
        propagate) for a real fetch/parse failure, which the caller catches
        and isolates per-adapter."""
        ...
