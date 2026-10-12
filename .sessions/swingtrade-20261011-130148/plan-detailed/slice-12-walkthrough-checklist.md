# Slice 12 Manual Walkthrough Checklist

**Session:** swingtrade-20261011-130148
**Date:** 2026-10-12
**Slice:** 12 (Cross-Cutting Hardening + Full Regression Gate)

This checklist transcribes every line from tech-spec.md §9 (Acceptance Criteria, per major feature) into a tickable format for manual verification against the real running app. Each line should be verified by:
1. Running the app (`uvicorn app.main:app --host 127.0.0.1 --port 8000`)
2. Triggering runs via the UI
3. Inspecting the SQLite database and logged output
4. Manually observing behavior in the browser

---

## Acceptance Criteria Verification

### FR1 — Data Collection
- [ ] **Verify:** Trigger a real run via the web UI ("Run now" button).
- [ ] **Verify:** Wait for the run to complete.
- [ ] **Verify:** Open the SQLite database (`sqlite3 app/app.db`).
- [ ] **Verify:** Inspect the `sweep_items` table: `SELECT * FROM sweep_items LIMIT 1;`
- [ ] **Verify:** Confirm every row has only: `headline`, `source`, `published_at`, `url`, `snippet` — NO full article body text anywhere.
- [ ] **Verify:** Check for forbidden columns with: `PRAGMA table_info(sweep_items);` — verify no `body`, `full_text`, `content`, `article_body`, `raw_html` columns exist.
- [ ] **Verify:** Inspect the sources shown on the main page after run completes — all snippets are short (~1-2 sentences), not full articles.

### FR2/FR12 — Quick-Sweep Skip (Change Detection)
- [ ] **Verify:** Trigger a run and let it complete.
- [ ] **Verify:** Note the completion time and check the cost log (cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd).
- [ ] **Verify:** Immediately trigger a second run (no material news change).
- [ ] **Verify:** Wait for the second run to complete (should be faster, skipping LLM stages).
- [ ] **Verify:** Check the UI for a message like "No material change detected..." indicating the prior output still stands.
- [ ] **Verify:** Inspect the second run's cost log: sweep/deep-dive/compilation costs should be ~0 or unchanged (quick-sweep skipped LLM).
- [ ] **Verify:** Confirm the ideas shown for the second run are identical to the first run.

### FR3/FR4 — Sweep + Deep-Dive Separation
- [ ] **Verify:** Trigger a run and let it complete (ensure it proceeds past quick-sweep check, not skipped).
- [ ] **Verify:** Observe the UI updates as the run progresses: first a status "Sweep stage running...", then "Deep-dive stage running..." (if applicable).
- [ ] **Verify:** After completion, inspect the final ideas on the main page.
- [ ] **Verify:** For each idea shown, confirm a visible rationale text that includes written reasoning (e.g., "Catalyst: ...").
- [ ] **Verify:** For each idea, confirm at least one citation link is present (a "Source" link).
- [ ] **Verify:** Verify that no idea shows a "final tier" assigned by the LLM itself (the tier should be one of green/yellow/red, but never be described as an LLM output; it comes from deterministic scoring).

### FR6 — Deterministic Scoring
- [ ] **Verify:** Trigger a run and let it complete.
- [ ] **Verify:** Pick one idea from the final list and note its sub-scores (if visible: catalyst/momentum/macro sub-scores).
- [ ] **Verify:** Re-apply the documented formula manually:
  - **Formula:** `score = (catalyst_subscore * 0.40) + (sector_subscore * 0.35) + (macro_subscore * 0.25)`
  - **Thresholds:** Green (70-100), Yellow (50-69), Red (<50)
- [ ] **Verify:** Confirm the resulting tier matches exactly what the UI shows for that idea.
- [ ] **Verify:** (Code-review check) Run `pytest tests/test_scoring.py -v` and confirm all scoring tests pass.

### FR5 — Compilation/Verdict Stage
- [ ] **Verify:** Trigger a run and let it complete.
- [ ] **Verify:** Inspect the run's cost log after completion: `cost_compilation_usd` should show exactly one Sonnet call's worth of cost, not one per idea.
- [ ] **Verify:** For each idea shown, confirm a polished rationale text is present (built from the Haiku reasoning, refined by Sonnet).
- [ ] **Verify:** Observe that the final ranking and commentary text is present (comparing ideas relative to each other, not just individual rationales).
- [ ] **Verify:** Pick one idea's score/tier from the UI; confirm it remains unchanged before and after this step (Sonnet refines text only, never changes scores).

### FR7 — Output Cap, Ordering, and Citation
- [ ] **Verify:** Trigger a run and let it complete.
- [ ] **Verify:** Count the ideas shown on the main page: confirm ≤10 ideas (never more than 10).
- [ ] **Verify:** Inspect the tier order: green-tier ideas appear first, then yellow-tier, then red-tier (if any).
- [ ] **Verify:** For each idea shown:
  - If it's green or yellow: confirm it has a visible citation link.
  - If it's red: confirm it's labeled distinctly (e.g., "⚠ Low confidence — backfilled").
- [ ] **Verify:** Trigger a run that might produce more than 10 viable candidates (or inspect the database to confirm truncation logic).
  - If the run produces >10 candidates: confirm exactly 10 ideas are shown, ordered green > yellow > red.
  - If any red-tier idea is shown, confirm all yellow/green ideas are exhausted (red only fills gaps).
- [ ] **Verify:** (Code-review check) Run `pytest tests/test_assembly.py -v` and confirm all assembly tests pass (cap, ordering, backfill labeling).

