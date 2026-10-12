"""Opt-in live test against the REAL Sonnet ClaudeSDKClient. Skipped by default.

Run manually with:
    COMPILATION_LIVE=1 pytest tests/test_compilation_live_manual.py -v -s
"""

import os
import pytest
import dataclasses
from app.agent.sessions import ScoredCandidate, CompiledIdea
from app.agent.compilation import run_compilation_stage, merge_compilation_into_candidates
from app.agent.sonnet_session import SonnetCompilationSession


pytestmark = pytest.mark.skipif(
    os.environ.get("COMPILATION_LIVE") != "1", reason="live LLM call, manual only"
)


@pytest.fixture
def realistic_candidates() -> list[ScoredCandidate]:
    """2-3 realistic fixture candidates for live testing."""
    return [
        ScoredCandidate(
            ticker="RELIANCE",
            score=72,
            tier="green",
            sub_score_catalyst=34,
            sub_score_momentum=29,
            sub_score_macro=20,
            haiku_reasoning=(
                "Refining margins reported up q/q per Moneycontrol coverage; "
                "Jio Financial stake-sale speculation adds a secondary catalyst. "
                "Energy sector showing multi-week uptrend."
            ),
            citations=[
                {
                    "source": "moneycontrol_rss",
                    "headline": "Reliance Industries refining margins improve in Q2",
                    "url": "https://www.moneycontrol.com/news/business/stocks/reliance-q2-results-refining-margins-up",
                    "published_at": "2026-10-10",
                    "snippet": "Refining margins improve significantly"
                },
            ],
        ),
        ScoredCandidate(
            ticker="TATAMOTORS",
            score=48,
            tier="yellow",
            sub_score_catalyst=26,
            sub_score_momentum=19,
            sub_score_macro=15,
            haiku_reasoning=(
                "JLR wholesale volumes recovering per latest commentary; "
                "EV launch date announced. Auto sector showing mixed momentum. "
                "Rate decision upcoming as macro risk."
            ),
            citations=[
                {
                    "source": "moneycontrol_rss",
                    "headline": "Tata Motors JLR volumes show recovery signs",
                    "url": "https://www.moneycontrol.com/news/business/stocks/tata-motors-jlr-recovery",
                    "published_at": "2026-10-08",
                    "snippet": "JLR wholesale showing improvement"
                },
            ],
        ),
    ]


@pytest.mark.asyncio
async def test_live_compilation_preserves_score_and_tier(realistic_candidates):
    """Live test: verify Sonnet compilation preserves score/tier invariant.

    This runs against the REAL Sonnet API when COMPILATION_LIVE=1 is set.
    Verifies: (1) result covers all input tickers, (2) polished text is
    non-empty and distinct from raw Haiku reasoning, (3) merge preserves
    score/tier byte-for-byte, (4) CompiledIdea has no score/tier field.
    """
    session = SonnetCompilationSession()
    result = await session.run_compilation(realistic_candidates)

    # Verify: all tickers present in result
    assert set(result.ideas.keys()) == {c.ticker for c in realistic_candidates}

    # Verify: polished text is present and distinct
    for candidate in realistic_candidates:
        compiled_idea = result.ideas[candidate.ticker]
        assert compiled_idea.polished_rationale, f"{candidate.ticker}: polished_rationale is empty"
        assert compiled_idea.ranking_commentary_fragment, f"{candidate.ticker}: ranking_commentary_fragment is empty"
        # Verify it's not just a copy of the raw reasoning
        assert compiled_idea.polished_rationale != candidate.haiku_reasoning
        print(f"\n{candidate.ticker} polished rationale:\n{compiled_idea.polished_rationale}")

    # Verify: overall ranking commentary present
    assert result.overall_ranking_commentary
    print(f"\nOverall ranking commentary:\n{result.overall_ranking_commentary}")

    # Verify: CompiledIdea has no score/tier
    compiled_idea_fields = {f.name for f in dataclasses.fields(CompiledIdea)}
    assert "score" not in compiled_idea_fields
    assert "tier" not in compiled_idea_fields

    # Verify: merge preserves score/tier
    merged = merge_compilation_into_candidates(realistic_candidates, result)
    for orig, merged_cand in zip(realistic_candidates, merged):
        assert merged_cand.score == orig.score, \
            f"{orig.ticker}: score {merged_cand.score} != original {orig.score}"
        assert merged_cand.tier == orig.tier, \
            f"{orig.ticker}: tier {merged_cand.tier} != original {orig.tier}"
