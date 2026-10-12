# Slice 5 — Detailed Technical Plan: Deterministic Scoring Module (FR6)

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 5 only
**Inputs (locked, not reopened):** `tech-spec.md` §4 (FR5, FR6), §6 (scoring rubric), §9 (acceptance criteria); `vertical-slice-plan.md` Slice 5 section (lines 257-291); `plan-detailed/slice-0.md` schema (`ideas.score`, `ideas.sub_score_catalyst`, `ideas.sub_score_momentum`, `ideas.sub_score_macro`, `ideas.tier` — columns already declared as placeholders, reused here, not renamed).
**Precedent repo:** `ai-job-finder-console/app/scoring_math.py` (`compute_final_score`) — referenced for pattern shape only; the exact arithmetic differs (see §1 below).

---

## 1. Decided arithmetic: sub-scores are already pre-scaled to their weighted band — `compute_score` sums them, it does not apply weighting itself

This is the single most important design decision in this slice and is made explicit because the spec's §6 wording is terse enough to admit two readings.

**tech-spec.md §6 says:**
- Catalyst strength — 40%: scored **0-40** across weak/moderate/major bands.
- Sector momentum — 35%: scored **0-35** based on recent trend.
- Macro risk modifier — 25%: scored **0-25** (green macro = 25, yellow = 20, red = 15).

The sibling job-finder project's `compute_final_score` takes 0-4 raw sub-criteria from the LLM and applies the weighting arithmetic itself (`sub.skills * 0.45 + ...`, then scales `/4.0 * 100`). **This project does not mirror that pattern.** Here, the sub-score *ranges themselves* are already the weighted contribution — Haiku (Slice 4) is instructed to output `catalyst_subscore` directly on a 0-40 scale, `sector_subscore` directly on a 0-35 scale, and `macro_subscore` directly on a 0-25 scale (one of exactly three values: 15, 20, or 25). There is no additional weighting multiplication to apply in `scoring.py` — the three inputs are **already weighted and already on 0-100-comparable units**. `compute_score`'s entire arithmetic is:

```
score = catalyst_subscore + sector_subscore + macro_subscore
```

**Why this reading over the job-finder-style reading:** (1) §6's own band language ("scored 0-40", "scored 0-35", "scored 0-25", with macro's three *named* values 15/20/25) describes output ranges, not raw 0-4 criteria needing a weight multiplier — if the spec author intended a 0-4-then-weighted scheme it would have said "0-4, weighted 40%" the way job-finder's spec presumably did; instead it directly states the post-weighting numeric range. (2) The macro modifier is defined by exactly three discrete values (15/20/25), which only makes sense as an already-final contribution — multiplying a 0-4 raw score by 25% would never land exactly on 15/20/25 for a small integer domain in the way the spec implies. (3) Keeping Haiku's output directly in the final units removes one more place (weighting math) where Haiku's text output could introduce drift, which matches FR6's intent that application code be "the only code path that produces the final tier" — the less arithmetic `scoring.py` has to perform, the smaller the surface for a mismatch between what Slice 4's prompt asks Haiku for and what `scoring.py` assumes.

