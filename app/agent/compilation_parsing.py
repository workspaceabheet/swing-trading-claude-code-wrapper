"""JSON parsing for Sonnet compilation stage responses.

Strict key presence and type validation, raising ValueError on malformed responses.
Mirrors haiku_parsing.py's parse_json_object pattern.
"""

import json
from app.agent.sessions import CompiledIdea, CompilationResult


def parse_json_object(raw: str) -> dict:
    """Parse a single JSON object from raw text, raising ValueError on parse error.

    Handles markdown code fencing (```json ... ```) that models sometimes output
    despite explicit "no markdown" instructions.
    """
    import re
    text = raw.strip()

    # Try to extract JSON from markdown code fences
    # Look for ``` ... ``` blocks
    code_fence_match = re.search(r'```(?:json)?\s*\n?(.*?)\n?```', text, re.DOTALL)
    if code_fence_match:
        text = code_fence_match.group(1).strip()

    # Find the first { and last } to extract the JSON object
    first_brace = text.find('{')
    if first_brace >= 0:
        # Find the matching closing brace
        # Start from the first { and count braces
        brace_count = 0
        last_brace = -1
        for i in range(first_brace, len(text)):
            if text[i] == '{':
                brace_count += 1
            elif text[i] == '}':
                brace_count -= 1
                if brace_count == 0:
                    last_brace = i
                    break

        if last_brace > first_brace:
            text = text[first_brace:last_brace + 1]

    text = text.strip()

    try:
        # strict=False: real Sonnet/Haiku output has been observed to embed
        # literal unescaped control characters (e.g. a raw newline) inside a
        # JSON string value rather than escaping it as \n. That's still
        # unambiguous, parseable content -- Python's default strict=True
        # mode rejects it outright ("Invalid control character"), which
        # crashed an entire compilation call over one cosmetic formatting
        # quirk. strict=False accepts it without weakening any of the
        # structural validation that follows (required keys, types, bounds).
        obj = json.loads(text, strict=False)
        if not isinstance(obj, dict):
            raise ValueError(f"Expected JSON object, got {type(obj).__name__}")
        return obj
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON: {e}") from e


def parse_compilation_result(raw: str, expected_tickers: list[str]) -> CompilationResult:
    """Parse Sonnet's compilation response into a CompilationResult.

    Args:
        raw: Raw text from Sonnet, expected to contain a JSON object with
             'ideas' and 'overall_ranking_commentary' keys.
        expected_tickers: List of tickers that must be present in the result.

    Returns:
        CompilationResult

    Raises:
        ValueError: On malformed JSON or missing/incorrect fields, or if
                   any expected ticker is missing from the result.
    """
    obj = parse_json_object(raw)

    if "ideas" not in obj:
        raise ValueError("Response missing required 'ideas' key")
    if "overall_ranking_commentary" not in obj:
        raise ValueError("Response missing required 'overall_ranking_commentary' key")

    ideas_data = obj["ideas"]
    if not isinstance(ideas_data, dict):
        raise ValueError(
            f"'ideas' must be an object, got {type(ideas_data).__name__}"
        )

    overall_commentary = obj["overall_ranking_commentary"]
    if not isinstance(overall_commentary, str) or not overall_commentary.strip():
        raise ValueError("'overall_ranking_commentary' must be a non-empty string")

    # Check that all expected tickers are present
    for ticker in expected_tickers:
        if ticker not in ideas_data:
            raise ValueError(
                f"Missing ticker '{ticker}' in ideas (expected {len(expected_tickers)}, "
                f"got {len(ideas_data)})"
            )

    # Check that no extra tickers were added
    extra_tickers = set(ideas_data.keys()) - set(expected_tickers)
    if extra_tickers:
        raise ValueError(
            f"Extra tickers in ideas: {extra_tickers}; expected exactly {expected_tickers}"
        )

    # Parse each idea
    compiled_ideas = {}
    for ticker in expected_tickers:
        idea_data = ideas_data[ticker]
        if not isinstance(idea_data, dict):
            raise ValueError(f"ideas['{ticker}'] must be an object, got {type(idea_data).__name__}")

        if "polished_rationale" not in idea_data:
            raise ValueError(f"ideas['{ticker}'] missing 'polished_rationale' key")
        if "ranking_commentary_fragment" not in idea_data:
            raise ValueError(f"ideas['{ticker}'] missing 'ranking_commentary_fragment' key")

        polished_rationale = idea_data["polished_rationale"]
        ranking_commentary_fragment = idea_data["ranking_commentary_fragment"]

        if not isinstance(polished_rationale, str) or not polished_rationale.strip():
            raise ValueError(f"ideas['{ticker}'].polished_rationale must be a non-empty string")
        if not isinstance(ranking_commentary_fragment, str) or not ranking_commentary_fragment.strip():
            raise ValueError(f"ideas['{ticker}'].ranking_commentary_fragment must be a non-empty string")

        # Enforce structural invariant: CompiledIdea must NOT have score/tier fields
        # Check the raw JSON to make sure Sonnet didn't output them
        if "score" in idea_data or "tier" in idea_data:
            raise ValueError(
                f"ideas['{ticker}'] contains forbidden 'score' or 'tier' field(s) — "
                "compilation stage must never output these"
            )

        compiled_ideas[ticker] = CompiledIdea(
            ticker=ticker,
            polished_rationale=polished_rationale,
            ranking_commentary_fragment=ranking_commentary_fragment,
        )

    return CompilationResult(
        ideas=compiled_ideas,
        overall_ranking_commentary=overall_commentary,
    )
