"""Tests for Slice 8: Sonnet compilation stage (fake-session only)."""

import pytest
import dataclasses
from app.agent.sessions import ScoredCandidate, CompiledIdea, CompilationResult
from app.agent.compilation import run_compilation_stage, merge_compilation_into_candidates, extract_compilation_commentary
from app.fakes.fake_sessions import FakeCompilationSession


@pytest.fixture
def sample_candidates() -> list[ScoredCandidate]:
    """Five fixture ScoredCandidate objects with mixed tiers for testing."""
    return [
        ScoredCandidate(
            ticker="RELIANCE",
            score=70,
            tier="green",
            sub_score_catalyst=32,
            sub_score_momentum=28,
            sub_score_macro=20,
            haiku_reasoning="Refining margins up Q/Q; Jio Financial speculation adds secondary catalyst.",
            citations=[
                {"source": "moneycontrol", "headline": "Reliance margins improve", "url": "http://example.com/1", "published_at": "2026-10-10", "snippet": "Margins up 15%"},
            ],
        ),
        ScoredCandidate(
            ticker="INFY",
            score=45,
            tier="yellow",
            sub_score_catalyst=14,
            sub_score_momentum=12,
            sub_score_macro=20,
            haiku_reasoning="Deal-win headline but light on specifics; weak catalyst.",
            citations=[
                {"source": "moneycontrol", "headline": "Infosys wins deal", "url": "http://example.com/2", "published_at": "2026-10-11", "snippet": "European retailer"},
            ],
        ),
        ScoredCandidate(
            ticker="TATAMOTORS",
            score=42,
            tier="red",
            sub_score_catalyst=24,
            sub_score_momentum=18,
            sub_score_macro=15,
            haiku_reasoning="JLR recovery + EV launch; but macro rate-decision risk looms.",
            citations=[
                {"source": "screener", "headline": "Tata Motors JLR recovery", "url": "http://example.com/3", "published_at": "2026-10-08", "snippet": "Wholesale up"},
            ],
        ),
        ScoredCandidate(
            ticker="HDFCBANK",
            score=55,
            tier="yellow",
            sub_score_catalyst=28,
            sub_score_momentum=20,
            sub_score_macro=20,
            haiku_reasoning="Q3 provisioning guidance positive; sector momentum mixed.",
            citations=[
                {"source": "moneycontrol", "headline": "HDFC Q3 guidance", "url": "http://example.com/4", "published_at": "2026-10-12", "snippet": "Provisions stable"},
            ],
        ),
        ScoredCandidate(
            ticker="ITC",
            score=38,
            tier="red",
            sub_score_catalyst=12,
            sub_score_momentum=8,
            sub_score_macro=15,
            haiku_reasoning="Agri stimulus chatter but no material near-term catalyst confirmed.",
            citations=[
                {"source": "reuters", "headline": "India agri stimulus rumor", "url": "http://example.com/5", "published_at": "2026-10-11", "snippet": "Stimulus talk"},
            ],
        ),
    ]


@pytest.mark.asyncio
async def test_exactly_one_call_per_run(sample_candidates):
    """Verify that exactly one compilation call is made per run, with all candidates together."""
    fake = FakeCompilationSession()
    result = await run_compilation_stage(fake, sample_candidates)

    # Check: exactly one call was made
    assert len(fake.calls) == 1, f"Expected 1 call, got {len(fake.calls)}"

    # Check: all tickers are in the one call
    call_tickers = fake.calls[0]
    assert call_tickers == [c.ticker for c in sample_candidates], \
        f"Call tickers {call_tickers} != expected {[c.ticker for c in sample_candidates]}"

    # Check: result has all tickers
    assert set(result.ideas.keys()) == {c.ticker for c in sample_candidates}


