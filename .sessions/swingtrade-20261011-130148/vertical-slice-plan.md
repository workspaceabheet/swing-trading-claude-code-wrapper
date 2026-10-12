# ORDERED SLICE SUMMARY (for quick reference)

0. **S0 — App shell + run-lock + fake end-to-end run** — prove the full plumbing (UI → API → run-lock → background task → SQLite → UI display) with a hardcoded fake "idea," before any real data/LLM complexity.
1. **S1 — First real data-source adapter (Moneycontrol RSS) wired into the run** — replace the fake sweep input with one real external fetch, still producing a fake/stubbed idea output.
2. **S2 — Remaining data-source adapters (NSE Bhavcopy, Screener.in, Trading Economics)** — all four/five sources feeding one shared normalized shape, still no LLM yet.
3. **S3 — Quick-sweep change detection (FR2)** — hash/diff against prior run's sweep snapshot; skip path short-circuits before any LLM stage.
4. **S4 — Haiku sweep + deep-dive stage against fakes (FakeHaikuSession)** — orchestrator wired to the session-port protocol, full sweep→shortlist→deep-dive flow proven with canned data, no live SDK/network calls yet.
5. **S5 — Deterministic scoring module (FR6)** — pure, LLM-independent scoring formula consuming Haiku sub-scores, unit-tested at every threshold boundary.
6. **S6 — Negative filtering (pump-and-dump + stale-news, within FR4)** — concrete thresholds/checks applied between deep-dive output and scoring assembly.
7. **S7 — Real Haiku session (live SDK) replacing the fake** — swap FakeHaikuSession for the real ephemeral Haiku ClaudeSDKClient; per-stock failure isolation (skip-and-continue) proven against live calls.
8. **S8 — Sonnet compilation/verdict stage (FR5), fake then real** — single compilation call over all surviving candidates; exactly-once-per-run invocation proven; fake first, then real SDK swap.
9. **S9 — Output assembly: cap/ordering/red-tier backfill/labeling (FR7)** — the top-10 assembly logic with citation hard-constraint and low-confidence backfill labeling.
10. **S10 — Run history browsing (J3)** — history view/endpoint over real persisted multi-run data, survives restart.
11. **S11 — Cost visibility/logging (FR13)** — per-stage cost captured from real SDK usage and displayed on run records.
12. **S12 — Disclaimer, retention-guarantee hardening, and full regression pass** — cross-cutting FR8/FR9/FR10 verification slice that closes out remaining acceptance criteria not already covered incidentally by earlier slices.

Slices are numbered for dependency order, not necessarily 1:1 with calendar effort — S1/S2 and S5/S6 are each small.

---

# Judgment calls / ordering tradeoffs to confirm with the user before Stage 3

