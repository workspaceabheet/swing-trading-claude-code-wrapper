"""JSON parsing for Haiku sweep and deep-dive responses.

Strict key presence and type validation, raising ValueError on malformed responses.
Mirrors claude_scoring.py's parse_json_object pattern from the sibling repo.
"""

import json
from app.agent.sessions import ShortlistCandidate, DeepDiveResult, Citation


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
        # strict=False: real Haiku/Sonnet output has been observed to embed
        # literal unescaped control characters (e.g. a raw newline) inside a
        # JSON string value rather than escaping it as \n. That's still
        # unambiguous, parseable content -- Python's default strict=True
        # mode rejects it outright ("Invalid control character"), which
        # crashed an entire call over one cosmetic formatting quirk.
        # strict=False accepts it without weakening any of the structural
        # validation that follows (required keys, types, bounds).
        obj = json.loads(text, strict=False)
        if not isinstance(obj, dict):
            raise ValueError(f"Expected JSON object, got {type(obj).__name__}")
        return obj
    except json.JSONDecodeError as e:
        raise ValueError(f"Malformed JSON: {e}") from e


def parse_sweep_response(raw: str) -> list[ShortlistCandidate]:
    """Parse Haiku's sweep response into a shortlist.

    Args:
        raw: Raw text from Haiku, expected to contain a JSON object with
             a 'shortlist' key containing a list of candidates.

    Returns:
        list[ShortlistCandidate]

    Raises:
        ValueError: On malformed JSON or missing/incorrect fields.
    """
    obj = parse_json_object(raw)

    if "shortlist" not in obj:
        raise ValueError("Response missing required 'shortlist' key")

    shortlist_data = obj["shortlist"]
    if not isinstance(shortlist_data, list):
        raise ValueError(
            f"'shortlist' must be a list, got {type(shortlist_data).__name__}"
        )

    candidates = []
    for i, item in enumerate(shortlist_data):
        if not isinstance(item, dict):
            raise ValueError(
                f"shortlist[{i}] must be an object, got {type(item).__name__}"
            )

        if "ticker" not in item:
            raise ValueError(f"shortlist[{i}] missing 'ticker' key")
        if "reason" not in item:
            raise ValueError(f"shortlist[{i}] missing 'reason' key")

        ticker = item["ticker"]
        reason = item["reason"]

        if not isinstance(ticker, str) or not ticker.strip():
            raise ValueError(f"shortlist[{i}].ticker must be a non-empty string")
        if not isinstance(reason, str) or not reason.strip():
            raise ValueError(f"shortlist[{i}].reason must be a non-empty string")

        candidates.append(ShortlistCandidate(ticker=ticker, reason=reason))

    return candidates


