# Initial Implementation Plan — Local Swing-Trading Helper

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 1 (Initial Planning and User Alignment)
**Source:** `.sessions/swingtrade-20261011-130148/tech-spec.md` (locked — no requirement below reopens a spec decision; where the spec left something explicitly open to Workflow 2, this plan proposes a default)
**Architectural precedent:** sibling project `ai-job-finder-console` (`app/main.py`, `app/session_port.py`, `app/agent/claude_session.py`, `app/agent/claude_scoring.py`, `app/run_orchestrator.py`, `app/scoring_math.py`, `app/db.py`, `app/run_lock.py`, `app/routers/run.py`, `app/routers/settings.py`, `app/templates/index.html`, `pyproject.toml`)

---

## 1. Major capabilities implied by the spec

1. **Data collection layer** — four/five adapters (Moneycontrol RSS [+ optional secondary RSS], NSE Bhavcopy EOD CSV, Screener.in fundamentals, Trading Economics macro calendar), each normalizing to a shared, retention-safe shape (headline/source/date/URL/snippet — never full article body).
2. **Quick-sweep change detection (FR2)** — a cheap, pre-LLM hash/diff of the current raw sweep data against the immediately prior run's stored sweep snapshot; short-circuits the run (skips the deep-dive stage) when nothing material changed.
3. **Three-stage LLM pipeline (FR3-FR5)**, run fresh per invocation via the Claude Agent SDK:
   - Stage 1 — Haiku sweep (web search/fetch tools on) → shortlist of candidates.
   - Stage 2 — up to 10 sequential Haiku deep-dives (no web tools, reasoning over already-fetched content) → sub-scores + reasoning + citations + negative-filter flags per candidate.
   - Stage 3 — one Sonnet compilation/verdict call over all surviving candidates together → polished rationale + cross-candidate ranking commentary (read-only w.r.t. score/tier).
4. **Deterministic scoring module (FR6)** — pure application code, weighted formula (§6 of spec) turning Haiku sub-scores into a 0-100 score and red/yellow/green tier. No LLM ever computes or touches this.
5. **Negative filtering (within FR4)** — pump-and-dump indicators and stale/already-priced-in news checks, applied during/after the deep-dive stage, before scoring assembly.
6. **Output assembly (FR7)** — cap at 10, green>yellow>red ordering, yellow/green fill first, red backfill only when short and always distinctly labeled low-confidence, hard citation requirement.
7. **Persistence (FR8, FR13, §5)** — SQLite: run history (status, timestamps, quick-sweep short-circuit flag, per-stage cost), per-run ideas (with backfill/low-confidence flag), retained citation/snippet fields only, and whatever state the quick-sweep diff needs (hash or normalized snapshot of prior sweep).
8. **App shell (FR11)** — FastAPI + Jinja2 + static assets, bound to `127.0.0.1` only, SQLite-backed, startup reconciliation sweep (any `running` row from a crashed process → `error`), single in-memory run-lock, "Run now" background-task endpoint, progress streaming to the UI.
9. **UI** — latest-run ranked card list (ticker, entry/target/hold, tier badge, sub-scores, rationale, citation link(s), low-confidence label where applicable) + a history view of past runs + mandatory disclaimer rendered on every view that shows results.
10. **Cost visibility (FR13)** — per-stage (`sweep`, `deep_dive`, `compilation`) cost logged on the run record; purely observational, never gates a run.

## 2. User journeys

- **J1 — Trigger a run:** user opens the local UI, clicks "Run now," sees progress (sourcing → quick-sweep → sweep LLM → deep-dives → scoring → compilation), and lands on a ranked card list with disclaimer.
- **J2 — Cheap re-run:** user re-runs soon after; quick-sweep detects no material change; UI reports "prior output still current" without re-invoking the LLM stages.
- **J3 — Browse history:** user opens a history view, sees past runs (status, timestamp, cost, short-circuited-or-not), and can open any past run's idea list.
- **J4 — Reject a bad idea / understand reasoning:** user reads a card's rationale and citation(s) to judge whether to act on it manually (no execution path exists).