### FR8 — Retention
- [ ] **Verify:** Open the SQLite database: `sqlite3 app/app.db`
- [ ] **Verify:** Check all tables that reference source articles (sweep_items, ...): `SELECT name FROM sqlite_master WHERE type='table' AND name LIKE '%sweep%' OR name LIKE '%source%' OR name LIKE '%item%';`
- [ ] **Verify:** For each table, inspect the schema: `PRAGMA table_info(<table_name>);`
- [ ] **Verify:** Confirm no column named `body`, `full_text`, `content`, `article_body`, `raw_html`, `text` exists.
- [ ] **Verify:** Spot-check a few rows: `SELECT * FROM sweep_items LIMIT 1;` — confirm snippets are short (< 300 chars), not full articles.

### FR9 — Disclaimer
- [ ] **Verify:** Navigate to the main page (latest run view): `/` — confirm the disclaimer text is visible at the bottom.
- [ ] **Verify:** Read the exact disclaimer: "For personal informational use only. Not investment advice. Not a registered investment adviser. No trades are placed automatically -- review and decide manually."
- [ ] **Verify:** Trigger a run, wait for completion, then navigate to the latest run view: `/` — confirm disclaimer is still visible.
- [ ] **Verify:** Navigate to the history page: `/history` — click on a past run to view its detail.
- [ ] **Verify:** Confirm the disclaimer is visible on the history detail view as well.
- [ ] **Verify:** Trigger a run, then immediately trigger a second run (quick-sweep skip scenario).
- [ ] **Verify:** After the skipped run completes, navigate to its detail view and confirm the disclaimer is still present.

### FR10 — No Auto-Execution
- [ ] **Verify:** (Code-review check) Run `pytest tests/test_no_brokerage_code.py -v` and confirm all 4 tests pass:
  - No brokerage SDK imports
  - No brokerage substrings in source
  - No order-placement endpoint strings
  - No brokerage dependencies in pyproject.toml
- [ ] **Verify:** Manually search the codebase for any reference to Zerodha, Kite, Upstox, or other brokers: `grep -r "zerodha\|kite\|upstox" app/` — confirm zero matches.
- [ ] **Verify:** Confirm there is no brokerage API key or credential field anywhere in config files or environment variables.

### FR11 — App Shell and Access Control
- [ ] **Verify:** (Code-review check) Run `pytest tests/test_binding_config.py -v` and confirm all 3 tests pass:
  - App/main.py never references 0.0.0.0 as bind host
  - uvicorn.run() uses host='127.0.0.1' explicitly
  - No token-mint or Origin-pinning code exists
- [ ] **Verify:** The app is running on `127.0.0.1:8000` (check console output: "Uvicorn running on http://127.0.0.1:8000").
- [ ] **Verify:** Attempt to connect from a different bind address (if possible on this machine): `curl http://0.0.0.0:8000/` should NOT respond (connection refused).
- [ ] **Verify:** Trigger a run via the "Run now" button, then immediately (before it completes) trigger a second run.
- [ ] **Verify:** Confirm the second attempt is rejected with an HTTP 409 (Conflict) response: "run already in progress".
- [ ] **Verify:** Stop and restart the app process (Ctrl+C, then re-run).
- [ ] **Verify:** Confirm the latest run is still visible on the main page (state persisted in SQLite, not lost after restart).
- [ ] **Verify:** Confirm the history page shows all past runs (history persisted, not cleared on restart).

### FR13 — Cost Visibility
- [ ] **Verify:** Trigger a run and let it complete.
- [ ] **Verify:** On the latest run view, look for a cost breakdown (e.g., "Cost: $X.XX (sweep: $Y, deep-dive: $Z, compilation: $W)").
- [ ] **Verify:** Confirm all three stages are listed: sweep, deep-dive, and compilation.
- [ ] **Verify:** Confirm the `total_cost_usd` is the sum of the three stages.
- [ ] **Verify:** No warning or error message appears, regardless of the cost amount (no blocking or aborting due to cost).
- [ ] **Verify:** Trigger a run that produces many candidates (deep-dive calls for multiple stocks).
- [ ] **Verify:** After completion, confirm the `cost_deep_dive_usd` reflects the total cost of all deep-dive calls combined (not per-call, aggregated).
- [ ] **Verify:** (Code-review check) Run `pytest tests/test_cost_tracking.py -v` and confirm all cost-tracking tests pass.

### Negative Filtering (within FR4)
- [ ] **Verify:** (Code-review check) Run `pytest tests/test_run_orchestrator_filtering.py -v` and confirm filtering tests pass:
  - Pump-and-dump candidate is excluded
  - Stale news candidate is excluded
  - Clean candidate is kept
- [ ] **Verify:** Trigger a run and observe the final ideas list.
- [ ] **Verify:** Confirm no idea in the final list exhibits obvious pump-and-dump indicators (no sudden chatter with low volume, no suspicious promotional mentions).
- [ ] **Verify:** Confirm no idea in the final list references already-stale news (dates are recent, not days/weeks old).

---

## Test Suite Status

- [ ] **All tests pass:** Run `pytest tests/ -v -rs` and confirm:
  - Zero failures
  - Zero errors
  - Zero skips (except documented opt-in live-SDK tests marked with `@pytest.mark.live_sdk` or similar)
  - Final count: 234+ passed, 3 skipped (live-SDK tests)

---

## Findings and Notes

(Record any issues found and fixed, or anything that couldn't be verified, below.)

### Issues Found and Fixed
(None expected if all tests pass; record any here if encountered.)

### Blocked or Unable to Verify
(List any acceptance criteria that could not be verified, with reason.)

---

## Sign-Off

**Verifier:** _________________________  
**Date:** ________________  
**All criteria verified:** [ ] Yes [ ] No (if No, list blocked items above)