@pytest.mark.asyncio
async def test_score_tier_unchanged_before_and_after(sample_candidates):
    """CRITICAL: verify that score/tier fields are never modified by compilation.

    Also asserts that CompiledIdea has no score/tier fields in its schema.
    """
    fake = FakeCompilationSession()
    result = await run_compilation_stage(fake, sample_candidates)

    # Assert Layer 1: CompiledIdea dataclass has NO score/tier field
    compiled_idea_fields = {f.name for f in dataclasses.fields(CompiledIdea)}
    assert "score" not in compiled_idea_fields, "CompiledIdea must not have 'score' field"
    assert "tier" not in compiled_idea_fields, "CompiledIdea must not have 'tier' field"
    assert "sub_score_catalyst" not in compiled_idea_fields
    assert "sub_score_momentum" not in compiled_idea_fields
    assert "sub_score_macro" not in compiled_idea_fields

    # Assert Layer 2: merge preserves score/tier
    merged = merge_compilation_into_candidates(sample_candidates, result)
    for orig, merged_cand in zip(sample_candidates, merged):
        assert merged_cand.score == orig.score, \
            f"{orig.ticker}: score {merged_cand.score} != original {orig.score}"
        assert merged_cand.tier == orig.tier, \
            f"{orig.ticker}: tier {merged_cand.tier} != original {orig.tier}"
        assert merged_cand.sub_score_catalyst == orig.sub_score_catalyst
        assert merged_cand.sub_score_momentum == orig.sub_score_momentum
        assert merged_cand.sub_score_macro == orig.sub_score_macro


@pytest.mark.asyncio
async def test_rationale_and_commentary_populated_from_fake(sample_candidates):
    """Verify that compilation populates polished_rationale and ranking_commentary."""
    fake = FakeCompilationSession()
    result = await run_compilation_stage(fake, sample_candidates)

    # Check: each idea has non-empty rationale and commentary
    for ticker, compiled_idea in result.ideas.items():
        assert compiled_idea.polished_rationale, f"{ticker}: polished_rationale is empty"
        assert compiled_idea.ranking_commentary_fragment, f"{ticker}: ranking_commentary_fragment is empty"

        # Check: polished_rationale contains the [FAKE polished] marker
        assert "[FAKE polished]" in compiled_idea.polished_rationale
        assert ticker in compiled_idea.polished_rationale

    # Check: overall_ranking_commentary is non-empty and mentions all tickers
    assert result.overall_ranking_commentary, "overall_ranking_commentary is empty"
    assert "[FAKE overall]" in result.overall_ranking_commentary
    for candidate in sample_candidates:
        assert candidate.ticker in result.overall_ranking_commentary


@pytest.mark.asyncio
async def test_merge_rejects_missing_ticker(sample_candidates):
    """Verify that merge fails loud when a ticker is missing from compilation result."""
    fake = FakeCompilationSession()
    result = await run_compilation_stage(fake, sample_candidates)

    # Create a broken result missing one ticker
    broken_ideas = dict(result.ideas)
    missing_ticker = "RELIANCE"
    del broken_ideas[missing_ticker]
    broken_result = CompilationResult(
        ideas=broken_ideas,
        overall_ranking_commentary=result.overall_ranking_commentary,
    )

    # Attempt to merge: should raise ValueError
    with pytest.raises(ValueError, match="No compilation result for ticker RELIANCE"):
        merge_compilation_into_candidates(sample_candidates, broken_result)


@pytest.mark.asyncio
async def test_extract_compilation_commentary(sample_candidates):
    """Verify that extract_compilation_commentary retrieves the polished text."""
    fake = FakeCompilationSession()
    result = await run_compilation_stage(fake, sample_candidates)

    for candidate in sample_candidates:
        polished, commentary = extract_compilation_commentary(result, candidate.ticker)
        assert polished and commentary
        assert candidate.ticker in polished


@pytest.mark.asyncio
async def test_empty_candidates_list():
    """Verify graceful handling of empty candidate list."""
    fake = FakeCompilationSession()
    result = await run_compilation_stage(fake, [])

    assert result.ideas == {}
    assert result.overall_ranking_commentary == ""
    # Empty list: no call is made (optimization to skip LLM call)
    assert len(fake.calls) == 0