def parse_deep_dive_response(raw: str, ticker: str) -> DeepDiveResult:
    """Parse Haiku's deep-dive response into a DeepDiveResult.

    Args:
        raw: Raw text from Haiku, expected to contain a JSON object with
             sub-score, reasoning, negative-filter, and citation fields.
        ticker: The ticker this deep-dive is for (used in the result).

    Returns:
        DeepDiveResult

    Raises:
        ValueError: On malformed JSON or missing/incorrect fields.
    """
    obj = parse_json_object(raw)

    # Required fields with type and range validation
    required_fields = {
        "catalyst_subscore": (int, (0, 40)),
        "catalyst_reasoning": (str, None),
        "sector_momentum_subscore": (int, (0, 35)),
        "sector_momentum_reasoning": (str, None),
        "macro_subscore": (int, None),  # Special: must be one of 15, 20, 25
        "macro_reasoning": (str, None),
        "promotional_chatter_flag": (bool, None),
        "promotional_reasoning": (str, None),
        "catalyst_mentioned_date": (str, None),
        "expected_move_pct": (float, (-20.0, 30.0)),  # see validation block below
        "hold_days": (int, (3, 14)),                  # see validation block below
        "citations": (list, None),
    }

    # Check all required fields are present
    for field_name in required_fields:
        if field_name not in obj:
            raise ValueError(f"Response missing required '{field_name}' key")

    # Validate types and ranges
    catalyst_subscore = obj["catalyst_subscore"]
    if not isinstance(catalyst_subscore, int):
        raise TypeError(
            f"catalyst_subscore must be int, got {type(catalyst_subscore).__name__}"
        )
    if not (0 <= catalyst_subscore <= 40):
        raise ValueError(f"catalyst_subscore {catalyst_subscore} out of range [0, 40]")

    catalyst_reasoning = obj["catalyst_reasoning"]
    if not isinstance(catalyst_reasoning, str) or not catalyst_reasoning.strip():
        raise ValueError("catalyst_reasoning must be a non-empty string")

    sector_momentum_subscore = obj["sector_momentum_subscore"]
    if not isinstance(sector_momentum_subscore, int):
        raise TypeError(
            f"sector_momentum_subscore must be int, got {type(sector_momentum_subscore).__name__}"
        )
    if not (0 <= sector_momentum_subscore <= 35):
        raise ValueError(
            f"sector_momentum_subscore {sector_momentum_subscore} out of range [0, 35]"
        )

    sector_momentum_reasoning = obj["sector_momentum_reasoning"]
    if not isinstance(sector_momentum_reasoning, str) or not sector_momentum_reasoning.strip():
        raise ValueError("sector_momentum_reasoning must be a non-empty string")

    macro_subscore = obj["macro_subscore"]
    if not isinstance(macro_subscore, int):
        raise TypeError(
            f"macro_subscore must be int, got {type(macro_subscore).__name__}"
        )
    # Macro must be one of: 15, 20, 25 (red/yellow/green macro modifier,
    # per tech-spec.md section 6 and scoring.py's MACRO_VALID -- this must
    # stay in sync with scoring.py, not independently widened).
    valid_macro_values = {15, 20, 25}
    if macro_subscore not in valid_macro_values:
        raise ValueError(
            f"macro_subscore {macro_subscore} must be one of {sorted(valid_macro_values)}"
        )

    macro_reasoning = obj["macro_reasoning"]
    if not isinstance(macro_reasoning, str) or not macro_reasoning.strip():
        raise ValueError("macro_reasoning must be a non-empty string")

    promotional_chatter_flag = obj["promotional_chatter_flag"]
    if not isinstance(promotional_chatter_flag, bool):
        raise TypeError(
            f"promotional_chatter_flag must be bool, got {type(promotional_chatter_flag).__name__}"
        )

    promotional_reasoning = obj["promotional_reasoning"]
    if not isinstance(promotional_reasoning, str) or not promotional_reasoning.strip():
        raise ValueError("promotional_reasoning must be a non-empty string")

    catalyst_mentioned_date = obj["catalyst_mentioned_date"]
    if not isinstance(catalyst_mentioned_date, str) or not catalyst_mentioned_date.strip():
        raise ValueError("catalyst_mentioned_date must be a non-empty string (ISO date)")

    # expected_move_pct and hold_days (tech-spec §4 FR6/§8): Haiku's signal,
    # consumed by run_orchestrator to deterministically compute target price
    # (entry * (1 + expected_move_pct/100)) and persist hold_days as-is.
    # Bounds are a defense-in-depth backstop mirroring macro_subscore's
    # {15,20,25} check -- out-of-range/wrong-type values raise ValueError/
    # TypeError so the orchestrator's per-ticker skip-and-continue isolates
    # just this candidate, never the whole run.
    expected_move_pct = obj["expected_move_pct"]
    if isinstance(expected_move_pct, bool) or not isinstance(expected_move_pct, (int, float)):
        raise TypeError(
            f"expected_move_pct must be a number, got {type(expected_move_pct).__name__}"
        )
    expected_move_pct = float(expected_move_pct)
    if not (-20.0 <= expected_move_pct <= 30.0):
        raise ValueError(f"expected_move_pct {expected_move_pct} out of range [-20, 30]")

    hold_days = obj["hold_days"]
    if not isinstance(hold_days, int) or isinstance(hold_days, bool):
        raise TypeError(f"hold_days must be int, got {type(hold_days).__name__}")
    if not (3 <= hold_days <= 14):
        raise ValueError(f"hold_days {hold_days} out of range [3, 14]")

    # Parse citations
    citations_data = obj["citations"]
    if not isinstance(citations_data, list):
        raise ValueError(
            f"citations must be a list, got {type(citations_data).__name__}"
        )

    if not citations_data:
        raise ValueError("citations must contain at least one citation")

    citations = []
    for i, citation_obj in enumerate(citations_data):
        if not isinstance(citation_obj, dict):
            raise ValueError(
                f"citations[{i}] must be an object, got {type(citation_obj).__name__}"
            )

        required_citation_fields = {"source", "url", "headline", "published_at"}
        for field in required_citation_fields:
            if field not in citation_obj:
                raise ValueError(f"citations[{i}] missing required '{field}' key")

        source = citation_obj["source"]
        url = citation_obj["url"]
        headline = citation_obj["headline"]
        published_at = citation_obj["published_at"]

        if not isinstance(source, str) or not source.strip():
            raise ValueError(f"citations[{i}].source must be a non-empty string")
        if not isinstance(url, str) or not url.strip():
            raise ValueError(f"citations[{i}].url must be a non-empty string")
        if not isinstance(headline, str) or not headline.strip():
            raise ValueError(f"citations[{i}].headline must be a non-empty string")
        if not isinstance(published_at, str) or not published_at.strip():
            raise ValueError(f"citations[{i}].published_at must be a non-empty string")

        citations.append(Citation(
            source=source,
            headline=headline,
            url=url,
            published_at=published_at,
        ))

    return DeepDiveResult(
        ticker=ticker,
        catalyst_subscore=catalyst_subscore,
        catalyst_reasoning=catalyst_reasoning,
        sector_momentum_subscore=sector_momentum_subscore,
        sector_momentum_reasoning=sector_momentum_reasoning,
        macro_subscore=macro_subscore,
        macro_reasoning=macro_reasoning,
        promotional_chatter_flag=promotional_chatter_flag,
        catalyst_mentioned_date=catalyst_mentioned_date,
        expected_move_pct=expected_move_pct,
        hold_days=hold_days,
        citations=citations,
    )
