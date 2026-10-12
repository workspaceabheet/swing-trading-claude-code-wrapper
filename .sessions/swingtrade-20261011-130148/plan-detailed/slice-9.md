# Slice 9 — Detailed Technical Plan: Output Assembly (Cap, Ordering, Red-Tier Backfill, Citation Hard-Constraint) — FR7

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 9 only
**Locked inputs (not reopened):**
- `tech-spec.md` FR7 (§4), §6 scoring/tier thresholds and red-tier backfill decision, §9 acceptance criteria for "Output cap, ordering, and citation (FR7)".
- `initial-plan.md` (project layout, Decision B lighter structure).
- `vertical-slice-plan.md` Slice 9 section (lines 411-447): pure `assemble()` function, orchestrator step 8 (after Slice 8 compilation, before persistence), UI distinct low-confidence treatment, table-driven unit tests.
- `plan-detailed/slice-0.md` schema: `ideas` table already has `low_confidence` (INTEGER bool), `rank` (INTEGER), `tier` (TEXT), `score` (INTEGER), `citation_url` (TEXT NOT NULL). These are reused, not recreated.

**User-resolved policy (overrides any ambiguity elsewhere, restated verbatim for the coder):**
1. Top-10 output fills with yellow/green ideas FIRST.
2. Only if fewer than 10 yellow/green ideas exist does the system backfill with red-tier ideas, up to 10 total.
3. Backfilled red-tier ideas must be clearly/distinctly labeled low-confidence — not just a color difference.
4. Final list order is always green > yellow > red.
5. Any idea lacking a citation is dropped before output, regardless of score — never shown.

