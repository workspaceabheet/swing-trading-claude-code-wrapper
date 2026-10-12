# Technical Specification: Local Swing-Trading Helper for NSE/BSE Equities

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 1, Stage 4 (Technical Specification)
**Status:** Draft for user review — the four previously-open decisions (red-tier backfill policy, cost control via model split, local-auth/origin-pinning, feedback-loop scope) have been resolved per user direction; see §11 for resolution notes. Other research-identified risks (rubric validation, source fragility, etc.) remain and are not decisions pending the user.

---

## 1. Problem Statement and Goals

The user manually scans Indian equity (NSE/BSE) news, fundamentals, and macro context to find short-horizon (days-to-two-weeks) swing-trade candidates. This is time-consuming, inconsistent, and vulnerable to noisy "tip" chatter and stale/already-priced-in news.

**Goal:** A local, single-user tool that runs an automated three-stage pipeline — research sweep, per-stock deep-dive, and a final compilation/verdict pass — over free, legitimate Indian market data sources and surfaces at most 10 ranked, cited, swing-trade ideas per run, each with an entry/target/hold-duration estimate and a deterministic confidence tier — without ever placing a trade or requiring any paid API.

**Non-goals:** This is not a trade-execution system, not a backtested quant strategy, not a registered-adviser product, and not a multi-user service.

---

## 2. Target Users and Use Cases

**Target user:** The project owner only — a single, local, non-commercial user running the tool on their own machine for personal research.

**Primary use cases:**
1. Trigger a fresh research run and review a ranked list of up to 10 swing-trade ideas with rationale and citations.
2. Re-run later the same day/week and get a fast "nothing material changed" response instead of paying for a full re-analysis when the news picture is unchanged.
3. Browse past runs to see what was suggested previously and compare against what happened since (manually — no automated feedback loop in v1).

---

## 3. Scope and Out-of-Scope

