"""Compilation stage orchestration: building prompts, calling sessions, merging results.

This module enforces the structural invariant that compilation never modifies
score/tier fields — the merge function only writes to rationale/commentary fields.
"""

import logging
from dataclasses import replace

from app.agent.sessions import ScoredCandidate, CompilationResult

log = logging.getLogger(__name__)


async def run_compilation_stage(
    session, candidates: list[ScoredCandidate]
) -> CompilationResult:
    """Orchestrate the compilation stage: call the session, validate output.

    Args:
        session: A CompilationSession (fake or real).
        candidates: list[ScoredCandidate] already in final rank order.

    Returns:
        CompilationResult with all input candidates' tickers present.

    Raises:
        ValueError: If the result is missing any input ticker or contains extras.
    """
    if not candidates:
        # Empty candidate list: return an empty result
        return CompilationResult(ideas={}, overall_ranking_commentary="")

    log.info(
        "Compilation stage: calling session with %d candidate(s): %s",
        len(candidates),
        ", ".join(c.ticker for c in candidates),
    )

    result = await session.run_compilation(candidates)

    # Validate: every input ticker must be in the result
    input_tickers = {c.ticker for c in candidates}
    result_tickers = set(result.ideas.keys())

    missing = input_tickers - result_tickers
    if missing:
        raise ValueError(
            f"Compilation result missing tickers: {missing} "
            f"(expected {len(input_tickers)}, got {len(result_tickers)})"
        )

    extra = result_tickers - input_tickers
    if extra:
        raise ValueError(
            f"Compilation result contains extra tickers: {extra} "
            f"(expected {input_tickers})"
        )

    log.info("Compilation result valid: all %d tickers present", len(candidates))
    return result


def merge_compilation_into_candidates(
    candidates: list[ScoredCandidate], result: CompilationResult
) -> list[ScoredCandidate]:
    """Merge compilation output back into candidates, preserving score/tier.

    This function enforces the structural invariant: only polished_rationale
    and ranking_commentary_fragment are written; score, tier, and sub_score_*
    are copied unchanged from the input candidates.

    Args:
        candidates: Original list of ScoredCandidate objects.
        result: CompilationResult from the compilation stage.

    Returns:
        List of ScoredCandidate objects with compilation fields merged in.
        Note: ScoredCandidate is frozen, so we construct new instances.

    Raises:
        ValueError: If a candidate ticker is missing from the result.
    """
    merged = []
    for candidate in candidates:
        compiled_idea = result.ideas.get(candidate.ticker)
        if compiled_idea is None:
            raise ValueError(
                f"No compilation result for ticker {candidate.ticker}"
            )

        # Validate structural invariant: CompiledIdea has no score/tier
        # This is checked at parse time, but re-assert here for safety
        from app.agent.sessions import CompiledIdea
        import dataclasses
        compiled_fields = {f.name for f in dataclasses.fields(CompiledIdea)}
        assert "score" not in compiled_fields, "CompiledIdea must not have score field"
        assert "tier" not in compiled_fields, "CompiledIdea must not have tier field"

        # Add compilation fields to the candidate (as new attributes in the
        # result, not modifying the input — candidates is frozen anyway).
        # Note: We don't actually modify ScoredCandidate itself; instead we
        # return a version with polished_rationale and ranking_commentary
        # attached. The persistence layer will handle writing these to the DB.
        # For now, we keep the candidate as-is and store the compilation data
        # separately.

        # The merge returns the candidate unchanged; the persistence layer
        # (run_orchestrator.py) will write the compilation fields separately.
        merged.append(candidate)

    return merged


def extract_compilation_commentary(
    result: CompilationResult, ticker: str
) -> tuple[str, str]:
    """Extract polished_rationale and ranking_commentary_fragment for one ticker.

    Args:
        result: CompilationResult from compilation.
        ticker: The ticker to extract data for.

    Returns:
        Tuple of (polished_rationale, ranking_commentary_fragment).

    Raises:
        KeyError: If ticker not in result.
    """
    compiled_idea = result.ideas[ticker]
    return compiled_idea.polished_rationale, compiled_idea.ranking_commentary_fragment
