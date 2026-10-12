"""Unit tests for Slice 9: output assembly (cap, ordering, red-tier backfill, citation hard-constraint).

Table-driven test cases covering edge cases and invariants per technical spec.
"""

import pytest
from app.agent.sessions import FinalCandidate, Citation
from app.assembly import assemble


def make_candidate(
    ticker: str,
    tier: str,
    score: int,
    has_citation: bool = True,
    citation_url: str = "https://example.com",
) -> FinalCandidate:
    """Factory for creating FinalCandidate test fixtures.

    Args:
        ticker: Stock ticker symbol.
        tier: "green", "yellow", or "red".
        score: 0-100 score.
        has_citation: Whether to include a citation.
        citation_url: URL for the citation (if has_citation is True).
    """
    citations = []
    if has_citation and citation_url.strip():
        citations = [
            Citation(
                source="test_source",
                headline=f"Test headline for {ticker}",
                url=citation_url,
                published_at="2025-01-01T00:00:00Z",
            )
        ]

    return FinalCandidate(
        ticker=ticker,
        tier=tier,
        score=score,
        sub_score_catalyst=20,
        sub_score_momentum=15,
        sub_score_macro=15,
        citations=citations,
        polished_rationale=f"Rationale for {ticker}",
        ranking_commentary_fragment=f"Comment for {ticker}",
        entry=100.0,
        target=110.0,
        hold_days=7,
    )


class TestCitationHardConstraint:
    """Test that candidates without citations are dropped regardless of score/tier."""

    def test_high_score_green_without_citation_dropped(self):
        """A green candidate with score 95 but no citation is excluded."""
        candidates = [
            make_candidate("GOOD", "green", 90, has_citation=True),
            make_candidate("NOBAD", "green", 95, has_citation=False),  # dropped
        ]
        result = assemble(candidates)
        assert len(result) == 1
        assert result[0].ticker == "GOOD"

    def test_empty_citation_url_dropped(self):
        """A candidate with empty/whitespace citation URL is dropped."""
        candidates = [
            make_candidate("GOOD", "green", 85, has_citation=True),
            make_candidate("EMPTY", "green", 90, has_citation=True, citation_url=""),
            make_candidate("WHITESPACE", "green", 92, has_citation=True, citation_url="   "),
        ]
        result = assemble(candidates)
        assert len(result) == 1
        assert result[0].ticker == "GOOD"

    def test_zero_candidates_returns_empty_list(self):
        """assemble([]) returns [] without crash."""
        result = assemble([])
        assert result == []

    def test_all_candidates_lack_citations_returns_empty_list(self):
        """If all candidates lack citations, return [] (no output)."""
        candidates = [
            make_candidate("A", "green", 90, has_citation=False),
            make_candidate("B", "yellow", 80, has_citation=False),
            make_candidate("C", "red", 50, has_citation=False),
        ]
        result = assemble(candidates)
        assert result == []


class TestTierPartitionAndSort:
    """Test tier partitioning and sort order within each tier."""

    def test_tiebreak_ticker_ascending(self):
        """When two candidates share same score/tier, sort by ticker ascending."""
        candidates = [
            make_candidate("ZEE", "green", 85),
            make_candidate("ABC", "green", 85),
            make_candidate("MID", "green", 85),
        ]
        result = assemble(candidates)
        assert len(result) == 3
        assert result[0].ticker == "ABC"
        assert result[1].ticker == "MID"
        assert result[2].ticker == "ZEE"
        assert [r.rank for r in result] == [1, 2, 3]

    def test_score_descending_within_tier(self):
        """Within a tier, higher scores come first."""
        candidates = [
            make_candidate("LOW", "green", 50),
            make_candidate("HIGH", "green", 95),
            make_candidate("MID", "green", 75),
        ]
        result = assemble(candidates)
        assert result[0].ticker == "HIGH"
        assert result[1].ticker == "MID"
        assert result[2].ticker == "LOW"

    def test_tier_order_green_before_yellow_before_red(self):
        """Final order is always green block, yellow block, red block."""
        candidates = [
            make_candidate("R1", "red", 95),    # high score but red
            make_candidate("Y1", "yellow", 70),
            make_candidate("G1", "green", 60),  # lower score but green
        ]
        result = assemble(candidates)
        assert [r.tier for r in result] == ["green", "yellow", "red"]
        assert result[0].ticker == "G1"
        assert result[1].ticker == "Y1"
        assert result[2].ticker == "R1"