**Assumption carried from Slice 8 (stated per task instructions, to be confirmed with the user/orchestrator, not re-decided here):** Slice 9 receives a list of "final candidates" from the Slice 8 compilation stage, each already having ticker, score, tier, polished rationale, citation(s), and exclusion status from Slice 6's negative filters. Candidates already excluded by Slice 6 never reach Slice 8 or Slice 9 — assembly operates only on *surviving* candidates and performs no re-application of negative-filter logic. If Slice 8's actual output shape differs from `FinalCandidate` as defined below, the orchestrator wiring (not `assemble()`'s internal logic) is the adapter point to fix — flag to the orchestrator/user if Slice 8 lands with a materially different shape.

---

## 1. Files to create / modify

| Path | Responsibility |
|---|---|
| `app/assembly.py` | **New.** Pure function `assemble(candidates: list[FinalCandidate]) -> list[Idea]` implementing the cap/order/backfill/citation-drop algorithm (§3 below). Zero I/O, zero LLM import, zero DB import — fully unit-testable in isolation, same philosophy as `scoring.py` (Slice 5). |
| `app/models.py` (or wherever shared dataclasses live — create if it doesn't exist yet; check for a Slice 5/8 equivalent first and extend it rather than duplicating) | Add/confirm `FinalCandidate` and `Idea` dataclasses/`TypedDict`s (§2 below). |
| `app/run_orchestrator.py` | **Modify.** Insert the assembly call as orchestrator step 8, after Slice 8's compilation step and before persistence (§5 below). |
| `app/db.py` | **No schema change required.** Confirm `low_confidence` and `rank` columns already exist per Slice 0 (they do — see schema excerpt in §4). Optionally add `backfill_reason` (nullable TEXT) — see §4 for the recommendation. |
| `app/templates/index.html` (and any run-detail/history template that renders idea cards — check Slice 0/8's actual template names before editing) | **Modify.** Add the distinct low-confidence visual treatment (§6 below): separate section header + explicit warning text, not just a color. |
| `app/static/css/main.css` | **Modify.** Add a `.low-confidence-section` / `.idea-card--low-confidence` style block distinct from tier-color badges. |
| `tests/test_assembly.py` | **New.** Table-driven unit tests (§7 below). |

---

## 2. Data model

```
FinalCandidate (input to assemble(), produced by Slice 8):
    ticker: str
    entry: float
    target: float
    hold_days: int
    tier: Literal["green", "yellow", "red"]      # immutable, from Slice 5/6, never recomputed here
    score: int                                     # immutable, 0-100, from Slice 5, never recomputed here
    sub_score_catalyst: int
    sub_score_momentum: int
    sub_score_macro: int
    rationale: str                                 # Sonnet-polished, from Slice 8
    ranking_commentary_fragment: str | None         # from Slice 8
    citations: list[Citation]                       # Citation = {source, url, headline, published_at, snippet}; may be empty list

Idea (output of assemble(), persisted via db.py, same shape as Slice 0's `ideas` row + rank/low_confidence already present):
    ticker, entry, target, hold_days, tier, score,
    sub_score_catalyst, sub_score_momentum, sub_score_macro,
    rationale, citation_url, citation_source, citation_headline,
    low_confidence: bool,          # True ONLY for backfilled red ideas; False for every yellow/green idea and for red ideas that were never reached (they are dropped, not included with low_confidence=False)
    backfill_reason: str | None,   # see §4 — "red_tier_backfill" when low_confidence is True, else None
    rank: int                      # 1..N in final order, N <= 10
```

`assemble()`'s signature:
```
def assemble(candidates: list[FinalCandidate]) -> list[Idea]:
```
Pure function. No side effects, no randomness, no wall-clock dependence. Given the same input list (including list order), it always returns the same output list.

---

## 3. Exact algorithm (pseudocode-level, precise enough to implement without guessing)

```
function assemble(candidates):
    # Step 0 — citation hard-constraint, unconditional, BEFORE any partition/sort/cap logic.
    eligible = []
    for c in candidates:
        if c.citations is not None and len(c.citations) >= 1 and c.citations[0].url is not empty/null:
            eligible.append(c)
        # else: drop c entirely. Never carried forward regardless of score or tier.
        # "at least one citation" means len(citations) >= 1 AND that citation has a non-empty url.
        # Do not special-case tier here — a green idea with no citation is dropped exactly like a red idea with no citation.

    if eligible is empty:
        return []   # zero candidates in, zero out — no crash, no fabricated rows.

    # Step 1 — partition eligible candidates by tier.
    green  = [c for c in eligible if c.tier == "green"]
    yellow = [c for c in eligible if c.tier == "yellow"]
    red    = [c for c in eligible if c.tier == "red"]

    # Step 2 — sort each tier group by score descending, tiebreak by ticker ascending (alphabetical).
    #   Tiebreaker rationale: the spec does not specify one; ticker-ascending is deterministic,
    #   requires no new data, and produces a stable/reproducible order run-to-run for equal scores.
    sort_key = lambda c: (-c.score, c.ticker)
    green.sort(key=sort_key)
    yellow.sort(key=sort_key)
    red.sort(key=sort_key)

    # Step 3 — fill with yellow/green first, up to 10, green always before yellow.
    green_yellow = green + yellow            # green block entirely precedes yellow block
    primary = green_yellow[:10]              # take at most 10; if green_yellow has <=10, primary == green_yellow unchanged

    # Step 4 — backfill with red only if primary has fewer than 10.
    remaining_slots = 10 - len(primary)
    if remaining_slots > 0 and len(red) > 0:
        backfill = red[:remaining_slots]     # take only as many as needed, sorted red list already
    else:
        backfill = []

    # Step 5 — mark low_confidence.
    # ALL of primary (every green and every yellow idea) -> low_confidence = False, backfill_reason = None.
    # ALL of backfill (every red idea actually included) -> low_confidence = True, backfill_reason = "red_tier_backfill".
    # No other candidate (any red idea NOT selected into backfill) appears in output at all.

    final_order = primary + backfill         # green...yellow...red(backfilled) — order is preserved from steps 2-4, never re-sorted after this point

    # Step 6 — assign final rank 1..N.
    result = []
    for i, c in enumerate(final_order):
        idea = build_idea(c, low_confidence = (c in backfill), backfill_reason = ("red_tier_backfill" if c in backfill else None), rank = i + 1)
        result.append(idea)

    return result
```

### Edge cases (explicit, each must be covered by a test in §7)

| Scenario | Expected behavior |
|---|---|
| 0 total candidates | `eligible` is empty after Step 0 → return `[]`. No crash. |
| All candidates lack citations | `eligible` is empty after Step 0 → return `[]`, even if tiers/scores would otherwise qualify. |
| Exactly 10 yellow/green, any number of red | `primary` has exactly 10, `remaining_slots == 0` → `backfill = []` unconditionally, even if red candidates exist and even if their score is high. Zero red leakage. |
| More than 10 yellow/green (e.g. 14) | `green_yellow[:10]` truncates; candidates ranked 11-14 by the sort in Step 2 are dropped entirely (not carried to a "page 2" — v1 has no pagination). Truncation respects the tier-then-score-then-ticker sort, so if green alone exceeds 10, no yellow ideas are included at all that run. |
| Fewer than 10 yellow/green, red available | `backfill` takes exactly `remaining_slots` best-scoring eligible red ideas (ticker-ascending tiebreak), appended after all yellow/green, each flagged `low_confidence=True`. |
| Zero yellow/green, red available | `primary = []`, `remaining_slots = 10`, `backfill` = up to 10 best red ideas, all flagged `low_confidence=True`. Result is red-only, fully labeled. |
| Fewer than 10 total even after full red backfill (e.g. 3 green + 2 red, no more red) | `result` has 5 ideas. Never pad with placeholder/fake rows to reach 10 — a short list is the correct, honest output. |
| Tie in score within same tier | Resolved by ticker ascending (alphabetical, case-insensitive compare recommended — document exact `str.upper()` or `str.lower()` comparison used in the implementation so it's testable). |
| A red candidate with no citation, in a run that is short on yellow/green | Dropped at Step 0 regardless — never reaches the backfill pool, even though it "would have" been needed to reach 10. Output may legitimately end up with fewer than 10 as a result. |

---

## 4. Schema confirmation / additions

**Confirmed reuse (no change needed):** Per `plan-detailed/slice-0.md` §2, the `ideas` table already has:
- `tier TEXT NOT NULL` — 'green'/'yellow'/'red'.
- `score INTEGER` — will be non-null by the time Slice 9 runs (Slice 5 populates it).
- `low_confidence INTEGER NOT NULL DEFAULT 0` — bool (0/1). Slice 9 is the first slice to ever set this to `1`; every prior slice's fake/stub data left it `0`. This column's semantics (per FR7) are: **1 if and only if this idea is a red-tier candidate that was included specifically to backfill the list below 10 items.** It must never be `1` for a yellow or green idea.
- `rank INTEGER NOT NULL DEFAULT 1` — Slice 9 is the first slice to assign real, meaningful multi-row rank values (1..N) instead of the trivial single-row `1` from Slice 0.
- `citation_url TEXT NOT NULL` — already enforces at the schema level that a persisted idea has *a* URL string; Slice 9's Step 0 check must run in application code before persistence, since the DB constraint alone can't express "non-empty"/"well-formed" citation content.

**Recommended addition:** `backfill_reason TEXT` (nullable), added via `db.py`'s existing additive-migration mechanism (the `_ADDED_COLUMNS`-style pattern referenced in slice-0.md §2, or a plain `ALTER TABLE ideas ADD COLUMN backfill_reason TEXT` guarded by a `try/except` or a `PRAGMA table_info` check, consistent with whatever additive-migration approach Slice 0 actually established — confirm the exact mechanism in `app/db.py` before writing this migration and reuse it, don't invent a second one).
- Value is the literal string `"red_tier_backfill"` when `low_confidence=True` for the current v1 scope; `NULL` otherwise.
- Rationale: `low_confidence` alone tells the UI/analyst *that* an idea is lower confidence, but not *why* — this field gives a stable, machine-readable audit trail distinguishing "flagged low-confidence because backfilled" (Slice 9) from any possible future low-confidence reason (e.g., a borderline negative-filter pass in a later iteration), and it directly supports the Slice 6 exclusion-reason audit-trail convention (`excluded`/`exclusion_reason` on filtered-out candidates) by giving backfilled-but-included ideas an equivalent provenance field. This is optional/nice-to-have, not a hard FR7 requirement — implement it, but do not block slice completion on it if time-constrained; `low_confidence` alone is sufficient to satisfy FR7's letter.

**No change to `FinalCandidate`'s persistence boundary** — `assemble()` operates on in-memory `FinalCandidate`/`Idea` objects; the orchestrator (not `assemble()`) is responsible for writing the returned `Idea` list's rows to SQLite via the existing `db.py` insert path used since Slice 0.

---

## 5. Orchestrator wiring — exact placement

In `app/run_orchestrator.py`, the pipeline step order after Slice 8 lands is:

```
...
step 7: compilation (Slice 8) — Sonnet call over all surviving post-scoring, post-filtering candidates
        -> produces the FinalCandidate list (score/tier immutable from Slice 5/6, rationale/commentary from Slice 8)

step 8 (NEW, this slice): final_ideas = assembly.assemble(final_candidates)
        -> this is the ONLY place in the orchestrator that calls assemble()
        -> no other step may reorder, re-filter, or re-flag ideas after this point

step 9: persistence — write `final_ideas` (already capped at <=10, ordered, labeled, ranked) to the `ideas` table,
        exactly as returned — no further transformation. Update the `runs` row to `status='complete'`.
```

- **Before:** persistence (step 9) must never run against the raw `final_candidates` list from Slice 8 — only against `assemble()`'s output. If the orchestrator currently persists ideas as they're produced by Slice 8 (incremental persistence), this slice must change that so persistence happens once, after assembly, as a single batch write of the final list.
- **After:** Slice 8 compilation (step 7) must have already run to completion for all surviving candidates before `assemble()` is called — assembly never calls back into Haiku/Sonnet and never needs to.
- **Failure handling:** `assemble()` is pure and cannot itself fail against well-formed input (no I/O, no exceptions expected in normal operation). If `final_candidates` is malformed (e.g., a `FinalCandidate` missing a `tier` or `score` entirely — a Slice 5/8 contract violation, not an assembly concern), that is a programming-error-level failure the orchestrator should let surface as a run `error` status (fail loudly, don't silently coerce), consistent with how Slice 7's per-stock skip-and-continue applies only to upstream LLM calls, not to a broken data contract at the assembly boundary.

---

## 6. UI requirement — distinct low-confidence visual treatment

Per FR7/§9, a backfilled red idea must be **unmistakably distinct**, not merely a different badge color (colorblind users, quick scanning, and screenshot/print contexts can all lose a pure-color signal). Concrete spec for the coder:

1. **Separate section, not an interleaved card list.** The results template renders two sections when any backfilled idea is present:
   - `## Ideas` (or similar) — all `low_confidence == False` ideas (green/yellow), in rank order.
   - `## Lower-confidence ideas (backfilled)` — all `low_confidence == True` ideas, in rank order, rendered **below** the first section, visually separated by a horizontal rule or distinct background panel.
   - If there are zero low-confidence ideas in a run's result, the second section is omitted entirely (no empty "Lower-confidence ideas" header).
2. **Explicit text label on every low-confidence card**, in addition to the section header — exact copy (reuse verbatim, do not paraphrase at implementation time):
   `"⚠ Low confidence — backfilled (red-tier, fewer than 10 higher-confidence ideas were found this run)"`
   rendered as visible text inside the card (not a tooltip, not alt-text only, not solely conveyed via CSS color).
3. **Still show the tier badge** (red) on these cards too — the low-confidence label is additive, not a replacement for the existing tier badge from Slice 5.
4. **CSS treatment distinct from a plain color swap:** give the low-confidence section/card a visibly different layout treatment beyond color — e.g., a dashed/double border, a warning icon (⚠, already in the text label — can also be used as a standalone glyph via CSS `::before` for extra visual weight), or a muted/reduced-emphasis background panel for the whole section (distinguishable even in grayscale printing or for a colorblind viewer). Do not rely on red-vs-green/yellow hue alone anywhere in this treatment.
5. **Rank numbers remain continuous and real** across both sections (e.g., if ideas 1-7 are green/yellow and 8-10 are backfilled red, the backfilled cards show rank "8", "9", "10" — not re-numbered "1", "2", "3" within their own section) — this reinforces that they are lower-priority continuations of one list, not a separate parallel ranking.

This is concrete enough that a coder should not need to invent the wording, placement, or whether color alone would suffice — it explicitly would not.

---

## 7. Step-by-step implementation sequence

1. Confirm the exact `FinalCandidate` shape actually produced by Slice 8's implementation (read the real Slice 8 code once it exists, don't assume this plan's §2 shape is byte-exact — adapt the orchestrator glue, not `assemble()`'s internal logic, if there's drift).
2. Write `app/models.py` additions (or confirm existing) for `FinalCandidate`, `Citation`, `Idea`.
3. Write `app/assembly.py`'s `assemble()` per the algorithm in §3. No DB, no LLM, no datetime/wall-clock calls.
4. Write `tests/test_assembly.py` (§8) against `assemble()` directly — these must all pass before touching the orchestrator.
5. Add the `backfill_reason` column via `db.py`'s existing additive-migration mechanism (confirm mechanism first, per §4).
6. Wire `assembly.assemble()` into `run_orchestrator.py` as step 8, per §5 — change persistence to a single batch write of the assembled list, remove any incremental per-candidate persistence if it currently exists.
7. Update the results template(s) for the two-section low-confidence rendering (§6) and the CSS additions.
8. Write/extend an integration test exercising a full orchestrator run (using Slice 4/7/8's fake sessions, not live LLM calls) that produces more candidates than can fit, confirming the persisted + rendered output obeys every FR7 rule end-to-end.
9. Run the full test suite (`pytest tests/ -v`); fix regressions.
10. Manual verification pass per §9 below.

---

## 8. Exact test files and test cases (table-driven)

**File:** `tests/test_assembly.py`
**Run command:** `pytest tests/test_assembly.py -v` (full suite: `pytest tests/ -v`)

Helper: a small `make_candidate(ticker, tier, score, has_citation=True)` factory in the test file to keep cases terse.

### Table-driven cases (one parametrized test function, or one test per row — either is fine, but every row below must exist as a distinct assertion):

1. **`test_ten_plus_yellow_green_zero_red_leak`** — 12 green/yellow candidates (mixed tiers, varying scores) + 3 high-scoring red candidates, all with citations. Assert: `len(result) == 10`, zero rows have `tier == "red"`, all `low_confidence == False`, and the 2 lowest-scoring green/yellow candidates among the 12 are absent (truncation happened via the sort, not arbitrarily).
2. **`test_truncation_tiebreak_is_ticker_ascending`** — 11 green candidates where two share the same score (e.g., both score 85, tickers `"ZEE"` and `"ABC"`). Assert the one with the alphabetically earlier ticker (`"ABC"`) is included ahead of (or instead of, depending on where the cut falls) the later one — construct the fixture so the tie sits exactly at the 10th/11th boundary, so the test fails if ticker-ascending isn't applied.
3. **`test_exactly_ten_yellow_green_no_backfill_attempted`** — exactly 10 yellow/green candidates + 2 red candidates with citations and high scores. Assert `len(result) == 10`, zero red ideas present, even though red candidates with valid citations existed and had decent scores.
4. **`test_fewer_than_ten_yellow_green_backfills_with_red`** — 6 yellow/green + 5 red (all cited). Assert `len(result) == 10`, first 6 rows are the yellow/green ones (in order, green before yellow), last 4 rows are the 4 best-scoring red candidates, all 4 have `low_confidence == True` and `backfill_reason == "red_tier_backfill"`, and the 6 yellow/green rows all have `low_confidence == False`.
5. **`test_zero_yellow_green_all_red_all_flagged`** — 0 yellow/green + 7 red (all cited). Assert `len(result) == 7`, every row has `tier == "red"` and `low_confidence == True`.
6. **`test_citationless_candidates_dropped_regardless_of_score_or_tier`** — a mix including: one green candidate with score 95 but `citations=[]`, one green candidate with score 90 and a valid citation, one red candidate with a citation whose `url` is an empty string. Assert the score-95 green candidate is absent from `result` despite its score/tier, the score-90 green candidate is present, and the empty-url red candidate is absent.
7. **`test_zero_total_candidates_returns_empty_list_no_crash`** — `assemble([])` returns `[]` without raising.
8. **`test_fewer_than_ten_total_even_after_backfill_never_padded`** — 3 green (cited) + 2 red (cited), no more available. Assert `len(result) == 5` exactly — not padded to 10, no fabricated rows, and no exception.
9. **`test_rank_assigned_1_to_n_in_final_order`** — any mixed fixture producing N<10 or N==10 results; assert `result[i].rank == i + 1` for all i, and that rank is strictly increasing in the returned order (green block's ranks all precede yellow block's ranks all precede red-backfill block's ranks).
10. **`test_order_always_green_before_yellow_before_red`** — a fixture with all three tiers present and fewer than 10 yellow/green (so backfill triggers); assert every green row's rank < every yellow row's rank < every red row's rank in the result.

**Integration test** (extend an existing orchestrator integration test file, e.g. `tests/test_run_orchestrator.py` if it exists from earlier slices, or add `tests/test_assembly_integration.py`):
- `test_full_run_assembly_end_to_end` — using Slice 4/7's `FakeHaikuSession` and Slice 8's `FakeCompilationSession` configured to produce 14 candidates (9 green/yellow, 5 red, one of the red ones missing a citation), run the orchestrator end-to-end and assert the **persisted** `ideas` rows for that run (queried back from SQLite) number exactly 10, obey the green>yellow>red order, show exactly 4 `low_confidence=True` rows (5 red minus the 1 dropped for no citation), and that `rank` values in the DB are 1..10 with no gaps or duplicates.

---

## 9. Manual demonstration procedure

1. **Review a real run's list for ordering/labeling:** trigger a real (or fake-session-backed, whichever is wired as default at this point in the build) run that produces more than 10 surviving candidates across at least two tiers. Open the results page and visually confirm: ideas appear green-block-then-yellow-block-then-red-block (if any red made it in), ranks are continuous 1..10, and no idea card is missing a citation link.
2. **Construct or wait for a <10-yellow/green scenario:** since real yellow/green supply depends on live market conditions and may not reliably be under 10, the most reliable approach is to **temporarily** run with `FakeHaikuSession`/`FakeCompilationSession` configured (via the existing test-fixture fakes, not a new one-off hack) to produce, e.g., 6 yellow/green + 4 red candidates, and trigger a run through the real orchestrator/UI path (not just the unit test) so the full stack — assembly, persistence, template rendering — is exercised visually. Confirm in the browser:
   - The "Lower-confidence ideas (backfilled)" section appears, below the main list, visually separated.
   - Each backfilled card shows the exact `"⚠ Low confidence — backfilled..."` text label, not just a red badge.
   - Ranks on the backfilled cards continue from the main list's last rank (not restarted at 1).
3. **Confirm the no-backfill-when-unnecessary case:** run again with >=10 yellow/green in the fake fixture and confirm the "Lower-confidence ideas" section does not render at all.
4. **Confirm citation-drop visually:** configure one fake candidate with no citation and a high score/green tier; confirm it never appears anywhere in the rendered output, and that the DB row count for that run matches "total candidates minus the dropped one," not blindly 10.

---

## 10. Acceptance criteria and verification evidence

- [ ] Given 10+ yellow/green candidates, zero red-tier ideas appear in output. **Evidence:** `test_ten_plus_yellow_green_zero_red_leak`, `test_exactly_ten_yellow_green_no_backfill_attempted` passing; manual step 3.
- [ ] Given fewer than 10 yellow/green candidates, red-tier ideas backfill up to 10 total (or fewer if the whole pool is smaller), ordered strictly after all yellow/green, each flagged `low_confidence=True` in **persisted** data (not just incidentally stylable). **Evidence:** `test_fewer_than_ten_yellow_green_backfills_with_red`, `test_zero_yellow_green_all_red_all_flagged`, `test_fewer_than_ten_total_even_after_backfill_never_padded`, and the integration test's DB-level assertion; manual step 2.
- [ ] A candidate missing a citation never appears in output, regardless of score/tier. **Evidence:** `test_citationless_candidates_dropped_regardless_of_score_or_tier`; integration test's "5 red minus 1 dropped" assertion; manual step 4.
- [ ] Final list order is always green-before-yellow-before-red; never more than 10 ideas regardless of upstream candidate count; never padded below the true available count. **Evidence:** `test_order_always_green_before_yellow_before_red`, `test_rank_assigned_1_to_n_in_final_order`, `test_zero_total_candidates_returns_empty_list_no_crash`, `test_fewer_than_ten_total_even_after_backfill_never_padded`.
- [ ] Truncation of a same-tier group larger than its share of the top-10 uses a documented, deterministic tiebreaker (ticker ascending) rather than arbitrary/unstable ordering. **Evidence:** `test_truncation_tiebreak_is_ticker_ascending`.
- [ ] Low-confidence ideas are rendered with a distinct section header and explicit warning text, not merely a color difference. **Evidence:** manual step 2 (visual review against §6's exact spec); a template-level assertion test (optional but recommended) checking the literal warning string appears in rendered HTML for a backfilled idea and is absent when none exist.
- [ ] `backfill_reason` (if implemented) is set to `"red_tier_backfill"` exclusively on backfilled rows and `NULL` elsewhere. **Evidence:** integration test DB-row assertions; code review of `assemble()`.
- [ ] `assemble()` remains pure — no DB/LLM/network/datetime import. **Evidence:** `grep -n "^import\|^from" app/assembly.py` reviewed by hand; shows only stdlib/typing imports plus the local `models` module.
- [ ] `pytest tests/ -v` — all tests pass, including the new `test_assembly.py` file and the extended integration test, zero skips/xfails.

Slice 9 is complete only when every checkbox above is verified with the stated evidence, not merely claimed — this is explicitly flagged in `vertical-slice-plan.md` as the most spec-critical slice, so partial/claimed-but-unverified completion is not acceptable here.