### In scope (v1)
- Automated data collection from: Moneycontrol RSS (+ optionally one more RSS feed), NSE Bhavcopy (EOD OHLC/volume CSV), Screener.in (fundamentals), Trading Economics (macro calendar).
- A three-stage LLM pipeline using the Claude Agent SDK, run fresh per invocation: (1) a Haiku broad sweep, (2) up to 10 Haiku per-stock deep-dives, and (3) one Sonnet compilation/verdict pass that synthesizes the final written rationale and cross-candidate ranking commentary from all the deep-dive outputs together. Cost control is achieved via this model split (cheap Haiku for data-gathering/sub-scoring, Sonnet only for the single final synthesis call), not via a hard dollar cost cap — there is no budget ceiling that aborts a run, but actual per-run cost is logged per stage.
- Deterministic scoring (weighted formula applied in application code, not by the LLM) producing a red/yellow/green tier per idea.
- Pump-and-dump and stale-news negative filtering during the deep-dive stage.
- A capped, cited, disclaimed output of at most 10 ranked ideas per run.
- A cheap "quick sweep" change-detection check that skips the expensive deep-dive stage when nothing material has changed since the prior run.
- A local FastAPI + Jinja2 + SQLite app shell (mirroring the sibling `ai-job-finder-console` project's pattern) for triggering runs and browsing run history.
- Headline/source/date/URL/snippet-only data retention (never full article bodies).
- A visible, mandatory disclaimer on every run's output.

### Out of scope (v1)
- Any automated interaction with Zerodha Kite (API or scraping) in any form. Manual, one-off CSV export from Kite Console remains an acceptable non-automated input if the user wants portfolio context later, but nothing is built against it.
- Any paid data/API subscriptions.
- Trade execution, order placement, modification, or cancellation of any kind.
- Backtesting or a feedback-validation loop comparing predictions to actual subsequent price action (noted as a future direction only).
- Multi-user support, remote/non-localhost access, or any authentication beyond what a single local user needs.
- Live/intraday pricing (the tool is a once-daily-or-so advisory tool using EOD data; Upstox's free API is a plausible future addition if live reference pricing ever becomes necessary, not a v1 requirement).
- SEBI Research Analyst / Investment Adviser registration or compliance workflow (not required for a non-distributed personal tool, per research; this is not legal advice).

---

## 4. Functional Requirements

### FR1 — Data collection
The system shall fetch, on each run, current data from: Moneycontrol RSS (+ optional secondary RSS feed), NSE Bhavcopy EOD CSV, Screener.in fundamentals pages for candidate tickers, and Trading Economics' macro calendar. Google News RSS is explicitly excluded as a source (ToS risk). Social media, Telegram, and YouTube "tip" content are explicitly excluded as inputs at every stage.

### FR2 — Quick-sweep change detection
Before invoking any LLM stage, the system shall perform a cheap, programmatic comparison (e.g., hash/diff) of the current sweep's raw results against the immediately prior run's sweep results. If nothing material has changed, the system shall skip the deep-dive LLM stage entirely and report that the prior run's output is still current, rather than re-running full analysis.

### FR3 — Sweep stage (LLM, stage 1, Haiku)
When the quick-sweep indicates material change, the system shall run one Haiku LLM sweep stage (with web search/fetch tools enabled) that reviews the collected data and narrows the universe down to a shortlist of candidate stocks worth a deep-dive (shortlist size bounded — exact bound is a Workflow 2 tuning decision, but must be enough to comfortably produce up to 10 final ideas after filtering). Haiku is used here for cost control; see §5 and §7.

### FR4 — Deep-dive stage (LLM, stage 2, Haiku)
For each shortlisted candidate (up to 10 final ideas), the system shall run a Haiku deep-dive LLM call (no web tools — reasoning over already-fetched content only) that:
- Scores catalyst strength, sector momentum, and macro context as independent sub-scores with written reasoning (the LLM never outputs the final tier itself).
- Applies the negative filters: pump-and-dump indicators (low daily volume, no institutional ownership, sudden promotional-style chatter) and stale/already-priced-in news (cross-checked against NSE announcement dates).
- Produces a written rationale naming the specific catalyst and at least one citation (source name, URL, headline, date).

### FR5 — Compilation/verdict stage (LLM, stage 3, Sonnet)
After deterministic scoring (FR6) and negative filtering have run over all surviving deep-dive candidates, the system shall run a single Sonnet compilation/verdict LLM call that takes as input the deterministic scores/tiers and all candidates' Haiku sub-scores and reasoning together, and produces:
- Polished, cross-referenced final written rationale text per idea (building on, not replacing, the Haiku deep-dive rationale).
- Cross-candidate ranking rationale/commentary explaining the relative ordering of the final list.
This stage is strictly a synthesis/writing pass. Sonnet never computes, overrides, or re-derives the 0-100 score or the red/yellow/green tier — those remain fixed by the deterministic formula in §6 applied in application code (FR6). Sonnet reads the already-final scores and tiers and writes narrative/ranking text around them.

### FR6 — Deterministic scoring
Application code (not any LLM — neither Haiku nor Sonnet) shall compute the final 0-100 score from the Haiku deep-dive sub-scores using the weighted formula in §6, and assign the red/yellow/green tier from the fixed thresholds in §6. No LLM's role extends to producing or altering the final tier; Haiku's role ends at producing sub-scores and reasoning, and Sonnet's role (FR5) is limited to writing narrative/ranking text over the already-computed tier.

### FR7 — Output assembly
The system shall assemble at most 10 ranked ideas per run, ordered best-to-worst (green before yellow before red). The list shall be filled with yellow- and green-tier ideas first. Only if fewer than 10 yellow/green ideas are available shall red-tier (score <50) ideas be used to backfill the list up to 10; any backfilled red-tier idea shall be clearly and distinctly labeled as low-confidence in the output, never presented identically to a yellow/green idea. Every idea shall include: ticker, buy price (entry reference), target price, hold-duration estimate (days), tier (red/yellow/green) with sub-scores, written rationale naming the specific catalyst (per FR4/FR5), and at least one citation. An idea with no citation shall never appear in output (hard constraint, not configurable).

### FR8 — Data retention
The system shall never persist full scraped article body text, in either the raw sweep cache or final run output. Only headline, source name, publish date, URL, and a short (~1-2 sentence) snippet shall be stored.

### FR9 — Disclaimer
Every run's output shall carry a visible disclaimer: personal informational use only, not investment advice, not a registered adviser, no trades are placed automatically.

### FR10 — No auto-execution
The system shall never place, modify, or cancel any brokerage order, automatically or otherwise. It only ever displays suggestions.

### FR11 — Local app shell
The system shall expose a local FastAPI + Jinja2 + static-asset web UI, bound to `127.0.0.1` only (never `0.0.0.0`) as the sole access-control measure — no local-auth/token-mint/Origin-pinning layer is included in v1 (decided; see §5), backed by SQLite for run history and results persistence. A "Run now" action triggers a new pipeline run as a background task; overlapping runs shall be prevented (mirroring the sibling project's single in-memory run-lock pattern). The UI shall display the most recent run's ranked card list and allow browsing past runs' history.

### FR12 — Re-run safety
Running the pipeline again shortly after a prior run shall be cheap by default (FR2) and shall never silently duplicate LLM spend when the underlying news picture hasn't materially moved.

### FR13 — Cost visibility
The system shall log actual per-run cost (e.g., `total_cost_usd`) broken out per stage — Haiku sweep, Haiku deep-dive (aggregate or per-candidate), and Sonnet compilation — mirroring the sibling job-finder project's cost-tracking approach. This is for visibility/monitoring only; no dollar threshold is enforced and no run is blocked, warned, or aborted on cost grounds.

---

## 5. High-Level Architecture

The architecture mirrors the established `ai-job-finder-console` pattern, adapted for a single ephemeral pipeline run rather than a long-lived conversational session:

- **App shell:** FastAPI app (`main.py`-equivalent) with Jinja2 templates + static assets, bound to `127.0.0.1`. Lifespan hook reconciles any run left `running` from a prior crashed process to `error`, matching the sibling project's startup reconciliation sweep. (No app-token minting — see Auth/origin-pinning below.)
- **Run endpoint + background task:** A "Run now" HTTP endpoint acquires a single in-memory run-lock (409 if already in progress), then runs the pipeline as a background task, streaming progress events to the UI (the sibling project's SSE pattern is a reasonable precedent, though exact transport is a Workflow 2 decision).
- **Pipeline orchestrator:** A single orchestrator coordinates, per run: (1) data collection from the four/five sources, (2) quick-sweep change detection against the prior run, (3) conditionally the Haiku sweep LLM stage, (4) up to 10 sequential Haiku deep-dive LLM stages, (5) deterministic scoring, (6) negative filtering, (7) one Sonnet compilation/verdict LLM stage over all surviving candidates together (final rationale text + cross-candidate ranking commentary — not re-scoring), (8) persistence (including per-stage cost), (9) disclaimer attachment.
- **Session/engine seam:** A `SessionManager`-equivalent protocol wraps the Claude Agent SDK client, analogous to the sibling project's `session_port.py`/`claude_session.py`, but **ephemeral per run** rather than long-lived: one ephemeral run now needs to make calls against two different models — Haiku for the sweep and all deep-dive stages, Sonnet for the single compilation stage — within the same run. Whether that is implemented as one `ClaudeSDKClient` with a per-call model override, or two short-lived clients (one per model) sequenced within one ephemeral run, is **not decided by this spec** and is left to Workflow 2 to design and implement. Either way, the session is connected at the start of a run and disconnected at the end; no idle-timeout or run-count reset policy is needed (no cross-run session state to keep alive), unlike the job-finder project's continuous-server session.
- **Scoring seam:** A deterministic scoring module (analogous to `scoring_math.py`) takes Haiku-returned sub-scores as input and is the only code path that produces the final tier — never any LLM (Haiku or Sonnet) directly. This mirrors the job-finder project's separation where the LLM scores 0-4 sub-criteria and app code computes the weighted final score. The downstream Sonnet compilation stage (FR5) consumes this already-final score/tier as a read-only input to its narrative/ranking output; it has no path to change it.
- **Persistence:** SQLite, via a schema covering run history (including per-stage cost, e.g. `total_cost_usd` for sweep/deep-dive/compilation), per-run results (ideas, including a low-confidence/backfill flag for any red-tier idea included to fill out the list), and the retained-only citation/snippet fields (never full article text), plus whatever state the quick-sweep comparison needs (e.g., a hash or normalized snapshot of the prior sweep). Exact schema is Workflow 2's job.
- **Data-source adapters:** One adapter per source (Moneycontrol RSS, NSE Bhavcopy, Screener.in, Trading Economics, optional secondary RSS), each responsible only for fetching and normalizing into the retained fields — never for persisting full article bodies.
- **Auth/origin-pinning:** Decided (no longer open): v1 does **not** include the job-finder-style token-mint-on-start + Origin/Host check layer. Binding to `127.0.0.1` only is the sole access-control measure for this tool. This was previously flagged as an open question in §11; it is now resolved and the local-auth layer is explicitly out of scope for v1.

---

## 6. Scoring Rubric (v1 draft — explicitly tunable)

Weighted 0-100 composite:
- **Catalyst strength — 40%:** scored 0-40 across weak/moderate/major bands.
- **Sector momentum — 35%:** scored 0-35 based on recent trend.
- **Macro risk modifier — 25%:** scored 0-25 (green macro = 25, yellow = 20, red = 15).

Thresholds:
- **Green: 70-100** — initiate, hold ~1-2 weeks.
- **Yellow: 50-69** — smaller size / tighter stop, ~5-7 day hold.
- **Red: <50** — avoid as a primary recommendation. Red-tier ideas are excluded from the top-10 list by default. **Decided (no longer open):** if fewer than 10 yellow/green ideas are found in a run, red-tier ideas may backfill the list up to 10, ordered after all yellow/green ideas (final list is always best-to-worst: green > yellow > red), and each backfilled red idea must be clearly and distinctly labeled as low-confidence in the output (see FR7).

This rubric is a draft to validate against real pipeline output, not a locked formula — Workflow 2 and early real runs may adjust the band boundaries or weights.

---

## 7. Constraints, Dependencies, and Assumptions

**Constraints (hard, non-configurable):**
- Maximum 10 ideas per run.
- Mandatory citation per idea (no idea without one may appear in output).
- No auto-execution of trades under any circumstance.
- Mandatory disclaimer on every run's output.
- Never persist full article body text — headline/source/date/URL/snippet only.
- App binds to `127.0.0.1` only, never `0.0.0.0`.
- No Zerodha Kite automation in any form.
- No paid APIs/data sources in v1.

**Dependencies:**
- Claude Agent SDK (`claude_agent_sdk` Python package), authenticated via existing `claude login` — no API key management.
- Free access to Moneycontrol RSS, NSE Bhavcopy, Screener.in, Trading Economics (subject to each site's current availability/ToS at build time — not independently re-verified by this spec).
- Local Python/FastAPI/SQLite stack, consistent with the sibling `ai-job-finder-console` project's toolchain.

**Assumptions:**
- Single user, single machine, no concurrent remote access ever required.
- Daily-or-less-frequent run cadence (not a real-time/intraday tool).
- The user accepts that free-source scraping (where not via official RSS/Bhavcopy) carries low-but-nonzero ToS enforcement risk, as flagged by research, and chooses to proceed anyway.
- There is no hard dollar cost cap and no run is ever blocked, warned, or aborted on cost grounds. Cost control is instead achieved via model selection: Haiku for the sweep stage and all per-stock deep-dive stages, Sonnet for the single final compilation/verdict stage. Actual per-run cost shall be logged per stage (FR13) for monitoring. The rough $2-10/day order-of-magnitude estimate from research assumed an all-Sonnet pipeline and should be re-validated against real logged costs once the Haiku+Sonnet split is built; it is expected to be materially lower under this split, but that is not yet confirmed.

---

## 8. Expected Outputs and Deliverables

Per run, the system produces:
1. A persisted run record (status, timestamps, whether quick-sweep short-circuited the run, per-stage cost in USD for the sweep/deep-dive/compilation stages).
2. Up to 10 ranked ideas, ordered best-to-worst (green > yellow > red), each with: ticker, buy price, target price, hold-duration (days), red/yellow/green tier with sub-scores, written rationale citing the specific catalyst (Sonnet-compiled, built on the Haiku deep-dive reasoning), and ≥1 citation (headline/source/date/URL/snippet only). Yellow/green ideas fill the list first; any red-tier idea present is there only as a backfill (used when fewer than 10 yellow/green ideas exist) and is clearly labeled low-confidence.
3. A visible disclaimer attached to the output.
4. A UI view of the latest run as a ranked card list, plus a history view of past runs.

---

## 9. Acceptance Criteria (per major feature)

**Data collection (FR1):** Given a run, the system fetches from all configured sources and normalizes results into headline/source/date/URL/snippet form, with zero full-article-body fields persisted anywhere, including the raw sweep cache.

**Quick-sweep skip (FR2, FR12):** Given a second run shortly after a first run where the underlying news picture is materially unchanged, the system detects this via the hash/compare mechanism and completes without invoking the deep-dive LLM stage, visibly reporting to the user that the prior output still stands.

**Sweep + deep-dive separation (FR3, FR4):** Given a run that proceeds past the quick-sweep check, the Haiku sweep stage runs with web tools enabled and narrows to a shortlist; each Haiku deep-dive stage runs without web tools, over already-fetched content only, and returns sub-scores + reasoning + citation(s) — never a final tier.

**Deterministic scoring (FR6):** Given any set of Haiku-returned sub-scores, the final tier is always reproducible by re-applying the documented formula and thresholds in application code alone, independent of any further LLM call (Haiku or Sonnet). The Sonnet compilation stage never changes this tier — given the same deterministic inputs, the tier is identical whether or not the compilation stage has run.

**Compilation/verdict stage (FR5):** Given a set of surviving candidates with deterministic scores/tiers and Haiku sub-scores/reasoning, the system invokes exactly one Sonnet call per run (not per candidate) covering all candidates together, and the resulting output contains cross-candidate ranking commentary and polished per-idea rationale text, while every idea's numeric score and tier remain byte-for-byte identical to the pre-compilation deterministic output.

**Output cap, ordering, and citation (FR7):** No run ever returns more than 10 ideas; ideas are ordered best-to-worst (green before yellow before red); yellow/green ideas are used to fill the list before any red-tier idea is added; red-tier ideas appear only as a backfill when fewer than 10 yellow/green ideas exist, and every such backfilled idea is visibly and distinctly labeled low-confidence (not rendered identically to a yellow/green idea); every returned idea has at least one citation; an idea that fails to produce a valid citation is dropped before output, not shown without one.

**Retention (FR8):** Inspecting the SQLite database and any on-disk cache after a run shows only headline/source/date/URL/snippet fields for every article referenced — no full article text anywhere.

**Disclaimer (FR9):** Every run's output (UI and any other presentation) visibly includes the required disclaimer text.

**No auto-execution (FR10):** The codebase contains no code path capable of placing, modifying, or cancelling a brokerage order; the system has no brokerage credentials or order-placement integration at all.

**App shell and access control (FR11):** The app is only reachable at `127.0.0.1` (never `0.0.0.0`); no token-mint or Origin/Host-check layer is present or required (decided out of scope for v1 — `127.0.0.1`-only binding is the sole access control and is itself the thing under test here); attempting to start a second run while one is in progress is rejected (e.g., HTTP 409) rather than allowed to run concurrently; the UI correctly displays the latest run and historical runs after a restart (state survives in SQLite, not in memory).

**Cost visibility (FR13):** After any run, inspecting the run record shows a logged `total_cost_usd`-style figure broken out by stage (Haiku sweep, Haiku deep-dive, Sonnet compilation); no run is blocked, delayed, or aborted due to cost regardless of how high the logged figure is.

**Negative filtering (within FR4):** Given a candidate exhibiting pump-and-dump indicators (low volume, no institutional ownership, promotional-style chatter) or news that cross-checks as already priced in against NSE announcement dates, the deep-dive stage flags/excludes it rather than surfacing it uncritically.

---

## 10. Test Expectations

- **Unit-level:** Deterministic scoring formula (sub-score inputs → correct final score and correct tier assignment at each threshold boundary) must be fully unit-testable without any LLM call, mirroring the sibling project's `scoring_math.py` test approach.
- **Unit-level:** Data-retention guarantee — tests should assert that no adapter or cache-write path ever stores a field containing full article body text.
- **Unit-level:** Output-cap and citation-requirement enforcement — tests should assert that assembly logic drops any idea lacking a citation and never emits more than 10 ideas regardless of how many deep-dives were run.
- **Unit-level:** Red-tier backfill policy — given a candidate pool with 10+ yellow/green ideas, assert zero red-tier ideas appear in output; given fewer than 10 yellow/green ideas, assert red-tier ideas backfill the list up to 10 (or fewer, if the combined pool is smaller), are ordered after all yellow/green ideas, and are each flagged/labeled as low-confidence in the assembled output's data (not just incidentally renderable as such).
- **Integration-level:** Quick-sweep change detection — given two sweep snapshots that are identical (or near-identical within a defined materiality threshold), the pipeline must skip the deep-dive stage; given snapshots that differ materially, it must proceed.
- **Integration-level:** Compilation/verdict stage — given stubbed deterministic scores/tiers and Haiku sub-score/reasoning fixtures for multiple candidates, assert the stubbed Sonnet call is invoked exactly once per run (not once per candidate) and that the scores/tiers in the final persisted output exactly match the pre-compilation deterministic values (Sonnet's stubbed output can only affect rationale/ranking-commentary text fields, never the score/tier fields).
- **Integration-level:** Cost logging — given a stubbed multi-model session run, assert a per-stage cost figure (sweep/deep-dive/compilation) is persisted on the run record, and assert no code path aborts, blocks, or warns the user based on the magnitude of that figure.
- **Integration-level:** End-to-end pipeline run against fixture/stubbed data sources and a stubbed multi-model LLM session (same pattern as the sibling project's fake `SessionManager`/`ScoringPort`, extended to stub both the Haiku and Sonnet calls within one run), verifying the full run completes, persists correctly, and respects all hard constraints (cap, ordering/backfill labeling, citations, disclaimer, no-auto-execution).
- **Manual/exploratory:** Real-run validation of the scoring rubric's thresholds against actual LLM output quality, since the rubric is explicitly a draft to be tuned post-build.
- **Security/scope:** Verify the app never binds to `0.0.0.0`, that no code path can reach a brokerage execution API, and that no token-mint/Origin-pinning code path exists (decided out of scope for v1) — `127.0.0.1`-only binding is the full extent of access control under test.

---

## 11. Risks, Open Questions, and Unresolved Decisions

**Previously-open questions — now resolved:**
1. ~~Whether "red" (low-confidence) ideas should ever appear in the top-10 output at all.~~ **Resolved:** the top-10 list is filled with yellow/green ideas first; red-tier ideas backfill the list only when fewer than 10 yellow/green ideas exist, are ranked after all yellow/green ideas, and are clearly labeled low-confidence when included. See §4 (FR7), §6, §9.
2. ~~Exact run_count/model-cost budget alarms.~~ **Resolved:** there is no hard dollar cost cap and no run is ever blocked or warned on cost grounds. Cost control is instead achieved through model selection — Haiku for the sweep and deep-dive stages, Sonnet for a single compilation/verdict stage — and actual per-run cost is logged per stage for visibility only. See §4 (FR3-FR5, FR13), §5, §7, §9.
3. ~~Whether a lightweight local-auth/origin-pinning layer is necessary.~~ **Resolved:** it is explicitly skipped for v1. `127.0.0.1`-only binding is the sole access-control measure. See §4 (FR11), §5, §9, §10.
4. **Feedback-validation loop** (comparing predictions to actual subsequent price action) — this was never genuinely open; it remains explicitly out of scope for v1 and noted purely as a future direction (see §3, "Out of scope").

**Other risks identified from research:**
- **Token-cost estimates are soft.** Research's ~$2-4/day (Sonnet) to ~$6-10/day (Opus) figures assumed an all-Sonnet pipeline and are now superseded by the decided Haiku (sweep + deep-dive) / Sonnet (compilation only) model split, which is expected to materially reduce real cost — but this has not yet been measured against real traffic. Actual per-stage cost should be monitored via the FR13 logging once built, and the estimate above should be revisited once real numbers exist.
- **ToS exposure for scraped sources remains real, if low-enforcement-risk**, for anything beyond official RSS/Bhavcopy channels; this should be revisited if run frequency ever increases beyond the assumed daily-or-less cadence.
- **Scoring rubric is unvalidated** against real market outcomes — no backtesting exists yet, and the weights/thresholds in §6 are a draft pending real-run review.
- **Pump-and-dump / stale-news filtering logic is not yet concretely designed** beyond the qualitative description in FR4 — exact volume/institutional-ownership thresholds and the stale-news cross-check mechanics are Workflow 2's job to specify precisely.
- **Source fragility:** free sources (RSS feeds, Screener.in page structure, NSE Bhavcopy URL/format) can change without notice; no SLA exists for any of them. The system should be expected to need periodic adapter maintenance.
- **Single point of engine failure:** since the Haiku deep-dive stages run sequentially within one ephemeral run (and the Sonnet compilation stage then runs once over all of their outputs together), a mid-run exchange failure (timeout, error result) at either the Haiku or Sonnet layer needs a defined failure-handling behavior (continue vs. abort the run; per-stock skip vs. whole-run failure) — not fully specified here; Workflow 2 should define this explicitly, analogous to the sibling project's per-posting `ScoringError` handling, and should also decide the exact mechanism for running two models within one ephemeral session (see §5).

---

*This document is produced at the requirements/high-level-design level per Workflow 1 Stage 4. Code-level design — file structure, exact schemas, exact prompts, exact adapter implementations — is Workflow 2's responsibility.*