## 3. APIs / interfaces (high-level, not final contracts — Stage 3's job to pin down exactly)

- `POST /api/run` — acquire run-lock (409 if busy), run pipeline as background task, stream progress (SSE, mirroring the sibling project's pattern) ending in a `run_complete`/`run_error`/`run_skipped_no_change` event.
- `GET /api/run/status` — lock state.
- `GET /api/run/last` — latest run summary + its ideas (for page load/reload).
- `GET /api/run/{run_id}` or `/results` — a specific past run's ideas, for history browsing.
- `GET /` — index page (latest run + "Run now" button + history link).
- Ports (protocols, mirroring sibling's `ports.py`/`session_port.py`): `SourcingPort` (or one port per adapter plus an aggregator), `SweepLLMPort`/`DeepDiveLLMPort`/`CompilationLLMPort` (or one `SessionManager`-equivalent exposing model-scoped `ask`), `ScoringPort`-equivalent is just the deterministic module (no port needed — it's pure code, not swappable at runtime the way an LLM call is).

## 4. Data needs

- Normalized source record: `{source, headline, url, published_at, snippet}` — shared shape across all adapters, enforced at the adapter boundary (see Q3 below).
- Sweep snapshot (for quick-sweep diff): a hash or normalized list of the above records from the most recent run, keyed by run.
- Candidate/deep-dive record: ticker, catalyst sub-score + reasoning, sector-momentum sub-score + reasoning, macro sub-score + reasoning, negative-filter flags, citations, (Haiku) rationale draft.
- Deterministic score/tier: computed from the above, immutable once set.
- Idea record (final): ticker, entry, target, hold-duration-days, tier, sub-scores, Sonnet-polished rationale, citations, low-confidence/backfill flag, cross-candidate ranking commentary fragment.
- Run record: id, started_at, finished_at, status, quick_sweep_skipped (bool), cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd, total_cost_usd.

## 5. Integration points

- Claude Agent SDK (`claude_agent_sdk`), auth via existing `claude login` (no API key handling) — same as sibling project.
- Four/five external data sources over HTTP (RSS/CSV/HTML scraping) — no official APIs for most, so adapters need to tolerate source fragility (per spec §11 risk).
- SQLite file on local disk.
- No brokerage integration of any kind (hard exclusion, FR10).

---

## 6. Open technical decisions for Stage 1 user alignment

### Decision A — How one ephemeral run calls two models (Haiku then Sonnet)

**What I found in the sibling project:** `claude_session.py`'s `ClaudeSessionManager` wires `model` into `ClaudeAgentOptions` once, at client-construction time, inside `_default_client_factory()`. The model is fixed for the lifetime of that `ClaudeSDKClient`; there's no per-`query()` model override anywhere in that code, and the public SDK surface used there (`ClaudeSDKClient`, `ClaudeAgentOptions`, `connect()`/`disconnect()`, `query()`/`receive_response()`) doesn't expose switching models on a live connected client either. The sibling project only ever needed one model for its whole process lifetime, so this question never came up there — our spec is the first time one *run* needs two.

**Recommendation: two short-lived `ClaudeSDKClient`s, sequenced within one run — a Haiku client for the sweep + all deep-dives, then a separate Sonnet client for the single compilation call.** Not one client with a "per-call model override," because that capability doesn't actually exist on `ClaudeSDKClient`/`ClaudeAgentOptions` as used here — model is an options-level, connect-time setting. Trying to mutate it mid-session would mean disconnecting and reconnecting anyway, which is just the two-client approach with extra indirection.

Concretely: a `SweepSessionManager`/`HaikuSession` connects at run start, serves the sweep call and all up-to-10 deep-dive calls, then disconnects before the compilation step; a second `CompilationSession` (Sonnet) connects just for the one compilation call and disconnects immediately after. This also cleanly matches the spec's "ephemeral per run" framing (§5) — neither client needs to outlive the run, so there's no idle-timeout/run-count-reset policy to port over from the sibling's long-lived-session design.

**Why this over one client with a model override:** (1) it matches what the SDK actually supports today, verified against the sibling's own usage; (2) it keeps the two system prompts cleanly separate (sweep/deep-dive prompts are data-constrained and tool-enabled-for-sweep-only; the compilation prompt is a pure synthesis prompt with different tool settings — `tools=[]` likely for both, but worth confirming) rather than threading model-conditional prompt logic through one client; (3) failure isolation — a Haiku exchange error (FR's "Workflow 2 should define failure handling" risk) can be handled and the Haiku client discarded/reconnected without touching the Sonnet stage at all.