1. **Fake-first, real-second split for both LLM stages (S4/S7 and S8).** I split "wire the LLM stage against fakes" from "swap in the real SDK client" into separate slices rather than building directly against the real SDK. This lets the orchestrator/scoring/assembly logic be fully proven before paying for any real Haiku/Sonnet calls, and gives early demo value without live network+auth dependencies. Tradeoff: it adds two extra slice boundaries (S4→S7, S8's internal fake→real swap) that are "thin" in user-visible novelty the second time (the UI/output looks identical; only the data source behind it changes from canned to real). If the user would rather collapse fake+real into one slice per stage (accepting that the demo of S4 looks identical to S7), that's a reasonable alternative — flagging for confirmation.

2. **Negative filtering (S6) placed after scoring (S5) but before the real Haiku swap (S7).** The spec's FR4 negative filters (pump-and-dump indicators, stale-news cross-check) conceptually belong inside/after the deep-dive stage. I sliced them against the fake deep-dive output first (so the filter logic itself is unit-testable deterministically), then re-validated against real Haiku output in S7. An alternative is to fold negative filtering directly into S4 (build it alongside the fake deep-dive wiring) rather than as its own slice — I kept it separate because the spec explicitly flags the exact thresholds/mechanics as an unresolved design question (§11) that deserves its own focused implementation+review step, not a no-op riding along with S4. Worth confirming the user is fine with filtering being "designed" in S6 rather than decided earlier in Stage 3 planning.

3. **Quick-sweep change detection (S3) placed before any LLM wiring, right after sourcing is complete.** This matches the spec's architecture (quick-sweep runs before any LLM stage) and lets S3 be demoed meaningfully (second run short-circuits) using only the real sourcing adapters from S1/S2, with the "would-be" LLM stage still a stub. Alternative: some teams prefer to build the "happy path through all stages" first and bolt on the skip-optimization last, since quick-sweep is logically an optimization/short-circuit rather than core value. I chose spec-order placement because FR2/FR12 are core functional requirements (not an optional optimization) and because testing the skip path is much cleaner before the LLM stages exist (nothing expensive to accidentally invoke). Flagging in case the user prefers quick-sweep later, after S8, once there's a "real" expensive run to meaningfully skip.

4. **Polling vs. SSE for progress updates** is already locked per the decisions provided (simple polling, not SSE) — reflected in S0's plumbing design, not re-raised as an open question.

5. **History browsing (S10) placed after both LLM stages (S8) rather than right after S0.** Technically a history view could be demoed as early as S0 (even against fake data) since persistence exists from the start. I deferred the dedicated "browse history" slice until after the real pipeline produces materially different multi-run data (to make the slice's manual test meaningful — comparing two distinct real runs), but S0 through S9 each still write a persisted run row, so history is implicitly exercised earlier. If the user wants an explicit early "browse history" demo moment (e.g., right after S0, with fake runs), that's easy to pull forward — flagging as a possible reordering.

---

# FULL VERTICAL-SLICE PLAN

## Locked inputs (not reopened)
- Tech spec: `.sessions/swingtrade-20261011-130148/tech-spec.md`
- Stage 1 initial plan: `.sessions/swingtrade-20261011-130148/initial-plan.md`
- Two sequenced ephemeral Claude Agent SDK clients per run (Haiku for sweep+deep-dives, then fresh Sonnet for compilation).
- Per-stock Haiku deep-dive failure → skip that stock, continue the run.
- UI progress via polling (re-fetch run status), not SSE.
- Lighter project structure than `ai-job-finder-console` (per initial-plan.md Decision B layout), same separation philosophy (LLM session seam, deterministic scorer, source adapters).
- One adapter per source, shared base normalized shape + source-specific extra fields.
- Fakes for both LLM stages (`FakeHaikuSession`, `FakeCompilationSession`) satisfying the same protocol as the real sessions, for full integration testability without network/LLM calls.

---

## Slice 0 — App shell, run-lock, and a fully fake end-to-end run

**Outcome:** The entire plumbing path — UI button → API endpoint → run-lock → background task → SQLite persistence → polling status → UI card display — works end-to-end using one hardcoded fake idea, before any real data or LLM complexity is introduced.

**User value:** Proves the skeleton of the whole app is real and navigable. The user can click "Run now," watch a run go from `running` to `complete`, and see a (fake) ranked idea card with a disclaimer — the full shape of the final product, minus any real intelligence.

**Scope:**
- FastAPI app bound to `127.0.0.1` only, Jinja2 templates, static assets.
- SQLite schema v0: `runs` table (id, status, started_at, finished_at) and `ideas` table (run_id, ticker, entry, target, hold_days, tier, rationale, citation_url, low_confidence flag) — schema will grow in later slices but must exist now in a form later slices can extend via migration-light additions.
- In-memory run-lock (409 if a run is already in progress), mirroring sibling's `run_lock.py`.
- `RunOrchestrator` stub: on "Run now," acquires lock, runs as a background task, sleeps/simulates minimal work, writes one hardcoded fake idea (fixed ticker, score, tier, rationale, citation) to SQLite, releases lock.
- Startup lifespan hook: reconciles any row left `running` from a crashed process to `error`.
- UI: index page with "Run now" button, polling-based status display, a ranked card showing the one fake idea, and the mandatory disclaimer text rendered on every results view.
- **Explicit exclusions:** no real data sourcing, no LLM calls of any kind, no scoring formula, no negative filtering, no history browsing view (a single "latest run" view is enough here), no cost logging beyond a placeholder `0.0` field.

**Frontend/backend/API/data:**
- `GET /` — index page.
- `POST /api/run` — acquire lock, launch background task, return run id.
- `GET /api/run/status` — lock/run state for polling.
- `GET /api/run/last` — latest run + its ideas for page load and poll-refresh.
- `db.py` — schema + connection helpers.
- `run_lock.py`, `run_orchestrator.py` (stub pipeline), `templates/index.html`.

**Dependencies/prerequisites:** None — first slice.

**Acceptance criteria:**
- Clicking "Run now" transitions run status `running` → `complete` and the UI (via polling) reflects this without a page reload.
- Attempting a second run while one is in progress returns HTTP 409.
- The fake idea appears as a card with ticker, entry/target/hold, tier badge, rationale, citation link, and the disclaimer is visible.
- Restarting the app with no runs in progress and re-loading `/` still shows the last completed run (state in SQLite, not memory).
- A run interrupted by process crash (simulate by killing the process mid-run) is reconciled to `error` status on next startup.

**Automated tests:**
- Unit: run-lock acquire/release/conflict behavior.
- Integration: `POST /api/run` → poll `GET /api/run/status` until complete → `GET /api/run/last` returns the fake idea with expected shape.
- Integration: startup reconciliation sweep flips a stale `running` row to `error`.

**Manual tests:** Start the app, open the browser, click "Run now," watch the status change and the card render; try clicking "Run now" again mid-run and confirm the UI handles the 409 gracefully; restart the server and confirm the last run still displays.

**How to run/access:** `uvicorn app.main:app --reload` (binding `127.0.0.1`), open `http://127.0.0.1:8000/`.

**What the user should verify:** The full loop — trigger, progress, completion, display, persistence-across-restart, disclaimer presence, double-run rejection — works with zero real data/LLM involvement yet.

**Completion/validation:** All acceptance criteria above pass via automated tests plus one manual click-through; no real adapters or LLM code paths exist yet (confirmed by grep/review).

---

## Slice 1 — First real data-source adapter (Moneycontrol RSS) feeding the run

**Outcome:** The orchestrator's sourcing step now performs one real external fetch (Moneycontrol RSS) and normalizes it into the shared record shape; the rest of the pipeline (scoring/LLM) is still faked, so the fake idea's rationale/citation can now optionally echo a real fetched headline to prove the data is flowing, or the idea output can remain fully fake while the fetched items are persisted/visible separately (recommended: surface the raw fetched headlines in a simple debug/"sources seen" section of the run detail view, decoupled from the still-fake idea card).

**User value:** First real, externally-sourced data enters the system; the user can see actual current Moneycontrol headlines pulled live, validating that outbound fetching, parsing, and retention-safe normalization work before any LLM or scoring complexity is added.

**Scope:**
- `sources/moneycontrol_rss.py` — fetch + parse RSS XML → list of `NormalizedItem` (source, headline, url, published_at, snippet, ticker: None for most RSS items).
- `sources/base.py` — `NormalizedItem` shape + `SourceAdapter` Protocol.
- Orchestrator calls the adapter during the run and persists the fetched items (headline/source/date/url/snippet only — hard constraint, no full article body ever touches a variable or a table).
- Run detail view/section shows the raw fetched headlines for this run (debug/transparency, not yet the final idea content).
- **Explicit exclusions:** no other adapters yet, no quick-sweep diffing yet (every run re-fetches fresh), no LLM involvement, idea output can remain the Slice 0 fake card.

**Frontend/backend/API/data:**
- `sources/base.py`, `sources/moneycontrol_rss.py`.
- Orchestrator step 1 (data collection) now real for this one source.
- New table (or JSON column) for persisted sweep items per run, retention-safe fields only.
- Optional: `GET /api/run/{id}/sources` or inline in run detail template.

**Dependencies/prerequisites:** Slice 0 (app shell, orchestrator, persistence, run flow).

**Acceptance criteria:**
- A real run fetches current Moneycontrol RSS content and persists it with only headline/source/date/url/snippet fields.
- No code path in the adapter or its persistence ever stores or returns full article body text.
- If the RSS feed is unreachable, the run still completes (sourcing failure for this one adapter is handled gracefully, not an unhandled crash) — demonstrates resilience pattern reused by later adapters.

**Automated tests:**
- Unit: adapter parses a fixture RSS XML blob into expected `NormalizedItem`s.
- Unit: retention guarantee — no field/attribute on `NormalizedItem` or the persisted row can hold more than the snippet-length content (assert via a fixture with a long body that it gets truncated/rejected, never stored whole).
- Integration: orchestrator run persists fetched items from a stubbed adapter (not hitting real network in CI).

**Manual tests:** Trigger a real run against the live Moneycontrol feed, inspect the run detail page's fetched-headlines section and the SQLite row contents directly to confirm no full-body text is present.

**How to run/access:** Same app, same "Run now" button; new section on run detail page shows fetched headlines.

**What the user should verify:** Real, current Moneycontrol headlines appear after a run; inspecting the DB shows only the retained fields, never full text.

**Completion/validation:** Acceptance criteria pass; retention unit test passes; manual DB inspection confirms no full-body leakage.

---

## Slice 2 — Remaining data-source adapters (NSE Bhavcopy, Screener.in, Trading Economics[, optional secondary RSS])

**Outcome:** All configured sources feed into one aggregated sweep dataset per run, each via its own adapter, normalizing into the shared base shape with source-specific extra fields layered on (e.g., Bhavcopy's OHLC/volume).

**User value:** The sweep dataset is now complete and realistic — news, EOD price/volume data, fundamentals, and macro calendar context all present together, which is the actual raw material the later LLM sweep stage will reason over.

**Scope:**
- `sources/nse_bhavcopy.py` — fetch/parse EOD CSV → `NormalizedItem`-with-OHLC/volume extension.
- `sources/screener_in.py` — fetch/parse fundamentals page → normalized record(s) per ticker.
- `sources/trading_economics.py` — fetch/parse macro calendar → normalized record(s).
- Optional secondary RSS adapter (same shape as Moneycontrol's), if pursued now or deferred to a backlog note.
- A small sourcing aggregator that calls all adapters and merges results (continuing even if one adapter fails — same per-adapter resilience pattern as Slice 1).
- **Explicit exclusions:** still no quick-sweep diffing, no LLM stage, no scoring; idea output remains the Slice 0 fake card; run detail's "fetched items" section now shows all sources together.

**Frontend/backend/API/data:**
- `sources/nse_bhavcopy.py`, `sources/screener_in.py`, `sources/trading_economics.py`, aggregator function/module.
- Persisted sweep-items table/column now holds a mix of item types; Bhavcopy's extra fields (volume, close, prev_close) stored alongside the shared base fields.

**Dependencies/prerequisites:** Slice 1 (adapter pattern, shared shape, persistence path established).

**Acceptance criteria:**
- A run fetches and normalizes data from all four/five configured sources (Moneycontrol RSS, Bhavcopy, Screener.in, Trading Economics[, secondary RSS]) into the shared base shape with source-specific extensions where applicable.
- Zero full-article-body or full-page-content fields are persisted from any adapter.
- If any single adapter fails (network error, parse error), the run still completes with the remaining sources' data (adapter-level isolation, not whole-run failure).

**Automated tests:**
- Unit: fixture-based parse test per new adapter (canned CSV/HTML bytes → expected normalized records, including Bhavcopy's extra OHLC/volume fields).
- Unit: retention guarantee extended to each new adapter.
- Integration: aggregator continues and returns partial results when one adapter is stubbed to fail.

**Manual tests:** Trigger a real run; confirm the run detail view shows items/rows from all sources; spot-check Screener.in fundamentals and Bhavcopy OHLC values look sane for a known ticker.

**How to run/access:** Same "Run now" flow; run detail view's sources section now richer.

**What the user should verify:** All sources are represented in a single run's fetched data; one source going down doesn't take down the whole run.

**Completion/validation:** All acceptance criteria pass; per-adapter fixture tests pass; one manual full-sweep run reviewed by the user.

---

## Slice 3 — Quick-sweep change detection (FR2/FR12)

**Outcome:** Before any LLM stage would run, the system compares the current run's aggregated sweep data against the immediately prior run's stored snapshot; if nothing material changed, the run completes immediately, reporting "prior output still current," without reaching the (still-stubbed) LLM stage.

**User value:** Re-running soon after a prior run is fast and clearly communicated as a no-op, directly delivering FR2/FR12's core promise — this is independently demonstrable and valuable even before the LLM stages exist, because the stub "would-be-expensive" stage is skipped visibly.

**Scope:**
- `quick_sweep.py` — hash/diff of normalized sweep items against the prior run's stored snapshot; concrete materiality definition decided now (e.g., hash of the set of (source, ticker/headline, published_at) tuples; a change counts as material if the hash differs — exact scope documented, since spec left this open).
- Orchestrator: if quick-sweep says "unchanged," mark run `skipped_no_change`, copy forward (reference) the prior run's ideas for display, persist the flag, and stop — never reach the LLM/scoring stub.
- If changed, proceed to the (still-stubbed from Slice 0) next stage as before.
- UI: run status/detail clearly shows "no material change — prior results still current" when skipped.
- **Explicit exclusions:** no real LLM stage yet (still the Slice 0 fake idea path when not skipped); no scoring formula yet.

**Frontend/backend/API/data:**
- `quick_sweep.py`, orchestrator step 2.
- `runs` table gains `quick_sweep_skipped: bool`.
- Run detail/status response includes the skip flag and a human-readable message.

**Dependencies/prerequisites:** Slice 2 (full real sweep dataset to diff against).

**Acceptance criteria:**
- Two runs in quick succession with identical underlying sweep data: second run completes almost immediately, is flagged `quick_sweep_skipped=true`, and the UI reports prior output still stands.
- A run where the underlying sweep data has materially changed (e.g., fixture-injected new headline) proceeds past the quick-sweep check.
- The skip decision is made before any LLM-stage code path executes (verifiable by call-count assertions in tests).

**Automated tests:**
- Integration: identical sweep snapshots (fixture) → deep-dive/LLM stub is never invoked, run marked skipped.
- Integration: materially different snapshots → stage proceeds, stub is invoked.
- Unit: hash/diff function behavior at the boundary of the materiality definition.

**Manual tests:** Run once, then run again immediately; observe the second run reports "no change" quickly in the UI. Then manually alter/wait for real source data to change and confirm a subsequent run proceeds normally.

**How to run/access:** Same "Run now" flow; UI messaging differs when skipped.

**What the user should verify:** Re-running shortly after a prior run is cheap and clearly communicated, matching FR2/FR12.

**Completion/validation:** Acceptance criteria pass; the user confirms the skip messaging is clear and trustworthy.

---

## Slice 4 — Haiku sweep + deep-dive stage against fakes (FakeHaikuSession)

**Outcome:** The orchestrator is wired to a `HaikuSession` protocol/port; using `FakeHaikuSession` (canned sweep shortlist + canned per-candidate deep-dive sub-scores/reasoning/citations), the full sweep→shortlist→deep-dive flow runs end-to-end and produces real (not hardcoded) idea data driven by the fake session's canned responses — proving the orchestration logic without any live LLM/network dependency.

**User value:** First time the output cards reflect actual pipeline logic (shortlisting + per-candidate reasoning) rather than one static fake idea — demonstrable and reviewable, and fully reproducible/debuggable since it's driven by fixtures.

**Scope:**
- `agent/sessions.py` — `HaikuSession` Protocol (e.g., `run_sweep(items) -> shortlist`, `run_deep_dive(ticker, context) -> sub-scores+reasoning+citations`).
- `fakes/fake_sessions.py` — `FakeHaikuSession` with canned sweep output and per-ticker canned deep-dive output; records calls (`self.calls`) for test assertions; supports a map-lookup "raise error for this ticker" trick to simulate per-stock failure.
- Orchestrator steps 3-4: call sweep, get shortlist (bounded, e.g. up to ~15-20 candidates to comfortably yield 10 after filtering — concrete bound decided and documented here since spec left it open), then sequential deep-dive calls per shortlisted ticker.
- Per-stock deep-dive failure handling (locked decision): if one deep-dive call fails, log it, skip that ticker, continue the run with the rest — implemented and tested here even though it's only exercised against the fake for now.
- Idea assembly is still simplistic (no scoring/negative-filtering/tiering yet — raw sub-scores displayed as-is or a placeholder tier) since those are Slices 5-6.
- **Explicit exclusions:** no real `ClaudeSDKClient` yet (that's Slice 7); no scoring formula yet (Slice 5); no negative filtering yet (Slice 6); no Sonnet compilation yet (Slice 8).

**Frontend/backend/API/data:**
- `agent/sessions.py` (protocol), `fakes/fake_sessions.py`, `agent/sweep.py`/`agent/deep_dive.py` (call+parse logic against the protocol).
- `candidates`/deep-dive-result persistence (ticker, sub-scores, reasoning, citations) — new table or JSON column.
- Orchestrator extended with steps 3-4 wired to the protocol (test injects the fake; later slices inject the real session).

**Dependencies/prerequisites:** Slice 3 (quick-sweep gate must exist so this expensive-looking stage is only reached on material change).

**Acceptance criteria:**
- A run that proceeds past quick-sweep produces a shortlist via the fake sweep call, then one deep-dive call per shortlisted ticker via the fake session.
- A per-stock deep-dive failure (simulated via the fake raising for one ticker) results in that ticker being skipped, with the rest of the run completing normally — not an aborted run.
- `FakeHaikuSession.calls` shows exactly one sweep call and one deep-dive call per surviving shortlisted candidate.

**Automated tests:**
- Integration: full run with `FakeHaikuSession` → assert shortlist size bound respected, one deep-dive call per shortlisted ticker, call counts recorded correctly.
- Integration: one ticker's fake deep-dive configured to raise → assert run completes, that ticker is absent from results, others present.

**Manual tests:** Trigger a run (fakes wired by default in a dev/test config toggle) and inspect that cards now reflect distinct per-ticker canned reasoning instead of one static fake idea.

**How to run/access:** Same "Run now" flow, with the app configured to use `FakeHaikuSession` (e.g., a dev/test settings flag or default-until-Slice-7 wiring).

**What the user should verify:** Distinct, per-candidate reasoning now drives the output; a simulated per-stock failure doesn't take down the whole run.

**Completion/validation:** All acceptance criteria pass via integration tests using the fake; no real SDK code path exists yet.

---

## Slice 5 — Deterministic scoring module (FR6)

**Outcome:** A pure, LLM-independent scoring module computes the 0-100 composite score and red/yellow/green tier from Haiku sub-scores using the documented weighted formula (§6), fully unit-testable without any session (real or fake).

**User value:** The score/tier shown on each card is now the real, reproducible, documented formula rather than a placeholder — this is the credibility-critical piece of the product (deterministic, auditable scoring) and is independently verifiable by the user re-computing by hand.

**Scope:**
- `scoring.py` — pure function(s): `compute_score(catalyst_subscore, sector_subscore, macro_subscore) -> (score: int, tier: Literal["red","yellow","green"])` per §6 weights/thresholds.
- Orchestrator step 5: apply `scoring.py` to each surviving deep-dive candidate's sub-scores (from the fake session for now) to get final score/tier.
- Idea cards now show the real computed score/tier badge instead of a placeholder.
- **Explicit exclusions:** no negative filtering yet (Slice 6); no real Haiku/Sonnet (Slices 7-8); no output cap/backfill ordering logic yet (Slice 9 — for now, all surviving candidates display, unordered or naively ordered).

**Frontend/backend/API/data:**
- `scoring.py` (pure module, zero LLM import — testable in isolation).
- Orchestrator wiring; `ideas` table gains real `score`/`tier` columns (if not already present from Slice 0's placeholder).

**Dependencies/prerequisites:** Slice 4 (candidates with sub-scores to score).

**Acceptance criteria:**
- Given any sub-score inputs, `compute_score` reproduces the documented formula exactly, including behavior at every threshold boundary (69/70, 49/50).
- The score/tier is identical regardless of anything downstream (no LLM involvement in scoring) — reproducible by re-running the pure function with the same inputs.
- Cards in the UI reflect the real computed tier/score.

**Automated tests:**
- Unit: table-driven tests covering weak/moderate/major catalyst bands, each sector-momentum band, each macro modifier band, and exact threshold boundaries for all three tiers.
- Integration: full fake-driven run now shows real computed scores/tiers matching what `scoring.py` would produce standalone for the same fake sub-score inputs.

**Manual tests:** Trigger a run, pick one card, manually recompute its score from the displayed sub-scores using the documented formula, and confirm it matches the badge shown.

**How to run/access:** Same flow; cards' tier badges now reflect the real formula.

**What the user should verify:** The scoring is transparent and reproducible — the user can audit any card's tier by hand.

**Completion/validation:** All unit tests (including boundary cases) pass; one manual hand-check by the user confirms the formula is applied correctly.

---

## Slice 6 — Negative filtering (pump-and-dump + stale-news, within FR4)

**Outcome:** Candidates exhibiting pump-and-dump indicators or stale/already-priced-in news are flagged/excluded during assembly, with concrete, documented thresholds (volume cutoff, institutional-ownership signal, promotional-chatter heuristic, stale-news cross-check against NSE announcement dates) decided and implemented here, resolving the spec's explicitly-left-open design question.

**User value:** The output is now protected against the two noise patterns the user explicitly wanted filtered out (tip-chatter pump-and-dump, stale already-priced-in news) — a core differentiator of the tool versus manual scanning.

**Scope:**
- `negative_filters.py` — concrete, documented rules:
  - Pump-and-dump: e.g., daily volume below an absolute or relative-to-average threshold AND no institutional-ownership signal from Screener.in data AND promotional-chatter flag from Haiku's deep-dive reasoning → flag/exclude.
  - Stale-news: deep-dive-reported catalyst date cross-checked against NSE announcement date (sourced from Bhavcopy/announcement data where available) beyond a defined staleness window → flag/exclude.
- Orchestrator step 6: apply filters to surviving deep-dive candidates before scoring assembly (or in combination with Slice 5's scoring — ordering per spec: negative filtering happens within/after deep-dive, before final assembly).
- Filtered-out candidates are excluded from the final idea list, with the exclusion reason recorded (for debugging/audit, not necessarily shown to the user in v1 UI).
- **Explicit exclusions:** no real Haiku yet (fake continues to supply sub-scores/reasoning/flags for filter logic to act on); no output cap/ordering/backfill logic yet (Slice 9).

**Frontend/backend/API/data:**
- `negative_filters.py`.
- Orchestrator wiring; candidate record gains `excluded: bool` + `exclusion_reason: str | None`.

**Dependencies/prerequisites:** Slice 5 (scoring exists; filtering happens in the same assembly neighborhood) — technically only depends on Slice 4's candidate data, but sequenced after scoring since both modify assembly together.

**Acceptance criteria:**
- A fixture candidate with low volume + no institutional ownership + promotional-chatter flag is excluded from the final list.
- A fixture candidate whose catalyst date cross-checks as stale against a known NSE announcement date is excluded.
- A clean candidate (no negative-filter triggers) is not excluded by this stage.

**Automated tests:**
- Unit: pump-and-dump rule — table-driven cases across the threshold boundaries.
- Unit: stale-news rule — cases where catalyst date is before/after the staleness window relative to the announcement date.
- Integration: full fake-driven run with one deliberately pump-and-dump-flagged fixture candidate and one clean candidate → only the clean one survives to output.

**Manual tests:** Configure the fake session to return one candidate with filter-triggering characteristics and one without; run; confirm only the clean one appears.

**How to run/access:** Same flow.

**What the user should verify:** The specific filtering rules now implemented are the ones they expect (this is a good moment for the user to sanity-check the concrete thresholds chosen, since the spec left exact mechanics open).

**Completion/validation:** Unit + integration tests pass; user reviews and confirms the concrete thresholds chosen are acceptable (or requests adjustment before Stage 3 locks them in further).

---

## Slice 7 — Real Haiku session (live Claude Agent SDK) replacing the fake

**Outcome:** `FakeHaikuSession` is swapped for a real ephemeral `ClaudeSDKClient`-backed `HaikuSession` implementation — one Haiku client connects at run start, serves the sweep call (with web search/fetch tools enabled) and all deep-dive calls (no web tools, reasoning over already-fetched content), then disconnects. All orchestration, scoring, and filtering logic from Slices 4-6 now runs against genuinely live LLM output.

**User value:** The pipeline's core intelligence is now real — actual Haiku reasoning over actual fetched data produces the shortlist, sub-scores, reasoning, and citations the user will actually rely on.

**Scope:**
- `agent/sessions.py` real implementation: connect, `run_sweep`, `run_deep_dive` (sequential, up to 10), disconnect — matching the locked two-client architecture.
- Prompt templates (`agent/prompts.py`) for sweep and deep-dive calls, respecting tool-enablement differences (web tools on for sweep, off for deep-dive).
- Real per-stock failure handling: a genuine Haiku exchange error/timeout for one ticker is caught, logged, and that ticker skipped — run continues (now proven against real failure modes, not just the fake's simulated ones).
- Shortlist-size bound (decided in Slice 4) enforced against real sweep output too.
- **Explicit exclusions:** no Sonnet/compilation yet (Slice 8, still produces Haiku-only rationale); cost logging not yet captured (Slice 11) — can log informally to console for dev visibility but not yet persisted/displayed.

**Frontend/backend/API/data:**
- `agent/sessions.py` real class, `agent/prompts.py`.
- Config/wiring to select fake vs. real session (test suite always uses fake; app defaults to real).

**Dependencies/prerequisites:** Slices 4-6 (orchestration, scoring, filtering all proven against the fake first) — swapping the session implementation should require no orchestrator logic changes if the protocol boundary was respected.

**Acceptance criteria:**
- A real run produces a shortlist and deep-dive results from genuine Haiku calls (verifiable by output varying run-to-run with real market data, unlike the fixed fake).
- Web tools are enabled only for the sweep call, disabled for deep-dive calls (verifiable via `ClaudeAgentOptions`/tool config inspection or a test double asserting tool config at connect time).
- A real Haiku call failure for one candidate (can be forced via a deliberately malformed/unreachable scenario in a controlled test, or observed opportunistically) does not abort the run.
- The Haiku client disconnects cleanly at the end of this stage, before any compilation stage begins.

**Automated tests:**
- Integration (still using fakes in CI for determinism): protocol-conformance test ensuring the real session class satisfies the same interface the fake does (so orchestrator tests remain valid either way).
- A narrowly-scoped, explicitly-marked "live" test (manual/opt-in, not part of default CI) that exercises one real sweep+deep-dive call to confirm live wiring works end-to-end.

**Manual tests:** Trigger a real run against live data and the real SDK; review actual Haiku-produced shortlist/reasoning/citations for plausibility; verify logged per-call behavior (e.g., via application logs) matches expectations (right model, right tool config per stage).

**How to run/access:** Same "Run now" flow; now genuinely live — requires `claude login` auth to be active locally.

**What the user should verify:** Real Haiku-driven shortlisting and reasoning quality; citations are real, clickable, and attributable; a forced/observed per-stock failure doesn't sink the run.

**Completion/validation:** Acceptance criteria pass; user reviews at least one real live run's Haiku output for sanity before proceeding.

---

## Slice 8 — Sonnet compilation/verdict stage (FR5), fake then real

**Outcome:** A single Sonnet call per run, invoked once over all surviving candidates together (not per-candidate), produces polished per-idea rationale text and cross-candidate ranking commentary — strictly read-only with respect to score/tier. Built and proven against `FakeCompilationSession` first, then swapped to a real ephemeral Sonnet `ClaudeSDKClient`.

**User value:** Final output rationale is now polished, cross-referenced, and includes ranking commentary explaining relative ordering — the last piece of "intelligence" the spec requires before output assembly.

**Scope:**
- `agent/sessions.py` — `CompilationSession` Protocol (`run_compilation(candidates_with_scores_and_reasoning) -> {per_idea: polished_rationale, ranking_commentary}`).
- `fakes/fake_sessions.py` — `FakeCompilationSession`, asserts exactly-once-per-run invocation via recorded call count.
- Real implementation: a fresh Sonnet `ClaudeSDKClient` connects just for this one call, after the Haiku client has disconnected, then disconnects immediately after.
- Orchestrator step 7: pass all surviving (post-scoring, post-filtering) candidates' deterministic scores/tiers + Haiku sub-scores/reasoning together into one compilation call; byte-for-byte preserve scores/tiers from before this stage (hard invariant).
- **Explicit exclusions:** output cap/ordering/backfill (Slice 9) still not applied — this stage operates on however many candidates survived filtering, which may exceed/be fewer than 10.

**Frontend/backend/API/data:**
- `agent/sessions.py` (`CompilationSession` protocol + real + fake), `agent/compilation.py` (call + parse), `agent/prompts.py` extended with the compilation prompt.
- Idea records gain a `polished_rationale`/`ranking_commentary_fragment` field distinct from the raw Haiku rationale.

**Dependencies/prerequisites:** Slice 7 (real candidates with real scores/reasoning to compile) — though the fake-session half can be built directly after Slice 6 if preferred; sequenced after 7 here so the compilation stage is demoed against genuinely real upstream data from the start, minimizing rework.

**Acceptance criteria:**
- Exactly one Sonnet call is made per run, regardless of candidate count (1 to 10), verified via the fake's call-count assertion in tests and via real-run logs/cost entries (informally) once swapped to real.
- Scores/tiers in the final persisted idea records are identical before and after the compilation stage runs (compilation can only affect rationale/ranking-commentary text fields).
- The Sonnet client connects only after the Haiku client has fully disconnected (sequencing, not concurrent sessions).

**Automated tests:**
- Integration: fixture candidates with pre-set scores/tiers + `FakeCompilationSession` → assert call count == 1, assert post-compilation scores/tiers match pre-compilation values exactly, assert rationale/ranking-commentary text fields are populated from the fake's canned output.
- A narrowly-scoped opt-in "live" test exercising one real compilation call (similar to Slice 7's live test).

**Manual tests:** Trigger a full real run (Haiku real, Sonnet real); review the polished per-idea rationale and ranking commentary for coherence and that they reference the correct candidates; confirm scores/tiers didn't change from what Slice 7 alone would have produced (compare before/after if feasible, or trust the invariant test).

**How to run/access:** Same "Run now" flow, now with both real LLM stages active end-to-end.

**What the user should verify:** The final rationale reads as polished, coherent, cross-referenced text, and that this polish never alters the underlying deterministic score/tier.

**Completion/validation:** Acceptance criteria and invariant tests pass; user reviews at least one real full-pipeline run's compiled text.

---

## Slice 9 — Output assembly: cap, ordering, red-tier backfill, and citation hard-constraint (FR7)

**Outcome:** Final assembly logic caps the list at 10 ideas, orders green > yellow > red, fills with yellow/green first, backfills with red-tier only when fewer than 10 yellow/green exist (clearly and distinctly labeled low-confidence), and drops any idea lacking a citation — all as explicit, independently unit-tested assembly code.

**User value:** The output a user actually sees now matches the spec's hard guarantees exactly: never more than 10 ideas, correctly ordered, red-tier ideas unmistakably marked as lower-confidence backfill, and zero citation-less ideas ever shown — this is the core trust-building guarantee of the product.

**Scope:**
- `assembly.py` (or similar) — pure function: `assemble(candidates) -> list[Idea]` implementing cap/order/backfill/citation-drop logic exactly per FR7/§6/§9.
- Orchestrator step 8: apply assembly after compilation (Slice 8) and before persistence.
- UI: red-tier backfilled ideas rendered with a visually and textually distinct "low-confidence" label (not just a generic badge color) — e.g., a separate section, a distinct banner/icon, and explicit text, so they're never confusable with yellow/green cards.
- **Explicit exclusions:** history browsing UI (Slice 10) not yet built; cost logging (Slice 11) not yet built.

**Frontend/backend/API/data:**
- `assembly.py`.
- `ideas` table gains `low_confidence: bool` / `backfill: bool` flag (if not already added earlier).
- Template update for the distinct low-confidence card treatment.

**Dependencies/prerequisites:** Slice 8 (final candidates with polished rationale and ranking commentary to assemble) — though the pure assembly function can be unit-tested in isolation immediately, independent of Slices 7-8 being "real."

**Acceptance criteria:**
- Given 10+ yellow/green candidates, zero red-tier ideas appear in output.
- Given fewer than 10 yellow/green candidates, red-tier ideas backfill up to 10 total (or fewer if the whole pool is smaller), ordered strictly after all yellow/green ideas, and each is flagged `low_confidence=true` in the persisted data (not just incidentally stylable as such).
- A candidate missing a citation never appears in output, regardless of its score/tier.
- Final list order is always green-before-yellow-before-red; never more than 10 ideas regardless of how many candidates survived upstream stages.

**Automated tests:**
- Unit: table-driven cases — 10+ yellow/green (no red leak), fewer than 10 yellow/green (red backfill count and flag correctness), zero yellow/green (red-only list, all flagged), a mix including citation-less candidates (dropped regardless of score).
- Integration: full pipeline run (real or fake LLM stages) exercising the assembly step end-to-end, confirming the persisted and displayed list obeys every rule above.

**Manual tests:** Review a real run's output list; confirm ordering and that any red-tier card is unmistakably marked low-confidence; construct (or wait for) a run with fewer than 10 yellow/green ideas and confirm backfill behavior and labeling visually.

**How to run/access:** Same flow; final idea list now rule-complete.

**What the user should verify:** The final list always obeys the cap/order/backfill/citation guarantees — this is the most spec-critical slice to sign off on carefully.

**Completion/validation:** All table-driven unit tests and the integration test pass; user visually confirms the low-confidence labeling is clear and distinct, not easily missed.

---

## Slice 10 — Run history browsing (J3)

**Outcome:** A dedicated history view lets the user browse past runs (status, timestamp, cost placeholder, skipped-or-not) and open any past run's full idea list, with state surviving app restarts (already implicitly true since Slice 0, now given a proper browsing UI/API).

**User value:** The user can look back at what was suggested in prior runs and compare against what they recall happening since — directly delivering use case 3 from the spec (manual comparison, no automated feedback loop).

**Scope:**
- `GET /api/runs` — paginated/simple list of past run summaries.
- `GET /api/run/{run_id}` — a specific past run's full idea list + metadata.
- `history.html` (or a view-toggle on the existing template) listing past runs with status/timestamp/skip-flag, linking into each run's detail.
- **Explicit exclusions:** no cost figures yet (Slice 11 — show a placeholder or omit the cost column for now); no cross-run diffing/analytics beyond simple listing.

**Frontend/backend/API/data:**
- `routers/run.py` additions, `templates/history.html`.
- Reuses existing `runs`/`ideas` schema — no new persistence needed, since every slice since Slice 0 already wrote real run rows.

**Dependencies/prerequisites:** Slice 9 (so history has real, fully-assembled, rule-correct idea lists to browse, not partial/placeholder data) — though technically could be pulled earlier since persistence has existed since Slice 0 (flagged as a judgment call above).

**Acceptance criteria:**
- The history view lists all past runs in reverse-chronological order with status and skip-flag visible.
- Clicking into any past run shows that run's full, correctly-assembled idea list exactly as it was at completion time (immutable historical record).
- History is correct after an app restart (queried from SQLite, not memory).

**Automated tests:**
- Integration: seed multiple runs (via the test harness/fakes), query `/api/runs` and `/api/run/{id}`, assert correct ordering and content fidelity.

**Manual tests:** Run the pipeline two or three times (varying fake/real inputs to get different outcomes), then browse history and open each past run to confirm accurate recall.

**How to run/access:** New "History" link/nav item in the UI; `GET /api/runs` directly queryable too.

**What the user should verify:** Past runs are accurately preserved and browsable, letting them manually track outcomes over time.

**Completion/validation:** Acceptance criteria pass; user browses at least two distinct past runs and confirms fidelity.

---

## Slice 11 — Cost visibility and logging (FR13)

**Outcome:** Real per-stage cost (Haiku sweep, Haiku deep-dive aggregate, Sonnet compilation) is captured from the SDK's usage/cost reporting during Slices 7-8's real calls and persisted/displayed on each run record, purely for monitoring — never gating a run.

**User value:** The user can see what each run actually costs, broken out by stage, directly answering the spec's cost-visibility requirement and letting them sanity-check the Haiku/Sonnet split's real-world economics versus the spec's soft estimate.

**Scope:**
- Capture cost/usage data returned by the Claude Agent SDK for each real session call (sweep, each deep-dive, compilation); sum into `cost_sweep_usd`, `cost_deep_dive_usd`, `cost_compilation_usd`, `total_cost_usd` on the run record.
- Display per-stage cost on run detail (latest run) and history views.
- Explicitly verify no code path uses this figure to block, delay, or warn about a run, regardless of magnitude (a hard non-feature to confirm absent, mirroring the spec's explicit "never gates" requirement).
- **Explicit exclusions:** no budget/threshold UI of any kind (intentionally absent, per spec).

**Frontend/backend/API/data:**
- Orchestrator/session wrappers extended to surface per-call cost from SDK responses.
- `runs` table gains the four cost columns.
- Template updates for run detail/history cost display.

**Dependencies/prerequisites:** Slices 7-8 (real SDK calls must exist to have real cost data to capture) — the `FakeHaikuSession`/`FakeCompilationSession` should also return a stubbed cost figure so integration tests can assert cost-persistence logic without live calls.

**Acceptance criteria:**
- After any real run, the run record shows a logged `total_cost_usd` broken out into sweep/deep-dive/compilation components, summing correctly.
- No code path blocks, delays, or warns a run based on the cost figure's magnitude (verified by a test asserting a deliberately huge stubbed cost value still lets the run complete normally).
- Cost figures persist correctly and display on both the latest-run view and history view.

**Automated tests:**
- Unit/integration: fake sessions return stubbed per-call cost values; assert the orchestrator sums and persists them correctly into the four fields.
- Integration: a run with an artificially huge stubbed cost value completes without any blocking/warning behavior (negative test for the "never gates" requirement).

**Manual tests:** Trigger a real run; inspect the run detail/history view for per-stage cost figures; sanity-check the numbers look like real per-call costs (not zero, not obviously wrong).

**How to run/access:** Same flow; cost now visible on run detail/history.

**What the user should verify:** Real per-stage cost is visible and plausible, and nothing about the system reacts defensively to a high cost figure.

**Completion/validation:** Acceptance criteria pass; user reviews at least one real run's logged cost breakdown for plausibility.

---

## Slice 12 — Disclaimer hardening, retention-guarantee regression pass, and full spec cross-check

**Outcome:** A focused closing slice that re-verifies the cross-cutting hard constraints (FR8 retention, FR9 disclaimer, FR10 no-auto-execution, `127.0.0.1`-only binding) across the now-complete system, closing any gaps that individual earlier slices didn't fully cover, and running a full regression pass before independent validation (Stage 5).

**User value:** Confidence that the hard, non-negotiable constraints from the spec hold true across the whole, now-complete system — not just within the slice that originally introduced each piece.

**Scope:**
- Disclaimer: confirm it renders on every view that shows results (latest run, run detail, history detail) — not just the original Slice 0 view.
- Retention: a repo-wide test/grep-style check (encoded as an automated test, not just manual review) asserting no adapter, cache, or persistence path ever stores more than the retained fields — run against the full, final adapter set from Slice 2.
- No-auto-execution: confirm (via code review / grep, encoded as a lightweight automated check if feasible, e.g. asserting no brokerage-related import/module exists) that no code path can reach any order-placement/brokerage API.
- Access control: confirm the app only binds to `127.0.0.1` (test that attempting to bind `0.0.0.0` is not how `main.py` is configured — a simple assertion/test on the startup config).
- Full regression: re-run the entire automated test suite built across all prior slices together, and do one full manual end-to-end real run reviewing every acceptance criterion from the tech spec's §9 checklist.
- **Explicit exclusions:** no new product features — this is a verification/hardening slice, not new scope.

**Frontend/backend/API/data:** No new modules expected; this slice's "deliverable" is tests + a verification pass, possibly minor template fixes if disclaimer coverage gaps are found.

**Dependencies/prerequisites:** All prior slices (0-11) complete.

**Acceptance criteria:**
- Every view that renders results includes the disclaimer, verified across latest-run, run-detail, and history-detail views.
- A repo-wide retention test passes against the final adapter set.
- No brokerage-related code/imports/credentials exist anywhere in the codebase.
- The app's binding configuration is verified (by test or direct inspection) to never be `0.0.0.0`.
- Full automated test suite (all slices) passes together, not just individually.

**Automated tests:**
- A disclaimer-presence test per results-rendering template/route.
- The repo-wide retention test (final version, covering all adapters).
- A static/no-import check for brokerage-related modules (e.g., asserting no `kite`/brokerage-SDK import exists in the dependency tree or source).
- A config test asserting the FastAPI/uvicorn startup binds to `127.0.0.1`.
- Full regression run of the complete test suite.

**Manual tests:** One full, real end-to-end run reviewed against every bullet in tech-spec.md §9 ("Acceptance Criteria (per major feature)"), checked off item by item with the user.

**How to run/access:** Same app; this slice is primarily a verification pass rather than a new feature to click through, though the final regression run should be demoed live.

**What the user should verify:** Every hard constraint from the spec holds across the finished system, and the user has personally walked through the §9 acceptance checklist once end-to-end.

**Completion/validation:** All automated checks pass; the user has completed a guided walkthrough of tech-spec.md §9 against the real running app with no unresolved gaps — this slice's completion is effectively the readiness gate for Stage 5 (independent validation).

---

End of canonical vertical-slice plan.
