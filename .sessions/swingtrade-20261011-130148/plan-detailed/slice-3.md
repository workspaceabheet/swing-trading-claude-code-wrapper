# Slice 3 — Detailed Technical Plan: Quick-Sweep Change Detection (FR2/FR12)

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 3 only
**Inputs (locked, not reopened):**
- `tech-spec.md` FR2, FR12, §5 ("quick-sweep" architecture step), §9 (acceptance criteria), §10 (test expectations), §11 (risk: "quick-sweep materiality threshold... needs a concrete definition before Stage 3" — **this plan resolves that**)
- `initial-plan.md` (project layout Decision B: `app/quick_sweep.py` already named there)
- `vertical-slice-plan.md` Slice 3 section (lines 177-214) — ordering (quick-sweep right after sourcing, before any LLM stage) is **locked, not reopened**
- `plan-detailed/slice-0.md` — established `runs`/`ideas` schema, `run_orchestrator.py` stub shape, polling-based status API, conventions (SQLite via `db.py`/`db_session()`, FastAPI app in `app/`, lighter-than-sibling structure)

**Integration dependency to double-check once it exists:** Slices 1-2 are being planned in parallel and will define the exact persistence shape of "the aggregated sweep dataset" (what this plan calls `sweep_items` — the per-run collection of `NormalizedItem`-shaped records from all source adapters). This plan is written against that dataset **abstractly** — by its row shape, not its table/column names — specifically so it survives whatever Slice 1/2 actually names things. **Action item before/at Slice 3 implementation time:** confirm against the landed `plan-detailed/slice-1.md`/`slice-2.md` (or the actual code) that:
1. There is a queryable way to fetch "all sweep items for run N" as a list of records exposing at minimum `source`, `ticker` (nullable), `headline`, `published_at`.
2. Each run's sweep items are retrievable by `run_id` after the run completes (i.e., not only held in memory during the run).
If either assumption is wrong, `quick_sweep.py`'s `load_prior_sweep_snapshot()` function (ยง3 below) is the only place that needs to change — the hash/compare logic and orchestrator wiring do not depend on the storage mechanics.

---

## 1. Files to create