### Decision B — Project structure and dependency choices

**Recommendation: a lighter structure than the sibling's full ports/adapters/fakes/routers layout, but keep the same *separation philosophy*** — i.e., still have explicit seams (a scoring module with zero LLM dependency, a session/engine seam, adapters behind a shared interface) because the spec explicitly asks for these seams and the test strategy depends on them, but avoid replicating structure that exists in the sibling only because it is a multi-feature chat console (e.g., `chat.py` router, `resume_store.py`, `dedup.py`'s cross-run matching, settings-profile CRUD, auth/token-mint layer — all explicitly out of scope here per spec §5's "no app-token minting").

Proposed lighter layout:
```
app/
  main.py                 # FastAPI app, lifespan reconciliation, binds 127.0.0.1 only
  db.py                    # schema + connection (mirrors sibling's db.py)
  run_lock.py              # same as sibling's run_lock.py, copied near-verbatim
  run_orchestrator.py      # the 9-step pipeline from spec §5
  scoring.py               # deterministic scoring (spec §6) — pure, no LLM import
  quick_sweep.py           # hash/diff change-detection (FR2)
  negative_filters.py      # pump-and-dump + stale-news checks (FR4)
  sources/
    moneycontrol_rss.py
    secondary_rss.py        # optional
    nse_bhavcopy.py
    screener_in.py
    trading_economics.py
    base.py                 # shared normalized record type + adapter protocol
  agent/
    sessions.py             # Haiku + Sonnet session wrappers (Decision A)
    prompts.py              # sweep / deep-dive / compilation prompt templates
    sweep.py / deep_dive.py / compilation.py   # per-stage LLM call + parsing
  routers/
    run.py
  templates/
    index.html, history.html (or one template with a view toggle)
  static/
fakes/
  fake_sources.py
  fake_sessions.py          # fakes for both Haiku and Sonnet stages
tests/
```
No `ports.py`-as-Protocol-zoo unless Stage 3 finds real value in it; a few small `Protocol`s where swapping real/fake matters (sources, the two session wrappers) is enough. No auth module, no settings-profile CRUD, no chat/direction concept — none of that is in this spec.

