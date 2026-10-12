"""Output assembly: cap, ordering, red-tier backfill, citation hard-constraint (Slice 9).

This module implements the final ranking and capping logic that ensures:
- No more than 10 ideas in output
- Green-tier ideas prioritized over yellow, yellow over red
- Backfilled red ideas clearly marked as low_confidence
- No ideas without citations ever appear in output

Pure function with no I/O, no LLM calls, no database access.
"""

from app.agent.sessions import FinalCandidate, Idea


def assemble(candidates: list[FinalCandidate]) -> list[Idea]:
    """Assemble a ranked, capped, backfilled idea list from final candidates.

    Algorithm:
    1. Drop any candidate with no citation or empty citation URL (hard constraint).
    2. Partition remaining candidates by tier (green, yellow, red).
    3. Sort each tier by score descending, ticker ascending (tiebreaker).
    4. Take green+yellow candidates up to 10 total.
    5. If fewer than 10, backfill with red candidates (same sort order).
    6. Mark backfilled red candidates as low_confidence=True.
    7. Assign final rank 1..N in result order (green block, yellow block, red block).

    Args:
        candidates: list[FinalCandidate], output from Slice 8 compilation.

    Returns:
        list[Idea], ordered by rank 1..N (N <= 10), with low_confidence flag set
        appropriately. Empty list if no eligible candidates exist.
    """
    # Step 0: Hard constraints — drop any candidate with no citation, or with
    # no resolvable entry (buy) price. A candidate is eligible only if it has
    # at least one citation with a non-empty URL AND a positive entry price.
    # The orchestrator already drops no-entry-price candidates before they
    # ever reach assemble() (see run_orchestrator._resolve_entry_price), but
    # this is defense-in-depth against any other caller that doesn't --
    # entry=0.0 is never a real Bhavcopy price, only the dataclass default.
    eligible = []
    for c in candidates:
        if c.citations and len(c.citations) >= 1:
            first_cit = c.citations[0]
            if first_cit.url and first_cit.url.strip() and c.entry and c.entry > 0:
                eligible.append(c)

    if not eligible:
        return []

    # Step 1: Partition by tier.
    green = [c for c in eligible if c.tier == "green"]
    yellow = [c for c in eligible if c.tier == "yellow"]
    red = [c for c in eligible if c.tier == "red"]

    # Step 2: Sort each tier by score descending, ticker ascending.
    sort_key = lambda c: (-c.score, c.ticker)
    green.sort(key=sort_key)
    yellow.sort(key=sort_key)
    red.sort(key=sort_key)

    # Step 3: Fill with green+yellow first, up to 10.
    green_yellow = green + yellow
    primary = green_yellow[:10]

    # Step 4: Backfill with red only if primary has fewer than 10.
    remaining_slots = 10 - len(primary)
    if remaining_slots > 0 and len(red) > 0:
        backfill = red[:remaining_slots]
    else:
        backfill = []

    # Step 5 & 6: Mark low_confidence and assign rank.
    final_order = primary + backfill
    result = []
    for i, c in enumerate(final_order):
        is_backfilled = c in backfill
        idea = Idea(
            ticker=c.ticker,
            entry=c.entry,
            target=c.target,
            hold_days=c.hold_days,
            tier=c.tier,
            score=c.score,
            sub_score_catalyst=c.sub_score_catalyst,
            sub_score_momentum=c.sub_score_momentum,
            sub_score_macro=c.sub_score_macro,
            polished_rationale=c.polished_rationale,
            citation_url=c.citations[0].url,
            citation_source=c.citations[0].source,
            citation_headline=c.citations[0].headline,
            low_confidence=is_backfilled,
            backfill_reason="red_tier_backfill" if is_backfilled else None,
            rank=i + 1,
            ranking_commentary=c.ranking_commentary_fragment,
        )
        result.append(idea)

    return result