class TestCapAtTen:
    """Test that output never exceeds 10 ideas."""

    def test_exactly_ten_green_yellow_no_backfill(self):
        """10 green/yellow candidates -> 10 results, zero red."""
        candidates = [
            make_candidate(f"T{i:02d}", "green", 90 - i)
            for i in range(7)
        ] + [
            make_candidate(f"T{i:02d}", "yellow", 60 - i)
            for i in range(3)
        ]
        # Add some red to ensure no backfill happens
        candidates.extend([
            make_candidate(f"R{i:02d}", "red", 40 - i)
            for i in range(5)
        ])

        result = assemble(candidates)
        assert len(result) == 10
        assert all(r.tier in ("green", "yellow") for r in result)
        assert all(not r.low_confidence for r in result)

    def test_more_than_ten_green_yellow_truncates_at_ten(self):
        """14 green/yellow candidates -> 10 results, lowest-scoring ones dropped."""
        candidates = [
            make_candidate(f"T{i:02d}", "green", 90 - i)
            for i in range(14)
        ]
        result = assemble(candidates)
        assert len(result) == 10
        # Top 10 by score should be present
        assert result[0].ticker == "T00"  # score 90
        assert result[9].ticker == "T09"  # score 81
        # Candidates T10-T13 (scores 80-77) should be absent
        assert "T10" not in [r.ticker for r in result]
        assert "T13" not in [r.ticker for r in result]

    def test_fewer_than_ten_total_never_padded(self):
        """If total candidates (after citation drop) < 10, result is exactly that number."""
        candidates = [
            make_candidate("G1", "green", 90),
            make_candidate("G2", "green", 85),
            make_candidate("Y1", "yellow", 75),
            make_candidate("R1", "red", 50),
        ]
        result = assemble(candidates)
        assert len(result) == 4
        assert [r.rank for r in result] == [1, 2, 3, 4]


class TestRedTierBackfill:
    """Test that red-tier candidates backfill only when needed."""

    def test_fewer_than_ten_green_yellow_backfills_with_red(self):
        """6 yellow/green + 5 red -> 10 results, last 4 flagged low_confidence."""
        candidates = [
            make_candidate("G1", "green", 90),
            make_candidate("G2", "green", 85),
            make_candidate("Y1", "yellow", 75),
            make_candidate("Y2", "yellow", 70),
            make_candidate("Y3", "yellow", 65),
            make_candidate("Y4", "yellow", 60),
        ] + [
            make_candidate(f"R{i}", "red", 50 - i)
            for i in range(5)
        ]

        result = assemble(candidates)
        assert len(result) == 10

        # First 6 are non-backfilled (low_confidence=False)
        for i in range(6):
            assert not result[i].low_confidence, f"Result {i} should not be low_confidence"
            assert result[i].backfill_reason is None

        # Last 4 are backfilled red (low_confidence=True)
        for i in range(6, 10):
            assert result[i].low_confidence, f"Result {i} should be low_confidence"
            assert result[i].backfill_reason == "red_tier_backfill"
            assert result[i].tier == "red"

    def test_zero_green_yellow_all_red_backfilled(self):
        """0 green/yellow + 7 red -> 7 results, all low_confidence."""
        candidates = [
            make_candidate(f"R{i}", "red", 50 - i)
            for i in range(7)
        ]
        result = assemble(candidates)
        assert len(result) == 7
        assert all(r.tier == "red" for r in result)
        assert all(r.low_confidence for r in result)
        assert all(r.backfill_reason == "red_tier_backfill" for r in result)

    def test_fewer_than_ten_total_after_backfill(self):
        """3 green + 2 red, no more -> 5 results (not padded)."""
        candidates = [
            make_candidate("G1", "green", 90),
            make_candidate("G2", "green", 85),
            make_candidate("G3", "green", 80),
            make_candidate("R1", "red", 50),
            make_candidate("R2", "red", 45),
        ]
        result = assemble(candidates)
        assert len(result) == 5
        # Green block
        assert result[0].tier == "green"
        assert not result[0].low_confidence
        assert result[1].tier == "green"
        assert result[2].tier == "green"
        # Red block (backfilled)
        assert result[3].tier == "red"
        assert result[3].low_confidence
        assert result[4].tier == "red"
        assert result[4].low_confidence


class TestRankAssignment:
    """Test that rank is correctly assigned 1..N in final order."""

    def test_rank_is_one_to_n_continuous(self):
        """Rank starts at 1 and increments by 1 with no gaps."""
        candidates = [
            make_candidate(f"T{i}", "green", 90 - i)
            for i in range(5)
        ] + [
            make_candidate(f"R{i}", "red", 50 - i)
            for i in range(3)
        ]
        result = assemble(candidates)
        assert len(result) == 8
        assert [r.rank for r in result] == [1, 2, 3, 4, 5, 6, 7, 8]

    def test_rank_respects_tier_blocking(self):
        """Red-tier ranks don't start until green+yellow are exhausted."""
        candidates = [
            make_candidate("G1", "green", 90),
            make_candidate("Y1", "yellow", 70),
            make_candidate("R1", "red", 40),
        ]
        result = assemble(candidates)
        green_ranks = [r.rank for r in result if r.tier == "green"]
        yellow_ranks = [r.rank for r in result if r.tier == "yellow"]
        red_ranks = [r.rank for r in result if r.tier == "red"]

        assert green_ranks == [1]
        assert yellow_ranks == [2]
        assert red_ranks == [3]