**Dependencies (mirroring the sibling's stack where it overlaps):** `fastapi`, `uvicorn[standard]`, `jinja2`, `pydantic`, `httpx` (HTTP fetch for RSS/CSV/HTML sources), `claude-agent-sdk` (same pinned-pattern version approach), `pytest`. Likely additions the sibling doesn't need: an RSS parser (`feedparser` or hand-rolled XML parsing via stdlib `xml.etree`) and an HTML parser for Screener.in (`beautifulsoup4` or `selectolax`/`lxml`). No `PyMuPDF`/`python-docx`/`rapidfuzz`/`python-multipart` — those were resume-upload/dedup-specific to the job-finder tool and have no equivalent need here.

### Decision C — Data-source adapter boundaries

Confirmed: this matches spec §5's "Data-source adapters: one adapter per source... normalizing into the retained fields" bullet.

**Proposed shared interface (shape only):**
```
NormalizedItem:
    source: str            # "moneycontrol_rss" | "nse_bhavcopy" | "screener_in" | "trading_economics" | ...
    headline: str           # or a source-appropriate short label for non-news sources (e.g. "NSE Bhavcopy — 2026-10-11")
    url: str
    published_at: datetime (or date)
    snippet: str            # 1-2 sentences max, enforced at construction time (hard truncation or validation error)
    ticker: str | None      # when the source can associate the item with a specific symbol (Bhavcopy, Screener always can; RSS sometimes can't until the sweep stage maps headline->ticker)

SourceAdapter (Protocol):
    name: str
    async def fetch(self) -> list[NormalizedItem]
```
Each adapter is solely responsible for fetching + normalizing into `NormalizedItem` and must physically have no code path that stores/returns full article body text (testable per spec §10's retention unit test). Bhavcopy's "item" is more like an OHLC/volume row than a news item — it may need a slightly different concrete type or an adapter-specific extension field (e.g., `volume`, `close`, `prev_close`) alongside the shared base fields, since it feeds the negative-filter (volume) and scoring context rather than being "news." Recommend keeping one shared base shape for the retention guarantee and quick-sweep hashing, with adapter-specific optional fields layered on top rather than forcing Bhavcopy into a pure headline/snippet shape it doesn't fit.

### Decision D — Testing strategy for the two LLM stages/models

**Recommendation: mirror the sibling's fakes pattern — one fake per session wrapper, both satisfying the same minimal protocol the real Haiku/Sonnet wrappers satisfy**, analogous to `FakeSessionManager`/`FakeScoringPort`:
- `FakeHaikuSession` — takes canned sweep output (shortlist) and canned per-candidate deep-dive output (sub-scores + reasoning + citations), keyed by ticker, with the same "map lookup → raise a stage-specific error for this one input" trick `FakeScoringPort` uses for `ScoringError`. Records calls (`self.calls`) for assertion, exactly like the sibling's fakes.
- `FakeCompilationSession` — takes canned per-run compilation output (rationale text + ranking commentary) and asserts (via a recorded call count) that it is invoked exactly once per run, never once per candidate — this directly covers the FR5/AC "exactly one Sonnet call per run" requirement from the spec.
- The orchestrator depends only on the two session wrappers' protocols (never on `ClaudeSDKClient` directly), exactly as the sibling's `RunOrchestrator` depends only on `SourcingPort`/`ScoringPort`/`SessionManager` — this is what makes the full pipeline integration test (spec §10's "stubbed multi-model LLM session" test) possible without any real network/LLM calls.
- Deterministic scoring (`scoring.py`) stays pure and gets plain unit tests with no fakes needed at all, same as `scoring_math.py`'s tests in the sibling.
- Source adapters get fixture-based tests (canned RSS/HTML/CSV bytes → expected `NormalizedItem`s) plus a `FakeSourcingAggregator` for orchestrator-level tests, mirroring `fake_sourcing.py`.

---

## 7. Anticipated challenges (flagged, not solved here)

- Source fragility (Screener.in HTML structure, RSS feed URLs, Bhavcopy file-naming/format) — adapters will need resilience/retry and will break over time; out of scope to fully solve now.
- Exact failure-handling semantics when a Haiku deep-dive call errors mid-run (continue vs. abort; per-stock skip vs. whole-run failure) — spec explicitly leaves this to Workflow 2 (§11); needs a decision before Stage 3.
- Exact pump-and-dump/stale-news thresholds (volume cutoffs, institutional-ownership signal, "already priced in" cross-check mechanics against NSE announcement dates) — spec explicitly leaves this to Workflow 2 (§11); needs a decision before Stage 3.
- Quick-sweep "materiality" threshold — what counts as "nothing material changed" (exact hash scope, new NSE announcement, headline count delta?) — needs a concrete definition before Stage 3.
- SSE vs. polling for progress — spec says SSE is "a reasonable precedent, though exact transport is a Workflow 2 decision."

---

## Critical files for implementation (sibling precedent, for reference during Stage 2/3 planning)

- /Users/abheet/Desktop/Personal projects/ai-job-finder-console/app/agent/claude_session.py
- /Users/abheet/Desktop/Personal projects/ai-job-finder-console/app/run_orchestrator.py
- /Users/abheet/Desktop/Personal projects/ai-job-finder-console/app/scoring_math.py
- /Users/abheet/Desktop/Personal projects/ai-job-finder-console/app/fakes/fake_session.py
- /Users/abheet/Desktop/Personal projects/ai-job-finder-console/app/main.py
