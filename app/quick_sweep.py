"""Quick-sweep change detection: hash-based materiality check.

Slice 3 (FR2/FR12): computes a stable hash of the current run's sweep items
(normalized identity tuples) and compares it to the prior run's hash to
decide whether to proceed to deeper analysis or skip.
"""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, date

from app.sources.base import NormalizedItem


@dataclass
class QuickSweepResult:
    """Result of comparing current sweep hash to prior run's hash."""

    material_change: bool  # True if current differs from prior (or no prior exists)
    current_hash: str  # SHA-256 hex of current run's normalized tuples
    prior_hash: str | None  # Prior run's hash, or None if no prior run exists


def _normalize_identity_key(item: NormalizedItem) -> str:
    """Compute the identity key for an item: ticker (uppercased) if present,
    else normalized headline.

    Normalization (for headline-only items):
    - Lowercase
    - Remove all punctuation (regex [^\\w\\s])
    - Collapse whitespace runs to single space, strip leading/trailing
    - No stemming/fuzzy matching
    """
    if item.ticker is not None:
        return item.ticker.upper()

    # Normalize headline: lowercase, remove punctuation, then collapse whitespace
    normalized = item.headline.lower()
    # Remove punctuation
    normalized = re.sub(r"[^\w\s]", "", normalized)
    # Collapse whitespace and strip
    normalized = re.sub(r"\s+", " ", normalized).strip()
    return normalized


def _build_identity_tuples(
    items: list[NormalizedItem],
) -> set[tuple[str, str, str]]:
    """Build a set of (source, identity_key, published_date) tuples.

    published_date is truncated to YYYY-MM-DD (calendar date only, not time).
    The set deduplicates identical tuples across sources.
    """
    tuples: set[tuple[str, str, str]] = set()
    for item in items:
        identity_key = _normalize_identity_key(item)
        # Truncate to calendar date
        published_date = item.published_at.date().isoformat()
        tuples.add((item.source, identity_key, published_date))
    return tuples


def compute_hash(items: list[NormalizedItem]) -> str:
    """Compute a stable SHA-256 hash of the given items.

    Process:
    1. Build identity tuples (source, identity_key, published_date)
    2. Sort deterministically (lexicographic by tuple)
    3. Serialize with ASCII separators (\\x1f within tuple, \\x1e between tuples)
    4. SHA-256 hex digest
    """
    tuples = _build_identity_tuples(items)
    sorted_tuples = sorted(tuples)

    # Serialize: "|".join fields within a tuple, "\x1e" between tuples
    canonical = "\x1e".join(
        f"{s}\x1f{k}\x1f{d}" for s, k, d in sorted_tuples
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def compare_to_prior(current_hash: str, prior_hash: str | None) -> QuickSweepResult:
    """Compare current hash to prior run's hash; decide materiality.

    If prior_hash is None (first-ever run), always material.
    Otherwise, material iff hashes differ (even by one bit).
    """
    if prior_hash is None:
        # First-ever run: no prior to compare against
        return QuickSweepResult(
            material_change=True, current_hash=current_hash, prior_hash=None
        )

    material = current_hash != prior_hash
    return QuickSweepResult(
        material_change=material, current_hash=current_hash, prior_hash=prior_hash
    )


def format_skip_message(source_run_id: int, prior_finished_at: str) -> str:
    """Format the UI message for a skipped run.

    Exact text per spec: "No material change detected since the last run — showing results from run #{source_run_id} (completed {prior_finished_at})."
    """
    return (
        f"No material change detected since the last run — showing results from "
        f"run #{source_run_id} (completed {prior_finished_at})."
    )
