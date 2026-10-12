"""Slice 5: Tests for the deterministic scoring module (FR6).

Table-driven tests covering every threshold boundary (49/50, 69/70),
every catalyst/sector/macro band, and defensive validation of out-of-band inputs.
"""

import pytest
from app.scoring import compute_score


# Threshold boundary test cases (all boundaries exact and inclusive)
BOUNDARY_CASES = [
    # (catalyst, sector, macro, expected_score, expected_tier, note)
    (20, 15, 15, 50, "yellow", "49/50 boundary — red side"),
    (20, 14, 15, 49, "red", "49/50 boundary — red side"),
    (25, 25, 20, 70, "green", "69/70 boundary — green side"),
    (25, 24, 20, 69, "yellow", "69/70 boundary — yellow side"),
    (0, 0, 15, 15, "red", "absolute floor"),
    (40, 35, 25, 100, "green", "absolute ceiling"),
]


@pytest.mark.parametrize("catalyst,sector,macro,expected_score,expected_tier", [
    (c, s, m, score, tier) for c, s, m, score, tier, _ in BOUNDARY_CASES
])
def test_threshold_boundaries(catalyst, sector, macro, expected_score, expected_tier):
    """Test every threshold boundary (49/50, 69/70) and absolute extremes."""
    result = compute_score(catalyst, sector, macro)
    assert result.score == expected_score
    assert result.tier == expected_tier
    # Verify echoed-back sub-scores
    assert result.catalyst_subscore == catalyst
    assert result.sector_subscore == sector
    assert result.macro_subscore == macro


# Catalyst band table (weak/moderate/major)
CATALYST_BAND_CASES = [
    # (catalyst, sector, macro, expected_score, expected_tier, band_label)
    (5, 20, 20, 45, "red", "weak catalyst"),
    (20, 20, 20, 60, "yellow", "moderate catalyst"),
    (38, 20, 20, 78, "green", "major catalyst"),
]


@pytest.mark.parametrize("catalyst,sector,macro,expected_score,expected_tier", [
    (c, s, m, score, tier) for c, s, m, score, tier, _ in CATALYST_BAND_CASES
])
def test_catalyst_band_isolation(catalyst, sector, macro, expected_score, expected_tier):
    """Test catalyst band effects (weak/moderate/major) with fixed sector/macro."""
    result = compute_score(catalyst, sector, macro)
    assert result.score == expected_score
    assert result.tier == expected_tier


# Sector momentum band table
SECTOR_BAND_CASES = [
    # (catalyst, sector, macro, expected_score, expected_tier, band_label)
    (25, 5, 20, 50, "yellow", "weak/negative momentum"),
    (25, 20, 20, 65, "yellow", "moderate momentum"),
    (25, 35, 20, 80, "green", "strong momentum"),
]


@pytest.mark.parametrize("catalyst,sector,macro,expected_score,expected_tier", [
    (c, s, m, score, tier) for c, s, m, score, tier, _ in SECTOR_BAND_CASES
])
def test_sector_momentum_band_isolation(catalyst, sector, macro, expected_score, expected_tier):
    """Test sector momentum band effects with fixed catalyst/macro."""
    result = compute_score(catalyst, sector, macro)
    assert result.score == expected_score
    assert result.tier == expected_tier


# Macro modifier band table (exactly {15, 20, 25})
MACRO_BAND_CASES = [
    # (catalyst, sector, macro, expected_score, expected_tier, macro_band_label)
    (30, 25, 15, 70, "green", "macro = red (15)"),
    (30, 25, 20, 75, "green", "macro = yellow (20)"),
    (30, 25, 25, 80, "green", "macro = green (25)"),
]


@pytest.mark.parametrize("catalyst,sector,macro,expected_score,expected_tier", [
    (c, s, m, score, tier) for c, s, m, score, tier, _ in MACRO_BAND_CASES
])
def test_macro_modifier_band_isolation(catalyst, sector, macro, expected_score, expected_tier):
    """Test macro modifier band effects (red/yellow/green) with fixed catalyst/sector."""
    result = compute_score(catalyst, sector, macro)
    assert result.score == expected_score
    assert result.tier == expected_tier


# Invalid input validation (should raise ValueError, not clamp or silently succeed)
INVALID_INPUT_CASES = [
    # (catalyst, sector, macro, expected_error_substring)
    (41, 20, 20, "catalyst_subscore 41 out of band"),  # catalyst over max
    (-1, 20, 20, "catalyst_subscore -1 out of band"),  # catalyst under min
    (20, 36, 20, "sector_subscore 36 out of band"),     # sector over max
    (20, -1, 20, "sector_subscore -1 out of band"),     # sector under min
    (20, 20, 18, "macro_subscore 18 must be one of"),   # macro not in {15,20,25}
    (20, 20, 0, "macro_subscore 0 must be one of"),     # macro not in {15,20,25}
    (20, 20, 30, "macro_subscore 30 must be one of"),   # macro not in {15,20,25}
]


@pytest.mark.parametrize("catalyst,sector,macro,expected_error", INVALID_INPUT_CASES)
def test_invalid_input_raises_valueerror(catalyst, sector, macro, expected_error):
    """Test that out-of-band input raises ValueError (never silently clamps)."""
    with pytest.raises(ValueError, match=expected_error):
        compute_score(catalyst, sector, macro)


def test_compute_score_is_pure():
    """Test that compute_score is pure: same input always yields identical output."""
    # Call twice with identical inputs
    result1 = compute_score(25, 20, 20)
    result2 = compute_score(25, 20, 20)
    # Results must be equal (both value and reference equality for frozen dataclass)
    assert result1 == result2
    assert result1.score == result2.score
    assert result1.tier == result2.tier
    assert result1.catalyst_subscore == result2.catalyst_subscore
    assert result1.sector_subscore == result2.sector_subscore
    assert result1.macro_subscore == result2.macro_subscore


def test_scoreresult_is_immutable():
    """Verify ScoreResult is frozen and immutable."""
    result = compute_score(25, 20, 20)
    # Attempting to modify a frozen dataclass raises FrozenInstanceError
    with pytest.raises(Exception):  # FrozenInstanceError is the expected type
        result.score = 999