class TestLowConfidenceFlag:
    """Test low_confidence flag semantics."""

    def test_green_ideas_never_low_confidence(self):
        """Green ideas, even if few, are never flagged low_confidence."""
        candidates = [
            make_candidate("G1", "green", 90),
            make_candidate("G2", "green", 80),
        ] + [
            make_candidate(f"R{i}", "red", 50 - i)
            for i in range(8)
        ]
        result = assemble(candidates)
        green_results = [r for r in result if r.tier == "green"]
        assert all(not r.low_confidence for r in green_results)
        assert all(r.backfill_reason is None for r in green_results)

    def test_yellow_ideas_never_low_confidence(self):
        """Yellow ideas, even when < 10 green/yellow total, are never flagged."""
        candidates = [
            make_candidate("Y1", "yellow", 75),
            make_candidate("Y2", "yellow", 70),
        ] + [
            make_candidate(f"R{i}", "red", 50 - i)
            for i in range(8)
        ]
        result = assemble(candidates)
        yellow_results = [r for r in result if r.tier == "yellow"]
        assert all(not r.low_confidence for r in yellow_results)
        assert all(r.backfill_reason is None for r in yellow_results)

    def test_red_only_if_backfilled(self):
        """Red ideas never appear in output unless backfilled (low_confidence=True)."""
        # 10 green/yellow -> no red in output
        candidates_plenty = [
            make_candidate(f"T{i}", "green", 90 - i)
            for i in range(10)
        ] + [
            make_candidate(f"R{i}", "red", 40 - i)
            for i in range(5)
        ]
        result = assemble(candidates_plenty)
        assert all(r.tier != "red" for r in result)

        # 5 green + 2 red -> red in output but not low_confidence
        # (Actually, red in output IS backfilled, so WILL be low_confidence)
        candidates_short = [
            make_candidate(f"G{i}", "green", 90 - i)
            for i in range(5)
        ] + [
            make_candidate(f"R{i}", "red", 50 - i)
            for i in range(2)
        ]
        result = assemble(candidates_short)
        red_results = [r for r in result if r.tier == "red"]
        # Red ideas that DO appear are always backfilled
        assert all(r.low_confidence for r in red_results)


class TestCitationPreservation:
    """Test that first citation is correctly extracted to output Idea."""

    def test_citation_fields_extracted_from_first_citation(self):
        """Idea uses first Citation's url, source, headline."""
        citation1 = Citation(
            source="source1",
            headline="headline1",
            url="https://example.com/1",
            published_at="2025-01-01T00:00:00Z",
        )
        citation2 = Citation(
            source="source2",
            headline="headline2",
            url="https://example.com/2",
            published_at="2025-01-02T00:00:00Z",
        )

        candidate = FinalCandidate(
            ticker="TEST",
            tier="green",
            score=85,
            sub_score_catalyst=20,
            sub_score_momentum=15,
            sub_score_macro=15,
            citations=[citation1, citation2],
            polished_rationale="Test rationale",
            ranking_commentary_fragment="Test comment",
            entry=100.0,
            target=110.0,
            hold_days=7,
        )

        result = assemble([candidate])
        assert len(result) == 1
        assert result[0].citation_url == "https://example.com/1"
        assert result[0].citation_source == "source1"
        assert result[0].citation_headline == "headline1"


class TestIntegrationScenarios:
    """Complex end-to-end scenarios combining multiple requirements."""

    def test_mixed_tiers_with_truncation_and_backfill(self):
        """
        Scenario: 5 green (scores 90-86), 8 yellow (scores 80-73), 10 red (scores 65-56).
        Expected: top 5 green + 5 yellow (total 10), zero red.
        """
        candidates = [
            make_candidate(f"G{i}", "green", 90 - i)
            for i in range(5)
        ] + [
            make_candidate(f"Y{i}", "yellow", 80 - i)
            for i in range(8)
        ] + [
            make_candidate(f"R{i}", "red", 65 - i)
            for i in range(10)
        ]

        result = assemble(candidates)
        assert len(result) == 10
        assert [r.tier for r in result] == ["green"] * 5 + ["yellow"] * 5
        assert all(not r.low_confidence for r in result)

    def test_all_tiers_present_with_backfill(self):
        """
        Scenario: 3 green, 2 yellow, 7 red (all with citations).
        Expected: 3G + 2Y (5 total), then 5R backfilled (ranks 6-10, all low_confidence).
        """
        candidates = [
            make_candidate(f"G{i}", "green", 90 - i)
            for i in range(3)
        ] + [
            make_candidate(f"Y{i}", "yellow", 70 - i)
            for i in range(2)
        ] + [
            make_candidate(f"R{i}", "red", 50 - i)
            for i in range(7)
        ]

        result = assemble(candidates)
        assert len(result) == 10

        primary = result[:5]
        backfill = result[5:]

        assert all(p.tier in ("green", "yellow") for p in primary)
        assert all(not p.low_confidence for p in primary)

        assert all(b.tier == "red" for b in backfill)
        assert all(b.low_confidence for b in backfill)
        assert all(b.backfill_reason == "red_tier_backfill" for b in backfill)

        assert [r.rank for r in result] == list(range(1, 11))