**Cross-check requirement for Slice 4's agent:** Slice 4's `DeepDiveResult`/prompt must ask Haiku to return:
- `catalyst_subscore: int` in `[0, 40]`
- `sector_subscore: int` in `[0, 35]`
- `macro_subscore: int` that is **one of exactly `{15, 20, 25}`** (not an arbitrary 0-25 integer — the spec's band language is categorical: green macro environment = 25, yellow = 20, red = 15, there is no "22" or "18")

If Slice 4's agent instead scopes Haiku's sub-scores as raw 0-4 (job-finder-style) or as a continuous 0-25 macro value, that is a mismatch against this plan and must be reconciled before Slice 5 is implemented — flag to the orchestrator/user if Slice 4's output lands differently than the three ranges above.

`compute_score` validates its inputs defensively (see §3) and raises on out-of-range input rather than silently clamping, so a mismatch between Slice 4's actual output and this contract fails loudly in integration tests rather than silently producing a wrong tier.

---

## 2. File to create

| Path | Responsibility |
|---|---|
| `app/scoring.py` | Pure module. Zero imports from `app.agent.*`, zero imports of any LLM/SDK type. `compute_score(catalyst_subscore, sector_subscore, macro_subscore) -> ScoreResult`. No I/O, no DB access, no randomness — a plain function of its three integer inputs. |

No other files are modified to *implement* scoring itself; orchestrator wiring (a one-line call site) is described in §5 but is a small edit to the existing `app/run_orchestrator.py`, not a new module.

---

## 3. Exact interface

```python
# app/scoring.py
from dataclasses import dataclass
from typing import Literal

Tier = Literal["red", "yellow", "green"]

CATALYST_MIN, CATALYST_MAX = 0, 40
SECTOR_MIN, SECTOR_MAX = 0, 35
MACRO_VALID = frozenset({15, 20, 25})  # red, yellow, green macro modifier

GREEN_THRESHOLD = 70   # score >= 70 -> green
YELLOW_THRESHOLD = 50  # 50 <= score < 70 -> yellow; score < 50 -> red


@dataclass(frozen=True)
class ScoreResult:
    score: int                 # 0-100, sum of the three sub-scores
    tier: Tier                 # "red" | "yellow" | "green"
    catalyst_subscore: int      # echoed back unchanged, for persistence convenience
    sector_subscore: int        # echoed back unchanged
    macro_subscore: int         # echoed back unchanged


def compute_score(
    catalyst_subscore: int,
    sector_subscore: int,
    macro_subscore: int,
) -> ScoreResult:
    """Pure, deterministic. Sums three already-weighted sub-scores (see
    slice-5.md §1 for why no further weighting is applied here) and assigns
    a tier from fixed thresholds. Raises ValueError on out-of-band input —
    never silently clamps, so a Slice-4 contract mismatch fails loudly.
    """
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

    score = catalyst_subscore + sector_subscore + macro_subscore  # max 100, min 0

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
```

Threshold boundaries, exact and inclusive per §6:
- `score >= 70` → green (70-100 inclusive).
- `50 <= score < 70` → yellow.
- `score < 50` → red.

So `69` is yellow, `70` is green; `49` is red, `50` is yellow — both boundaries tested explicitly (§6 below).

---

## 4. Table-driven test cases

### `tests/test_scoring.py`

Run with: `pytest tests/test_scoring.py -v`

**Threshold boundary table** (catalyst/sector/macro chosen so their sum lands exactly on each boundary; macro fixed at 20 (yellow-macro) across most rows to isolate the boundary, with a couple of rows varying macro too):

| catalyst | sector | macro | expected score | expected tier | note |
|---|---|---|---|---|---|
| 20 | 15 | 15 | 50 | yellow | red/yellow boundary, low side of yellow |
| 20 | 14 | 15 | 49 | red | 49/50 boundary — red side |
| 20 | 15 | 15 | 50 | yellow | 49/50 boundary — yellow side (duplicate of row 1, kept for explicit pairing) |
| 25 | 25 | 20 | 70 | green | yellow/green boundary — green side |
| 25 | 24 | 20 | 69 | yellow | 69/70 boundary — yellow side |
| 0 | 0 | 15 | 15 | red | absolute floor (all-zero catalyst/sector, worst macro) |
| 40 | 35 | 25 | 100 | green | absolute ceiling |

**Catalyst band table** (weak/moderate/major — exact numeric sub-ranges within 0-40 are Slice 4's prompt-design concern, not Slice 5's; this table only needs representative values spanning the 0-40 domain since `compute_score` itself is band-agnostic once it receives an integer in range):

| catalyst | sector | macro | expected score | expected tier | band label (for readability only) |
|---|---|---|---|---|---|
| 5 | 20 | 20 | 45 | red | weak catalyst |
| 20 | 20 | 20 | 60 | yellow | moderate catalyst |
| 38 | 20 | 20 | 78 | green | major catalyst |

**Sector-momentum band table:**

| catalyst | sector | macro | expected score | expected tier | band label |
|---|---|---|---|---|---|
| 25 | 5 | 20 | 50 | yellow | weak/negative momentum |
| 25 | 20 | 20 | 65 | yellow | moderate momentum |
| 25 | 35 | 20 | 80 | green | strong momentum |

**Macro-modifier band table (every one of the three fixed values, per §6):**

| catalyst | sector | macro | expected score | expected tier | macro band |
|---|---|---|---|---|---|
| 30 | 25 | 15 | 70 | green | macro = red (15) |
| 30 | 25 | 20 | 75 | green | macro = yellow (20) |
| 30 | 25 | 25 | 80 | green | macro = green (25) |

**Invalid-input table (defensive validation, per §3's "raise, don't clamp" decision):**

| catalyst | sector | macro | expected behavior |
|---|---|---|---|
| 41 | 20 | 20 | raises `ValueError` (catalyst over max) |
| -1 | 20 | 20 | raises `ValueError` (catalyst under min) |
| 20 | 36 | 20 | raises `ValueError` (sector over max) |
| 20 | 20 | 18 | raises `ValueError` (macro not in {15,20,25}) |
| 20 | 20 | 0 | raises `ValueError` (macro not in {15,20,25}) |

Each table above is implemented as a single `pytest.mark.parametrize`-decorated test function (4-5 parametrized test functions total in `tests/test_scoring.py`, not one test per row written by hand) — e.g.:

```python
import pytest
from app.scoring import compute_score

BOUNDARY_CASES = [
    (20, 15, 15, 50, "yellow"),
    (20, 14, 15, 49, "red"),
    (25, 25, 20, 70, "green"),
    (25, 24, 20, 69, "yellow"),
    (0, 0, 15, 15, "red"),
    (40, 35, 25, 100, "green"),
]

@pytest.mark.parametrize("catalyst,sector,macro,expected_score,expected_tier", BOUNDARY_CASES)
def test_threshold_boundaries(catalyst, sector, macro, expected_score, expected_tier):
    result = compute_score(catalyst, sector, macro)
    assert result.score == expected_score
    assert result.tier == expected_tier
```

(Repeat the pattern for the catalyst-band, sector-band, macro-band, and invalid-input tables.)

### Integration test: `tests/test_run_orchestrator_scoring.py` (or added to the existing orchestrator integration test file from Slice 4)
- `test_fake_run_scores_match_standalone_compute_score` — run the full fake-driven pipeline (Slice 4's `FakeHaikuSession` with its canned sub-scores), then for each resulting idea in the persisted run, call `compute_score` standalone with that idea's persisted `sub_score_catalyst`/`sub_score_momentum`/`sub_score_macro` and assert the persisted `score`/`tier` match exactly. This proves orchestrator wiring didn't silently diverge from the pure function (e.g., no accidental double-counting, no stale cached tier).

Command to run all scoring tests: `pytest tests/test_scoring.py tests/test_run_orchestrator_scoring.py -v`

---

## 5. Orchestrator wiring

Slice 4 leaves the orchestrator with a step that, for each surviving shortlisted candidate, has called `FakeHaikuSession.run_deep_dive(ticker, context)` and obtained an object carrying (at minimum) `catalyst_subscore`, `sector_subscore`, `macro_subscore`, plus reasoning/citations. Slice 5 adds exactly one new step immediately after that deep-dive loop and before persistence:

```python
# app/run_orchestrator.py (excerpt — new step inserted after the deep-dive loop,
# before negative filtering (Slice 6) and before persistence)
from app.scoring import compute_score

for candidate in deep_dive_results:
    result = compute_score(
        candidate.catalyst_subscore,
        candidate.sector_subscore,
        candidate.macro_subscore,
    )
    candidate.score = result.score
    candidate.tier = result.tier
```

Placement relative to other stages, per the locked vertical-slice-plan sequencing (Slice 5's section explicitly runs before Slice 6's negative filtering is added, and the spec's §5 step list numbers scoring before negative filtering: "...(5) deterministic scoring, (6) negative filtering..."):

```
... Haiku deep-dive loop (Slice 4)
  -> compute_score per candidate (Slice 5, this slice)
  -> negative_filters.evaluate(...) per candidate (Slice 6, next slice)
  -> Sonnet compilation (Slice 8)
  -> output assembly / cap / backfill (Slice 9)
  -> persistence
```

Note for Slice 6's author: `compute_score` is called on **every** surviving deep-dive candidate, including ones that Slice 6 will go on to exclude for pump-and-dump/stale-news reasons — a candidate's score/tier is computed unconditionally first, and negative filtering is a separate, later gate that removes candidates from the list regardless of how good their score looks. This matches the spec's wording that negative filtering is a property of the deep-dive stage, independent of scoring, and avoids a Slice-6 implementation having to special-case "don't bother scoring something we're about to exclude anyway" (scoring is cheap and pure, so there's no cost reason to skip it).

Persistence: `ideas.score`, `ideas.tier`, `ideas.sub_score_catalyst`, `ideas.sub_score_momentum`, `ideas.sub_score_macro` columns already exist from Slice 0's schema (declared as nullable placeholders) — Slice 5 is the first slice to write real, non-null values into them. No schema migration needed.

UI: the existing idea-card template (from Slice 0) already renders a `tier` badge from placeholder data; Slice 5 changes nothing in the template — the same binding now receives real computed values instead of `null`/hardcoded `"green"`.

---

## 6. Manual verification

1. Trigger a run (fake-session-backed, per Slice 4's dev config).
2. Open the run detail page, pick any one idea card. Note its displayed `sub_score_catalyst`, `sub_score_momentum` (persisted as `sector_subscore` conceptually — see note below on naming), `sub_score_macro`, and the displayed `score`/`tier` badge.
3. By hand: `score = sub_score_catalyst + sub_score_momentum + sub_score_macro`. Confirm it matches the badge's score exactly.
4. Apply the thresholds by hand (`>=70` green, `50-69` yellow, `<50` red) and confirm the tier badge matches.
5. Repeat for at least 2-3 cards spanning different tiers (the fake session's canned candidates should be chosen in Slice 4 to span at least one of each tier, or this manual check should use `pytest -k test_threshold_boundaries -v` output alongside a live card as a substitute if the fake data doesn't happen to produce all three tiers in one run).

**Naming note:** `tech-spec.md`'s own §6 prose calls the second criterion "sector momentum," while `plan-detailed/slice-0.md`'s schema names the column `sub_score_momentum` (not `sub_score_sector_momentum`). This plan reuses the existing column name as instructed (not renaming it) — `compute_score`'s `sector_subscore` parameter maps to the `sub_score_momentum` column at the orchestrator-wiring boundary (§5's assignment `candidate.sector_subscore` is the in-memory/dataclass field name; the DB column it's written to is `sub_score_momentum`). This is a naming seam the orchestrator code must bridge explicitly (e.g., `row["sub_score_momentum"] = result.sector_subscore`), not a scoring-module concern.

---

## 7. Acceptance criteria and verification evidence

- [ ] `compute_score` reproduces the documented formula exactly for every table-driven case in §4, including every threshold boundary (49/50, 69/70) and every catalyst/sector/macro band. **Evidence:** `pytest tests/test_scoring.py -v` — all parametrized cases pass, zero skips.
- [ ] Invalid/out-of-band sub-score input raises `ValueError` rather than silently clamping or producing an incorrect tier. **Evidence:** the invalid-input parametrized test in `tests/test_scoring.py` passes.
- [ ] The score/tier is identical regardless of anything downstream — re-running `compute_score` standalone with the same three integers always yields the same `ScoreResult` (pure-function property; no hidden state). **Evidence:** test functions call `compute_score` twice with identical args in at least one case and assert equal results (trivial but explicit, since purity is the entire point of FR6).
- [ ] A full fake-driven orchestrator run's persisted `score`/`tier` for every idea exactly matches what `compute_score` produces standalone for that idea's persisted sub-scores. **Evidence:** `test_fake_run_scores_match_standalone_compute_score` passes.
- [ ] Idea cards in the UI display the real computed score/tier (not a placeholder). **Evidence:** manual verification steps in §6, performed and hand-confirmed by the user for at least 2-3 cards.
- [ ] `app/scoring.py` has zero imports of any LLM/SDK/network/DB module (pure-module guarantee). **Evidence:** `grep -n "^import\|^from" app/scoring.py` shows only `dataclasses`/`typing` imports.

Slice 5 is complete only when every checkbox above is verified with the stated evidence, not merely claimed.
