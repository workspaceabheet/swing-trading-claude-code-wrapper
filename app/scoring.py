"""Slice 5: Deterministic scoring module (FR6).

Pure, stateless function to compute a 0-100 score and assign a tier
from three pre-weighted sub-scores. No imports of LLM/SDK/network/DB
modules; no side effects; no randomness.

The three input ranges match tech-spec.md §6:
- catalyst_subscore: 0-40 (weak/moderate/major catalyst bands)
- sector_subscore: 0-35 (sector momentum)
- macro_subscore: exactly {15, 20, 25} (red/yellow/green macro modifier)

The score is simply the sum of these three pre-weighted values (already in
their final units, not raw 0-4 values that would be multiplied by weights).
The tier is assigned from fixed thresholds: green >=70, yellow 50-69, red <50.

See slice-5.md §1 for the design rationale (why the sub-scores are
pre-weighted and why no further weighting arithmetic is applied here).
"""

from dataclasses import dataclass
from typing import Literal

# Type alias for the three valid tier values
Tier = Literal["red", "yellow", "green"]

# Hardcoded ranges per tech-spec.md §6
CATALYST_MIN, CATALYST_MAX = 0, 40
SECTOR_MIN, SECTOR_MAX = 0, 35
MACRO_VALID = frozenset({15, 20, 25})  # red=15, yellow=20, green=25

# Tier thresholds (inclusive on the left, exclusive on the right)
GREEN_THRESHOLD = 70   # score >= 70 -> green
YELLOW_THRESHOLD = 50  # 50 <= score < 70 -> yellow; score < 50 -> red


@dataclass(frozen=True)
class ScoreResult:
    """Result of compute_score. All fields are immutable (frozen=True)."""

    score: int  # 0-100, the sum of the three sub-scores
    tier: Tier  # "red" | "yellow" | "green"
    catalyst_subscore: int  # echoed back, for persistence convenience
    sector_subscore: int  # echoed back
    macro_subscore: int  # echoed back


def compute_score(
    catalyst_subscore: int,
    sector_subscore: int,
    macro_subscore: int,
) -> ScoreResult:
    """Compute the deterministic score and tier from three pre-weighted sub-scores.

    This is a pure function: same input always yields the same output, no
    side effects, no external dependencies.

    Args:
        catalyst_subscore: Integer in [0, 40].
        sector_subscore: Integer in [0, 35].
        macro_subscore: Integer in exactly {15, 20, 25} (no other values).

    Returns:
        ScoreResult with score (0-100), tier ("red"/"yellow"/"green"),
        and the three input sub-scores echoed back.

    Raises:
        ValueError: If any input is out of the specified range. Never
            silently clamps; out-of-band input is an error, not a warning,
            so a mismatch between Slice 4's actual output and this contract
            fails loudly in integration tests rather than producing a wrong tier.
    """
    # Defensive validation: raise, don't clamp
    if not (CATALYST_MIN <= catalyst_subscore <= CATALYST_MAX):
        raise ValueError(
            f"catalyst_subscore {catalyst_subscore} out of band "
            f"[{CATALYST_MIN}, {CATALYST_MAX}]"
        )
    if not (SECTOR_MIN <= sector_subscore <= SECTOR_MAX):
        raise ValueError(
            f"sector_subscore {sector_subscore} out of band "
            f"[{SECTOR_MIN}, {SECTOR_MAX}]"
        )
    if macro_subscore not in MACRO_VALID:
        raise ValueError(
            f"macro_subscore {macro_subscore} must be one of {sorted(MACRO_VALID)}"
        )

    # Sum the three pre-weighted sub-scores (0-100 range)
    score = catalyst_subscore + sector_subscore + macro_subscore

    # Assign tier from fixed thresholds
    if score >= GREEN_THRESHOLD:
        tier: Tier = "green"
    elif score >= YELLOW_THRESHOLD:
        tier = "yellow"
    else:
        tier = "red"

    return ScoreResult(
        score=score,
        tier=tier,
        catalyst_subscore=catalyst_subscore,
        sector_subscore=sector_subscore,
        macro_subscore=macro_subscore,
    )