| Path | Responsibility |
|---|---|
| `app/quick_sweep.py` | Core change-detection module: normalization, hashing, and the `compare_to_prior(current_items, prior_hash) -> QuickSweepResult` function. Pure logic, no DB/network I/O beyond the one documented read of the prior run's stored hash. |
| `app/run_orchestrator.py` (modify) | Insert the quick-sweep step between sourcing (step 1, from Slices 1-2) and the LLM/deep-dive stage (still the Slice-0 stub at this point). On "unchanged," short-circuit: mark the run, copy forward the prior run's ideas, stop. |
| `app/db.py` (modify) | Add `quick_sweep_hash` column to `runs` (storage for this run's computed hash, so the *next* run can diff against it) and extend the `quick_sweep_skipped` semantics already present from Slice 0's schema (confirmed reuse — see §3). Add a helper to fetch "the immediately prior completed run's hash and idea set" by `id < current_run_id ORDER BY id DESC LIMIT 1` (excluding runs whose own status is `error`, as there is nothing trustworthy to compare against or copy forward from an errored run — fall through to that run's predecessor instead; see §3 for exact query). |
| `app/routers/run.py` (modify) | `GET /api/run/last` (and `/api/run/{id}` once Slice 10 adds it) response gains `quick_sweep_skipped` (already present as a placeholder bool since Slice 0) and a new `quick_sweep_message` string field for UI display. |
| `app/templates/index.html` (modify) | Render the "no material change" message distinctly from a normal completed run when `quick_sweep_skipped` is true. |
| `tests/test_quick_sweep.py` | Unit tests for the hash/normalization/compare logic itself (materiality rule boundary tests). |
| `tests/test_run_orchestrator_quick_sweep.py` | Integration tests for orchestrator wiring: identical-snapshot skip path (stub LLM stage never invoked) and materially-different proceed path (stub LLM stage invoked). |

No new top-level module beyond `quick_sweep.py` is needed — this slice is deliberately small per the vertical-slice plan's own framing ("S1/S2 and S5/S6 are each small"; S3 is comparably small).

---

## 2. The exact materiality / hash rule (decided — not left open)

The spec (FR2) explicitly delegates the exact rule to Workflow 2. Pure byte-equality hashing of raw fetched records is rejected as too brittle: RSS feeds frequently re-serve the same story with a changed tracking-parameter URL, a re-wrapped snippet sentence, or a republish timestamp a few seconds later than the original `published_at`, none of which represent new information worth paying for a deep-dive over. A rule that reacts to that noise would defeat FR12's entire purpose (cheap re-runs). Conversely, a rule that's too fuzzy (e.g., ignoring date entirely) could mask a genuinely new headline about the same ticker.

**Decided rule: a stable hash over a normalized, deduplicated, sorted set of identity tuples, each derived from one sweep item as follows:**

For each `NormalizedItem` in the current run's aggregated sweep dataset, compute an identity tuple:

```
(source, identity_key, published_date)
```

Where:
- `source` — the adapter name string exactly as the item carries it (e.g. `"moneycontrol_rss"`, `"nse_bhavcopy"`, `"screener_in"`, `"trading_economics"`), used as-is, no normalization needed (it's an internal enum-like string, not user/source-controlled free text).
- `identity_key` — **normalized headline** if `item.ticker` is `None`, else the **ticker symbol uppercased**. Rationale: once an item is ticker-attributable (Bhavcopy rows, Screener.in rows, and any RSS item the adapter could map to a symbol), the ticker is the stable identity — the exact headline/row wording around it is not informative for "did the universe of relevant facts change." For items with no ticker (most raw RSS news), the headline itself is the only identity signal, so it must be normalized to avoid false positives from trivial text variation:
  - Lowercase.
  - Collapse all whitespace runs to a single space, strip leading/trailing whitespace.
  - Strip all punctuation characters (regex `[^\w\s]` removed).
  - No stemming/fuzzy matching (e.g., no Levenshtein distance) — exact match on the normalized string only. This keeps the rule decidable and testable at an exact boundary, per the task's instruction to be decisive rather than impressionistic.
- `published_date` — the item's `published_at` **truncated to a calendar date** (`YYYY-MM-DD`, in the source's reported timezone or UTC if unspecified — adapters are responsible for supplying a timezone-aware or UTC-normalized `published_at`, consistent with Slice 1/2's `NormalizedItem` contract), **not** the full timestamp. Rationale: sub-day republish-time jitter (a feed re-serving the same story a few minutes/hours later same-day) is explicitly treated as immaterial; a genuinely new day's data (tomorrow's Bhavcopy row, a next-day follow-up story) is always material. This is the single fuzziness concession in the rule, and it is bounded and explicit (day-level granularity, not "ignore date" or "ignore if within N hours").

Explicitly **excluded** from the identity tuple (and therefore from materiality): `url` (varies with tracking params/redirects), `snippet` (wording varies run-to-run for the same underlying fact), and any source-specific extension fields from Slice 2 (e.g., Bhavcopy's exact OHLC/volume numbers) — **this is a deliberate scope decision**: FR2 is about *new information entering the picture* (a new headline, a new ticker-dated event), not about *existing tickers' numbers moving slightly*. A stock's closing price changing from yesterday is not itself new news requiring a fresh deep-dive under this rule; a new headline, a new ticker appearing in the sweep, or an existing ticker's items disappearing, is. (If real-run experience later shows this is too coarse — e.g., the user wants a large single-day price move to itself count as material — that is a tunable follow-up, flagged here but not implemented in this slice, since the spec's draft framing in §6/§11 already anticipates post-build tuning.)

**Hash computation:**
1. Build the set of identity tuples from all items in the current run's aggregated sweep dataset (across all sources combined — one shared set, not per-source sets, so that an item moving from "seen by adapter X" to "also seen by adapter Y" doesn't register as a spurious change if the tuple is otherwise identical; in practice duplicates across sources collapse into one set member, which is intentional).
2. Sort the tuples deterministically (Python's default tuple ordering — lexicographic over `(source, identity_key, published_date)` strings — is sufficient and deterministic across runs/processes).
3. Serialize the sorted list to a canonical string: `"|".join(f"{s}\x1f{k}\x1f{d.isoformat()}" for s, k, d in sorted_tuples)` joined with `"\x1e"` as the record separator (ASCII unit/record separators avoid collisions with any real headline content).
4. Compute `hashlib.sha256(canonical_string.encode("utf-8")).hexdigest()`.

**Decision rule: a change is material if and only if the current run's hash differs from the immediately prior (non-error) completed run's stored hash, at all.** No partial/fuzzy hash comparison, no "N items differ" threshold — once the identity-tuple normalization above has absorbed the known sources of noise, pure hash equality is the decision function. This keeps the rule decidable, unit-testable at exact boundaries, and matches the spec's own suggested default ("a change counts as material if the hash differs at all") rather than inventing an additional fuzzy layer on top of an already-normalized input.

**`QuickSweepResult` shape** (returned by `quick_sweep.py`):
```python
@dataclass
class QuickSweepResult:
    material_change: bool
    current_hash: str
    prior_hash: str | None   # None if there is no prior run to compare against
```

**First-ever run:** if there is no prior completed run at all (fresh install, or no prior non-error run exists), `prior_hash` is `None` and the result is always `material_change=True` (nothing to short-circuit against — proceed to the LLM stage/stub normally). This is a boundary case covered explicitly in tests (§7).

---

## 3. Schema — confirm reuse, define additions

**Confirmed reuse:** `runs.quick_sweep_skipped` already exists as an `INTEGER NOT NULL DEFAULT 0` placeholder column per Slice 0's schema (`plan-detailed/slice-0.md` §2). Slice 3 is the first slice to give it real (non-hardcoded-zero) values. No rename, no type change — reused as-is.

**New column needed:**

```sql
ALTER TABLE runs ADD COLUMN quick_sweep_hash TEXT;
```

- `quick_sweep_hash` — the current run's computed hash (§2, step 4), stored on **every** run (whether skipped or not), so the *next* run has something to diff against. `NULL` only for runs that errored before sourcing completed (no sweep dataset to hash).
- No separate "snapshot" blob column is needed — the hash alone is sufficient to decide materiality, and the actual prior sweep *items* (for display/debugging) are already retained via the aggregated sweep dataset from Slices 1-2 (keyed by `run_id`), so there's no need to duplicate that data onto the `runs` row. This keeps Slice 3's schema footprint to one column, consistent with the vertical-slice plan's own schema sketch (`runs` table gains `quick_sweep_skipped: bool`) plus the one hash column it didn't enumerate but is required to make the skip decision stateful across runs.

**Migration note:** follow `app/db.py`'s existing additive-column pattern (per Slice 0's `db.py` notes referencing the sibling's `_ADDED_COLUMNS` mechanism) — add `quick_sweep_hash` via the same `ALTER TABLE ... ADD COLUMN IF NOT EXISTS`-equivalent guard used for other additive changes, not a destructive schema rewrite.

**What "copy forward the prior run's ideas" means concretely:** when a run is skipped, do **not** duplicate `ideas` rows into the new run. Instead:
- The new `runs` row is marked `status='complete'`, `quick_sweep_skipped=1`, `quick_sweep_hash=<the identical hash>`.
- `GET /api/run/last` for a skipped run returns the **prior** run's `ideas` by looking them up via `source_run_id` (new nullable column on `runs`: `source_run_id INTEGER REFERENCES runs(id)`, set only when skipped, pointing at the run whose ideas are being presented). This avoids data duplication and keeps "which run actually produced this idea" traceable (important once Slice 10's history view exists — a skipped run's detail page should visibly say "ideas shown are from run #N").

```sql
ALTER TABLE runs ADD COLUMN source_run_id INTEGER REFERENCES runs(id);
```

So the full Slice 3 schema delta is two additive columns: `quick_sweep_hash TEXT`, `source_run_id INTEGER REFERENCES runs(id)`.

**Query for "the immediately prior run to compare against":**
```sql
SELECT id, quick_sweep_hash, status,
       COALESCE(source_run_id, id) AS ideas_owner_run_id
FROM runs
WHERE id < :current_run_id AND status != 'error'
ORDER BY id DESC
LIMIT 1;
```
If that row's own `status` was itself `'complete'` with `quick_sweep_skipped=1`, its `quick_sweep_hash` is still the correct thing to diff against (hash is always stored, skip or not — see above), and `ideas_owner_run_id` correctly chains back through any run of consecutive skips to the original run that actually produced the ideas.

---

## 4. Orchestrator wiring — exact sequencing

Per `tech-spec.md` §5's 9-step orchestrator sequence and the vertical-slice plan's locked ordering, `run_orchestrator.py`'s `execute_run()` gains one new step inserted between sourcing and the (still-stubbed, pending Slice 4+) LLM stage:

```
Step 1 (Slices 1-2): source all adapters -> aggregated sweep dataset, persisted for this run_id
Step 2 (THIS SLICE):  quick-sweep change detection
    2a. Compute current_hash from this run's aggregated sweep dataset (app.quick_sweep.compute_hash)
    2b. Look up the immediately prior non-error run's stored hash (app.db helper, query above)
    2c. result = app.quick_sweep.compare_to_prior(current_hash, prior_hash)
    2d. Persist quick_sweep_hash = result.current_hash on this run row immediately (regardless of outcome)
    IF result.material_change is False:
        2e. Set source_run_id = ideas_owner_run_id (from the lookup query)
        2f. Set status = 'complete', finished_at = now(), quick_sweep_skipped = 1
        2g. RETURN — do not proceed to step 3 (LLM stage) at all. No LLM-stage function/stub is called.
    ELSE:
        2h. Set quick_sweep_skipped = 0, proceed to step 3 as normal.
Step 3+ (Slice 0 stub today; real stages in Slices 4+): LLM sweep -> deep-dive -> scoring -> filtering -> compilation -> assembly -> persistence -> disclaimer
```

**Critical invariant for testability:** the LLM/deep-dive stage entry point (currently the Slice-0 stub function, later the real `agent/sweep.py` call) must be a single, named, mockable function/method (e.g., `self._run_llm_stages(...)` or equivalent) that the orchestrator calls **only** in the `ELSE` branch above. This lets tests assert a call-count of exactly 0 (skip path) or exactly 1 (proceed path) on a mock/stub substituted for that function — this is what makes the acceptance criterion "the skip decision is made before any LLM-stage code path executes" mechanically verifiable rather than just asserted by code reading.

**Error handling:** if sourcing (step 1) itself fails entirely (no sweep dataset produced), quick-sweep cannot run meaningfully — in that case the run is already marked `status='error'` by step 1's own failure handling (per Slices 1-2's adapter-failure resilience pattern; a single adapter failing does not abort the run, but if *all* adapters fail there is no sweep dataset to hash) and step 2 is skipped entirely, `quick_sweep_hash` stays `NULL` for that run. The "immediately prior non-error run" lookup query already excludes such runs from being used as a comparison baseline, so this failure mode cannot poison a future diff.

---

## 5. UI messaging requirements

**Run detail / latest-run view, when `quick_sweep_skipped = true`:**
- A distinct status banner/section (not styled identically to a normal completed run), with exact text:
  > "No material change detected since the last run — showing results from run #{source_run_id} (completed {prior_run_finished_at})."
- The idea cards displayed below this banner are the prior run's ideas (fetched via `source_run_id`), rendered with the normal card template — they are not fake/placeholder cards, they are the real prior output, just not freshly computed.
- The disclaimer (FR9) still renders unconditionally on this view, exactly as on a normal completed run — skip status does not exempt the disclaimer.

**Run detail / latest-run view, when `quick_sweep_skipped = false` (normal path):**
- No skip banner; normal "run completed" presentation as established in Slice 0.

**API contract addition** (`GET /api/run/last`, extending Slice 0's response shape):
```json
{
  "has_run": true,
  "run_id": 9,
  "status": "complete",
  "quick_sweep_skipped": true,
  "source_run_id": 8,
  "quick_sweep_message": "No material change detected since the last run — showing results from run #8 (completed 2026-10-12T09:05:00+00:00).",
  "ideas": [ /* run #8's ideas, unchanged */ ],
  "disclaimer": "For personal informational use only. ..."
}
```
`quick_sweep_message` is pre-built server-side (not constructed client-side from raw fields) so the exact wording is controlled in one place (`run_orchestrator.py` or a small formatting helper in `quick_sweep.py`) and is trivially unit-testable as a string.

---

## 6. Step-by-step implementation sequence

1. **`app/db.py`** — add the two additive columns (`quick_sweep_hash`, `source_run_id`) and the "immediately prior non-error run" lookup helper function (e.g., `get_prior_comparable_run(conn, current_run_id) -> PriorRunInfo | None`).
2. **`app/quick_sweep.py`** — implement:
   - `_normalize_identity_key(item: NormalizedItem) -> str` (ticker-or-normalized-headline logic from §2).
   - `_build_identity_tuples(items: list[NormalizedItem]) -> set[tuple[str, str, date]]`.
   - `compute_hash(items: list[NormalizedItem]) -> str` (sort + canonicalize + sha256, per §2).
   - `compare_to_prior(current_hash: str, prior_hash: str | None) -> QuickSweepResult`.
   - `format_skip_message(source_run_id: int, prior_finished_at: str) -> str` (exact UI string from §5).
3. **`tests/test_quick_sweep.py`** — write and pass the unit tests in §7 before touching the orchestrator (pure-function module, no DB/app dependency, fastest feedback loop).
4. **`app/run_orchestrator.py`** — insert step 2 exactly as specified in §4, refactor the existing LLM-stage stub call behind one named, mockable method if it isn't already (check Slice 0's actual stub structure first — it likely already is, since it's a single orchestrator method).
5. **`tests/test_run_orchestrator_quick_sweep.py`** — write and pass the integration tests in §7.
6. **`app/routers/run.py`** — extend the `GET /api/run/last` response with `quick_sweep_skipped`, `source_run_id`, `quick_sweep_message` fields.
7. **`app/templates/index.html`** — add the skip-banner conditional rendering block from §5.
8. **Manual verification** — run the two-runs-in-a-row demo (§8) by hand.
9. **Full regression** — `pytest tests/ -v` (whole suite, not just this slice's new files) to confirm no Slice 0-2 tests broke.

---

## 7. Exact test files and cases

Run with: `pytest tests/test_quick_sweep.py tests/test_run_orchestrator_quick_sweep.py -v`
(Full suite: `pytest tests/ -v`)

### `tests/test_quick_sweep.py` (unit, pure logic, no DB/app)

- `test_identical_item_sets_produce_identical_hash` — two independently-constructed lists of `NormalizedItem`s with the same (source, ticker, headline, published_at) content but different list order and different `snippet`/`url` values produce the same `compute_hash()` output. (Tests set-based + excluded-fields behavior.)
- `test_new_headline_changes_hash` — baseline item list vs. the same list plus one additional item (new source/ticker/headline/date combination) produce **different** hashes.
- `test_removed_item_changes_hash` — baseline item list vs. the same list with one item removed produce **different** hashes (materiality is symmetric — disappearance counts too).
- `test_snippet_only_difference_does_not_change_hash` — same identity tuples, different `snippet` text on one item → identical hash (boundary test proving snippet exclusion per §2).
- `test_url_only_difference_does_not_change_hash` — same identity tuples, different `url` (e.g., added tracking param) on one item → identical hash.
- `test_published_time_same_day_does_not_change_hash` — same item, `published_at` differing by a few hours but same calendar date → identical hash (boundary test for date-truncation rule).
- `test_published_date_change_changes_hash` — same item, `published_at` moved to the next calendar day → different hash (boundary test proving date-level granularity is not "ignore date entirely").
- `test_headline_case_and_punctuation_normalization` — two headline-only (no-ticker) items differing only by case and punctuation (`"RBI Cuts Rates!"` vs `"rbi cuts rates"`) produce the same identity tuple → identical hash.
- `test_headline_vs_ticker_identity_precedence` — an item with a `ticker` set uses the ticker as identity even if its headline text changes entirely between two runs → identical hash (proves ticker-identity precedence over headline text once a ticker is known).
- `test_compare_to_prior_identical_hashes_not_material` — `compare_to_prior(h, h)` returns `material_change=False`.
- `test_compare_to_prior_different_hashes_material` — `compare_to_prior(h1, h2)` with `h1 != h2` returns `material_change=True`.
- `test_compare_to_prior_no_prior_run_is_material` — `compare_to_prior(h, None)` returns `material_change=True` (first-ever-run boundary case per §2).
- `test_format_skip_message_exact_text` — asserts the exact rendered message string from `format_skip_message(...)` matches the §5 template byte-for-byte (given fixed inputs).

### `tests/test_run_orchestrator_quick_sweep.py` (integration, uses a mocked/stubbed LLM-stage entry point)

- `test_identical_snapshot_second_run_skips_llm_stage` — seed run #1 with a fixture sweep dataset and let it complete normally (LLM-stage stub mocked, called once, returns a canned idea so run #1 has ideas to "copy forward"); then run #2 with an **identical** fixture sweep dataset. Assert: run #2's `quick_sweep_skipped == True`, `source_run_id == 1`, and — the key call-count assertion — **the LLM-stage stub's mock was called exactly 0 additional times during run #2** (i.e., total call count across both runs stays at 1, not 2). This directly implements the task's required "call-count assertion on a stub/mock" for the identical-snapshot case.
- `test_materially_different_snapshot_second_run_proceeds` — same setup, but run #2's fixture sweep dataset includes one new headline/ticker not present in run #1's. Assert: run #2's `quick_sweep_skipped == False`, `source_run_id IS NULL`, and the LLM-stage stub mock **was** called during run #2 (total call count across both runs is 2). This implements the "materially-different snapshot" required test.
- `test_first_ever_run_always_proceeds` — a single run with no prior run in the DB at all: assert it proceeds (LLM-stage stub called), `quick_sweep_skipped == False`, `source_run_id IS NULL`.
- `test_skip_persists_identical_hash` — after the skip in the first test above, assert run #2's stored `quick_sweep_hash` column equals run #1's stored `quick_sweep_hash` exactly (proves the hash is persisted even on the skip path, so a third identical run can also skip).
- `test_errored_prior_run_excluded_from_comparison` — seed run #1 with status `'error'` (simulating an all-adapters-failed sourcing run) and `quick_sweep_hash IS NULL`; seed run #0 before it with a real completed hash; run #2 arrives with a sweep dataset identical to run #0's. Assert run #2 correctly skips and sets `source_run_id` to run #0 (not run #1), proving the "prior non-error run" lookup query correctly skips over the errored run.
- `test_skip_response_includes_prior_run_ideas` — after a skip, `GET /api/run/last` (via the existing `client`/`TestClient` fixture from Slice 0's `conftest.py`) returns the prior run's exact ideas and the `quick_sweep_message` field non-empty and containing the prior run's id.

---

## 8. Manual demonstration procedure

1. Start the app (`uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`), ensure a clean/fresh local DB (or note the existing run count).
2. Click "Run now." Wait for completion. Note the run id and that `quick_sweep_skipped` is false (first run, nothing to compare against — per §2's boundary rule).
3. **Immediately** click "Run now" again (same day, same underlying external data — Moneycontrol/Bhavcopy/Screener.in/Trading Economics content should not have changed materially in the few minutes between clicks). Observe: the run completes very fast (no LLM-stage wait, since in Slice 3 the "LLM stage" is still the Slice 0/4 stub anyway — but the orchestrator-level skip is what's being demonstrated: compare elapsed time/behavior against step 2, and inspect the run detail page for the "No material change detected..." banner referencing the first run's id).
4. Inspect the SQLite `runs` table directly (`sqlite3 ~/.swingtrade/app.db "SELECT id, status, quick_sweep_skipped, source_run_id, quick_sweep_hash FROM runs ORDER BY id;"`) and confirm run #2's `quick_sweep_hash` exactly equals run #1's, `quick_sweep_skipped=1`, `source_run_id=1`.
5. To demonstrate the "materially different" path without waiting for real external sources to change: temporarily point one adapter at a modified fixture (or, simplest, use the test suite's fixture-injection approach interactively via a short Python REPL session calling `quick_sweep.compute_hash` on two fixture lists — one baseline, one with an added headline — and show the hashes differ), OR wait for genuinely new data (next NSE trading day's Bhavcopy will almost certainly add at least one new ticker/date combination). Trigger a third run under those conditions and confirm: no skip banner, `quick_sweep_skipped=0`, a new `quick_sweep_hash` stored, and the LLM stub invoked (observable via the existing Slice 0-era card update or application logs).

---

## 9. Acceptance criteria and verification evidence

- [ ] A second run shortly after a first run, with materially-unchanged underlying sweep data, is flagged `quick_sweep_skipped=true`, references the prior run via `source_run_id`, and the UI visibly reports "prior output still current" with the exact message format from §5. **Evidence:** `test_identical_snapshot_second_run_skips_llm_stage` + `test_skip_response_includes_prior_run_ideas` passing, plus manual step 3-4.
- [ ] A run where the underlying sweep data has materially changed proceeds past the quick-sweep check and invokes the LLM-stage entry point. **Evidence:** `test_materially_different_snapshot_second_run_proceeds` passing, plus manual step 5.
- [ ] The skip decision is made and enforced before any LLM-stage code executes — provable by a call-count assertion, not just code inspection. **Evidence:** the mock call-count assertions inside `test_identical_snapshot_second_run_skips_llm_stage` (0 additional calls) and `test_materially_different_snapshot_second_run_proceeds` (1 additional call).
- [ ] The materiality rule is exact and decidable, with explicit, tested boundaries (date-truncation, snippet/URL exclusion, ticker-vs-headline identity precedence, case/punctuation normalization). **Evidence:** all boundary tests in `tests/test_quick_sweep.py` (§7) passing.
- [ ] The first-ever run (no prior run to compare against) always proceeds rather than erroring or incorrectly skipping. **Evidence:** `test_first_ever_run_always_proceeds` and `test_compare_to_prior_no_prior_run_is_material` passing.
- [ ] An errored prior run is never used as a comparison baseline, and skip-chaining correctly resolves `source_run_id` back through consecutive skips to the run that actually produced the displayed ideas. **Evidence:** `test_errored_prior_run_excluded_from_comparison` passing; manual DB inspection (step 4) confirms correct `source_run_id` values.
- [ ] Schema changes are additive only (no destructive migration), reusing the existing `quick_sweep_skipped` placeholder column from Slice 0. **Evidence:** code review of the `ALTER TABLE` statements in `app/db.py`; `pytest tests/ -v` (full suite) passes, confirming Slice 0-2 behavior is unaffected.
- [ ] `pytest tests/ -v` — full suite passes, zero skips/xfails, including all new Slice 3 tests.

Slice 3 is complete only when every checkbox above is verified with the stated evidence, not merely claimed — consistent with Slice 0's own completion standard.
