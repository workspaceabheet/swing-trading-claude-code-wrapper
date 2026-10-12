# Slice 4 — Detailed Technical Plan: Haiku Sweep + Deep-Dive Against `FakeHaikuSession`

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 4 only
**Inputs (locked, not reopened):** `tech-spec.md` (FR3, FR4, FR6, §5, §6, §11), `initial-plan.md` (Decision A — two sequenced ephemeral `ClaudeSDKClient`s; Decision C — `NormalizedItem`), `vertical-slice-plan.md` Slice 4 section (lines 217-254), `plan-detailed/slice-0.md` (schema/layout/conventions)
**Precedent repo:** `ai-job-finder-console` — `app/session_port.py` (Protocol-in-a-port-module pattern), `app/agent/claude_session.py` (real session, not built this slice — informs the Protocol shape only), `app/agent/claude_scoring.py` (prompt/parse separation, per-item try/except), `app/fakes/fake_session.py` + `app/fakes/fake_scoring.py` (call recording + canned-map-with-exception-sentinel pattern), `app/ports.py` (`SubScores`, `ScoringError` shape), `app/run_orchestrator.py` (per-item try/except skip-and-continue loop structure).

**What this slice explicitly does NOT do (per locked vertical-slice-plan boundaries):**
- No real `ClaudeSDKClient` anywhere (Slice 7). `HaikuSession` here has exactly one implementation in this slice: `FakeHaikuSession`.
- No deterministic scoring formula (Slice 5) — sub-scores are persisted and displayed as raw Haiku-sub-score output; no 0-100 score or red/yellow/green tier is computed yet (`ideas.score`/`tier` stay whatever Slice 0 left them — a placeholder tier string is used only so the existing card template doesn't break; see §7).
- No negative filtering (Slice 6).
- No Sonnet compilation (Slice 8).
- No output cap/ordering/backfill (Slice 9) — every surviving candidate is shown, in shortlist order.

---

## 1. Files to create

| Path | Responsibility |
|---|---|
| `app/agent/__init__.py` | Empty, package marker. |
| `app/agent/sessions.py` | `HaikuSession` Protocol + the frozen dataclasses it speaks in (`ShortlistCandidate`, `DeepDiveResult`, `DeepDiveContext`). Mirrors `session_port.py`'s "protocol in a port module" separation — zero LLM/SDK import here, so it is importable by both the fake and (in Slice 7) the real implementation without circularity. |
| `app/agent/sweep.py` | `run_sweep_stage(session, items) -> list[ShortlistCandidate]`: calls `session.run_sweep(items)`, enforces the shortlist-size bound (truncates to `MAX_SHORTLIST_SIZE`, logs a warning if the session returned more), returns the bounded list. No parsing logic needed yet since the fake already returns typed objects — this module becomes the natural home for real-response JSON parsing in Slice 7, kept separate now so Slice 7 only touches this file, not the orchestrator. |
| `app/agent/deep_dive.py` | `run_deep_dive_stage(session, shortlist, context_by_ticker) -> list[DeepDiveResult]`: loops the shortlist, calls `session.run_deep_dive(ticker, context)` per candidate inside a per-ticker `try/except`, logs+skips failures, returns the list of successes. This is the module the orchestrator calls — it owns the skip-and-continue policy so the orchestrator itself stays thin (consistent with the sibling's `score_posting` being called from inside `run_orchestrator.py`'s loop, but here the loop+try/except is factored one level down since both sweep and deep-dive share the "call the session, handle failure" shape and Slice 7 will want to unit-test this loop against the fake without the whole orchestrator). |
| `app/fakes/__init__.py` | Empty, package marker. |
| `app/fakes/fake_sessions.py` | `FakeHaikuSession` — canned sweep shortlist, canned per-ticker deep-dive results, call recording, configurable per-ticker raise. Exact behavior in §4. |
| `app/db.py` (modify) | Add `candidates` table (schema in §6) + `insert_candidate()`/`get_candidates_for_run()` helpers alongside the existing `runs`/`ideas` helpers from Slice 0. |
| `app/run_orchestrator.py` (modify) | Add orchestrator steps 3-4 (sweep → shortlist → deep-dive loop), wired to a `HaikuSession` passed into `RunOrchestrator.__init__` (constructor-injected, exactly like the sibling's `RunOrchestrator(sourcing, scoring, session, conn)` — here `RunOrchestrator(sourcing_aggregator, haiku_session, conn)`, with `haiku_session` defaulting to a `FakeHaikuSession()` instance in `main.py`'s wiring until Slice 7 swaps it). Candidate results are persisted to the new `candidates` table and also written into `ideas` (placeholder tier) so the existing Slice-0 card UI keeps working. |
| `tests/test_fake_haiku_session.py` | Unit tests for `FakeHaikuSession` itself (canned output returned correctly, call recording, configurable raise). |
| `tests/test_sweep_stage.py` | Unit tests for `run_sweep_stage`'s bound-enforcement. |
| `tests/test_deep_dive_stage.py` | Unit tests for `run_deep_dive_stage`'s skip-and-continue loop. |
| `tests/test_run_orchestrator_slice4.py` | Integration tests: full run through `RunOrchestrator` wired to `FakeHaikuSession`, asserting end-to-end shortlist→deep-dive→persistence behavior and call counts. |

No new router/template files are strictly required — the existing Slice-0 index page and `/api/run/last` response already render an `ideas` list; this slice just makes that list reflect real (fake-driven) per-ticker data. One small template tweak is needed (§8) so sub-score/reasoning fields are visible, since Slice 0's card only had a flat `rationale` string.

---

## 2. `HaikuSession` Protocol — exact shape

`app/agent/sessions.py`:

```python
from dataclasses import dataclass, field
from typing import Protocol


@dataclass(frozen=True)
class Citation:
    source: str        # e.g. "moneycontrol_rss", "screener_in"
    headline: str
    url: str
    published_at: str  # ISO-8601 date/datetime string


@dataclass(frozen=True)
class ShortlistCandidate:
    """One ticker the sweep stage flagged as worth a deep-dive."""
    ticker: str
    reason: str          # one-line reason the sweep surfaced this ticker


@dataclass(frozen=True)
class DeepDiveContext:
    """Already-fetched content the deep-dive reasons over (no web tools in
    the deep-dive call — FR4). Built by the orchestrator from the sweep's
    NormalizedItems filtered/grouped by ticker; shape is intentionally the
    sweep's own NormalizedItem list, not re-fetched or re-shaped."""
    ticker: str
    items: list  # list[NormalizedItem] (app.sources.base.NormalizedItem);
                 # left untyped here (not `list[NormalizedItem]`) only to
                 # avoid sessions.py depending on sources/base.py — Slice 7
                 # may tighten this import once both modules are stable.


@dataclass(frozen=True)
class DeepDiveResult:
    ticker: str
    catalyst_subscore: int        # 0-40 raw band value, per tech-spec §6
    catalyst_reasoning: str
    sector_momentum_subscore: int  # 0-35
    sector_momentum_reasoning: str
    macro_subscore: int            # 0-25
    macro_reasoning: str
    citations: list[Citation]      # length >= 1 (FR4/FR7 hard constraint;
                                    # enforced by assembly in Slice 9, not here)
    # Raw negative-filter signal fields the Slice 6 filter stage will consume.
    # Haiku reports these as flags/values; Slice 6 decides thresholds/action.
    daily_volume: int | None = None
    has_institutional_ownership: bool | None = None
    promotional_chatter_flag: bool = False
    catalyst_announcement_date: str | None = None  # ISO date, for the
        # stale-news cross-check against NSE announcement dates (Slice 6)


class HaikuSession(Protocol):
    async def run_sweep(self, items: list) -> list[ShortlistCandidate]:
        """items: list[NormalizedItem] from the completed sourcing stage.
        Returns a shortlist of candidate tickers worth a deep-dive. The
        caller (agent/sweep.py) enforces the MAX_SHORTLIST_SIZE bound; this
        method itself is free to return more or fewer -- it is not this
        method's job to truncate."""
        ...

    async def run_deep_dive(
        self, ticker: str, context: DeepDiveContext
    ) -> DeepDiveResult:
        """One ticker, no web tools -- reasoning over `context.items` only
        (FR4). Raises Exception (any type) on failure for THIS ticker only;
        callers (agent/deep_dive.py) catch and skip-and-continue, exactly
        like the sibling's ScoringError-per-posting pattern, except here the
        fake/real session may raise any exception type (no dedicated
        `DeepDiveError` type is introduced this slice -- the skip policy
        only needs "did it raise," not a typed reason; Slice 7 can introduce
        a narrower exception type if real-SDK failure modes warrant it)."""
        ...
```

**Judgment call:** unlike the sibling's `ScoringPort.score_posting`, which raises a dedicated `ScoringError`, this slice's `run_deep_dive` is documented to raise *any* exception, and `agent/deep_dive.py` catches `Exception` broadly. Rationale: this slice only has a fake implementation, and the fake's failure-simulation need is "raise when configured to," not "raise a specific semantically-typed error." Narrowing this to a dedicated exception type is deferred to Slice 7, where real SDK failure modes (timeout, error result, malformed JSON) are concretely known and worth distinguishing.

---

## 3. Shortlist-size bound

**Decision: `MAX_SHORTLIST_SIZE = 18`.**

Justification: the spec (FR3) requires the shortlist be "enough to comfortably produce up to 10 final ideas after filtering." Downstream, candidates can be lost at three later points: (a) per-stock deep-dive failures (Slice 4/7's skip-and-continue — real-world Haiku exchange failure rate is unknown but non-zero), (b) negative filtering (Slice 6 — pump-and-dump/stale-news exclusions), and (c) the red-tier default exclusion before backfill (Slice 9 — only yellow/green fill the list by default). Vertical-slice-plan's own suggestion was "~15-20." Picking **18** (midpoint-high within that range) gives roughly a 45% attrition budget to still land exactly 10 (lose up to 8 of 18) without having to special-case a "too few survived" path differently than today — if attrition exceeds that, Slice 9's backfill logic (already planned to use red-tier ideas when short) absorbs the gap; this slice does not need to react to it. 18 is not safety-critical to pin further right now: it is a single named constant (`MAX_SHORTLIST_SIZE` in `app/agent/sweep.py`), trivially tunable later from real-run data (per spec §6's "explicitly tunable" framing) without touching any other file.

---

## 4. `FakeHaikuSession` — exact canned behavior

`app/fakes/fake_sessions.py`:

```python
from app.agent.sessions import (
    Citation, DeepDiveContext, DeepDiveResult, ShortlistCandidate,
)

DEFAULT_SHORTLIST: list[ShortlistCandidate] = [
    ShortlistCandidate(ticker="RELIANCE", reason="Refining margin catalyst + Jio Financial spin-off chatter"),
    ShortlistCandidate(ticker="TATAMOTORS", reason="JLR volume recovery + EV launch cycle"),
    ShortlistCandidate(ticker="INFY", reason="Large deal wins reported this week"),
]

DEFAULT_DEEP_DIVES: dict[str, DeepDiveResult] = {
    "RELIANCE": DeepDiveResult(
        ticker="RELIANCE",
        catalyst_subscore=32, catalyst_reasoning=(
            "Refining margins reported up q/q per Moneycontrol coverage; "
            "Jio Financial stake-sale speculation adds a secondary catalyst."
        ),
        sector_momentum_subscore=28, sector_momentum_reasoning=(
            "Energy/conglomerate peers showing a multi-week uptrend in the "
            "Bhavcopy OHLC data reviewed."
        ),
        macro_subscore=20, macro_reasoning=(
            "Trading Economics calendar shows no major adverse macro print "
            "in the near-term window; treated as yellow macro context."
        ),
        citations=[Citation(
            source="moneycontrol_rss",
            headline="Reliance Industries refining margins improve in Q2",
            url="https://example.com/fake/reliance-refining-margins",
            published_at="2026-10-10",
        )],
        daily_volume=5_200_000, has_institutional_ownership=True,
        promotional_chatter_flag=False,
        catalyst_announcement_date="2026-10-09",
    ),
    "TATAMOTORS": DeepDiveResult(
        ticker="TATAMOTORS",
        catalyst_subscore=24, catalyst_reasoning=(
            "JLR wholesale volumes recovering per latest commentary; EV "
            "launch date announced within the review window."
        ),
        sector_momentum_subscore=18, sector_momentum_reasoning=(
            "Auto sector showing mixed momentum across Bhavcopy data; not a "
            "uniformly strong tailwind."
        ),
        macro_subscore=15, macro_reasoning=(
            "Macro calendar flags an upcoming rate decision as a risk to "
            "discretionary-auto demand; treated as red macro context."
        ),
        citations=[Citation(
            source="moneycontrol_rss",
            headline="Tata Motors JLR volumes show recovery signs",
            url="https://example.com/fake/tatamotors-jlr-recovery",
            published_at="2026-10-08",
        )],
        daily_volume=8_900_000, has_institutional_ownership=True,
        promotional_chatter_flag=False,
        catalyst_announcement_date="2026-09-28",  # intentionally stale --
        # Slice 6's stale-news filter is expected to act on this fixture.
    ),
    "INFY": DeepDiveResult(
        ticker="INFY",
        catalyst_subscore=14, catalyst_reasoning=(
            "Deal-win headline present but light on deal-size specifics; "
            "treated as a weak catalyst."
        ),
        sector_momentum_subscore=12, sector_momentum_reasoning=(
            "IT services sector flat-to-down in the reviewed Bhavcopy window."
        ),
        macro_subscore=20, macro_reasoning=(
            "No material adverse macro print found for the IT sector in "
            "the review window; treated as yellow."
        ),
        citations=[Citation(
            source="moneycontrol_rss",
            headline="Infosys wins large deal with European retailer",
            url="https://example.com/fake/infy-deal-win",
            published_at="2026-10-11",
        )],
        daily_volume=45_000, has_institutional_ownership=False,
        promotional_chatter_flag=True,  # intentionally pump-and-dump-shaped --
        # Slice 6's filter is expected to act on this fixture.
        catalyst_announcement_date="2026-10-11",
    ),
}


class FakeHaikuSession:
    """Satisfies HaikuSession. Canned sweep + per-ticker deep-dive output,
    with call recording and a configurable per-ticker failure trick --
    mirrors FakeScoringPort's `canned: dict[key, Exception | value]` and
    FakeSessionManager's call-recording style, combined.

    Args:
        shortlist: overrides DEFAULT_SHORTLIST if given.
        deep_dives: overrides DEFAULT_DEEP_DIVES if given (dict[ticker, DeepDiveResult]).
        fail_tickers: set of tickers for which run_deep_dive raises instead
            of returning a canned result -- the "configure this ticker to
            raise" failure-simulation hook. Raises RuntimeError(ticker) by
            default; pass fail_tickers as a dict[ticker, Exception] instead
            of a set to control the exact exception raised per ticker.
    """

    def __init__(
        self,
        shortlist: list[ShortlistCandidate] | None = None,
        deep_dives: dict[str, DeepDiveResult] | None = None,
        fail_tickers: "set[str] | dict[str, Exception] | None" = None,
    ):
        self.shortlist = shortlist if shortlist is not None else list(DEFAULT_SHORTLIST)
        self.deep_dives = dict(deep_dives if deep_dives is not None else DEFAULT_DEEP_DIVES)
        if fail_tickers is None:
            self._fail: dict[str, Exception] = {}
        elif isinstance(fail_tickers, dict):
            self._fail = dict(fail_tickers)
        else:
            self._fail = {t: RuntimeError(f"fake deep-dive failure for {t}") for t in fail_tickers}

        self.sweep_calls: list[list] = []          # each entry: the `items` list passed in
        self.deep_dive_calls: list[tuple[str, DeepDiveContext]] = []

    async def run_sweep(self, items: list) -> list[ShortlistCandidate]:
        self.sweep_calls.append(items)
        return list(self.shortlist)

    async def run_deep_dive(self, ticker: str, context: DeepDiveContext) -> DeepDiveResult:
        self.deep_dive_calls.append((ticker, context))
        if ticker in self._fail:
            raise self._fail[ticker]
        if ticker not in self.deep_dives:
            raise KeyError(f"FakeHaikuSession has no canned deep-dive for {ticker!r}")
        return self.deep_dives[ticker]
```

Call-recording for test assertions: `fake.sweep_calls` (list, one entry per `run_sweep` call — asserting `len(fake.sweep_calls) == 1` proves "exactly one sweep call per run"), `fake.deep_dive_calls` (list of `(ticker, context)` tuples, one entry per `run_deep_dive` call, in call order — asserting its length and ticker set proves "one deep-dive call per shortlisted ticker").

Failure-simulation for tests: construct `FakeHaikuSession(fail_tickers={"TATAMOTORS"})` to make that one ticker's deep-dive raise while `RELIANCE`/`INFY` succeed normally — this is the exact mechanic `test_deep_dive_stage.py`'s skip-and-continue test and `test_run_orchestrator_slice4.py`'s per-stock-failure test use.

---

## 5. Orchestrator wiring — exact new steps in `run_orchestrator.py`

`RunOrchestrator.__init__` gains a `haiku_session: HaikuSession` parameter (constructor-injected, same pattern as the sibling's `session: SessionManager`). `execute_run()` gains two new steps inserted between the existing sourcing step (Slice 1/2) and the existing fake-idea-insert step (Slice 0, now removed/replaced):

```python
# Step 3 (new): sweep stage -- narrow the full sourced item set to a shortlist.
shortlist = await run_sweep_stage(self.haiku_session, sourced_items)

# Step 4 (new): deep-dive stage -- one call per shortlisted ticker,
# per-stock failure handling via skip-and-continue (locked decision).
context_by_ticker = _build_deep_dive_contexts(sourced_items, shortlist)
deep_dive_results = await run_deep_dive_stage(
    self.haiku_session, shortlist, context_by_ticker
)

# Step 4b: persist each surviving candidate (candidates table) and mirror
# into `ideas` with a placeholder tier so Slice 0's existing card UI
# continues to render something meaningful (real tier lands in Slice 5).
for result in deep_dive_results:
    candidate_id = db.insert_candidate(self.conn, run_id, result)
    db.insert_idea_placeholder(self.conn, run_id, result, candidate_id)
```

Where `_build_deep_dive_contexts` groups the already-fetched `NormalizedItem`s by `ticker` (items whose `ticker` field matches, per `initial-plan.md` Decision C's note that RSS items may have `ticker: None` until mapped — for this slice, items with no ticker match are simply included for every shortlisted ticker's context as general market/macro background, since no ticker-mapping logic exists yet and is out of scope here).

**Per-stock failure handling (locked decision, implemented precisely):** inside `agent/deep_dive.py`'s `run_deep_dive_stage`:

```python
async def run_deep_dive_stage(session, shortlist, context_by_ticker):
    results = []
    for candidate in shortlist:
        ticker = candidate.ticker
        context = context_by_ticker.get(ticker, DeepDiveContext(ticker=ticker, items=[]))
        try:
            result = await session.run_deep_dive(ticker, context)
        except Exception:
            log.warning("deep-dive failed for %s; skipping", ticker, exc_info=True)
            continue
        results.append(result)
    return results
```

This is a direct per-ticker `try/except ... continue` loop — no whole-run abort, matching the sibling's per-posting `ScoringError` catch in `run_orchestrator.py`'s scoring loop, generalized to catch any exception (per §2's judgment call).

---

## 6. New schema — `candidates` table

Added to `app/db.py`'s schema alongside Slice 0's `runs`/`ideas` tables:

```sql
CREATE TABLE IF NOT EXISTS candidates (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      INTEGER NOT NULL REFERENCES runs(id),
    ticker                      TEXT NOT NULL,
    sweep_reason                TEXT NOT NULL,     -- ShortlistCandidate.reason
    catalyst_subscore           INTEGER NOT NULL,  -- 0-40
    catalyst_reasoning          TEXT NOT NULL,
    sector_momentum_subscore    INTEGER NOT NULL,  -- 0-35
    sector_momentum_reasoning   TEXT NOT NULL,
    macro_subscore              INTEGER NOT NULL,  -- 0-25
    macro_reasoning             TEXT NOT NULL,
    citations_json              TEXT NOT NULL,     -- JSON list of
                                                    -- {source,headline,url,published_at}
    daily_volume                INTEGER,
    has_institutional_ownership INTEGER,           -- bool 0/1, nullable
    promotional_chatter_flag    INTEGER NOT NULL DEFAULT 0,  -- bool 0/1
    catalyst_announcement_date  TEXT,              -- ISO date, nullable
    created_at                  TEXT NOT NULL       -- ISO-8601 UTC
);
```

Rationale: this mirrors `DeepDiveResult` field-for-field (matching Slice 0's precedent of naming placeholder columns up front to avoid later `ALTER TABLE`s). `citations_json` is a single JSON column (not a normalized child table) because Slice 4 has no query need to filter/join on individual citations yet — this can be normalized later without data loss if a real need arises, consistent with keeping this slice's scope minimal. `candidates` is additive — it does not replace or modify Slice 0's `ideas` table; `ideas` keeps being populated too (via `insert_idea_placeholder`) so the existing UI path (`GET /api/run/last`) needs no response-shape change this slice, only richer per-row content. `ideas.tier` is set to the literal string `"unscored"` as a placeholder (new allowed value beyond Slice 0's `"red"|"yellow"|"green"`) until Slice 5 computes the real tier — the UI template (§8) renders `"unscored"` with a neutral badge rather than crashing on an unexpected tier string.

---

## 7. Idea-row mirroring details

`db.insert_idea_placeholder(conn, run_id, result: DeepDiveResult, candidate_id: int)` inserts into `ideas`:
- `ticker` = `result.ticker`
- `entry`/`target`/`hold_days` = `0.0`/`0.0`/`0` placeholders (real entry/target pricing is not derived anywhere until a later slice in the broader plan that is out of this plan's scope — not reopened here; flagged only so a coder doesn't invent logic for it)
- `tier` = `"unscored"`
- `score`, `sub_score_catalyst`, `sub_score_momentum`, `sub_score_macro` = `result.catalyst_subscore`, `result.sector_momentum_subscore`, `result.macro_subscore` stored directly in the existing placeholder sub-score columns from Slice 0's schema (no new columns needed for these three — Slice 0 already added `sub_score_catalyst`/`sub_score_momentum`/`sub_score_macro` as nullable placeholders; this slice is the first to populate them with real values)
- `rationale` = concatenation of the three reasoning strings, newline-joined, prefixed with the ticker's sweep reason — e.g. `f"{result.catalyst_reasoning}\n{result.sector_momentum_reasoning}\n{result.macro_reasoning}"` (Slice 8's Sonnet compilation later replaces this with polished text; this slice's concatenation is a deliberately simple placeholder, not a design decision for later slices)
- `citation_url`/`citation_source`/`citation_headline` = first citation's `url`/`source`/`headline` (first-citation-only is this slice's placeholder; Slice 9's assembly logic is where "every idea needs >=1 citation" becomes a hard-enforced rule — here it's just display plumbing)
- `low_confidence` = `0`
- `rank` = position in `deep_dive_results` (1-based, in the order results were appended — i.e., shortlist order minus skips; no scoring-based ordering exists yet)

---

## 8. Template change

`app/templates/index.html`'s card partial (added in Slice 0) gains three more lines rendering `sub_score_catalyst`, `sub_score_momentum`, `sub_score_macro` labeled "Catalyst," "Sector momentum," "Macro," and renders `tier == "unscored"` with a neutral gray badge instead of the red/yellow/green badge colors (a one-line conditional in the existing badge-class logic). No new route or JS polling logic is needed — the existing `GET /api/run/last` polling flow from Slice 0 already re-renders the ideas list; only the per-idea field list shown grows.

---

## 9. Step-by-step implementation sequence

1. `app/agent/__init__.py`, `app/agent/sessions.py` — Protocol + dataclasses (§2). No other module depends on this yet; verify it imports cleanly in isolation.
2. `app/fakes/__init__.py`, `app/fakes/fake_sessions.py` — `FakeHaikuSession` + fixtures (§4). Write `tests/test_fake_haiku_session.py` immediately after (canned returns, call recording, configurable raise) before touching the orchestrator, so the fake's own contract is locked first.
3. `app/agent/sweep.py` — `run_sweep_stage` + `MAX_SHORTLIST_SIZE = 18` (§3). `tests/test_sweep_stage.py`: feed the fake a 25-item shortlist override, assert the returned list is truncated to 18.
4. `app/agent/deep_dive.py` — `run_deep_dive_stage` (§5). `tests/test_deep_dive_stage.py`: one test with all tickers succeeding (assert all results returned, call count matches shortlist length); one test with `fail_tickers={"X"}` (assert `X` absent from results, others present, call count still matches shortlist length since the failing call still happened).
5. `app/db.py` — add `candidates` table DDL + `insert_candidate()`, `get_candidates_for_run()`, `insert_idea_placeholder()` (§6-7). Manually verify (`python -c ...`) the new table is created alongside Slice 0's tables with no migration errors on an existing dev DB file (drop/recreate the dev DB if Slice 0 left one around, since this is additive DDL via `CREATE TABLE IF NOT EXISTS` and needs no `ALTER TABLE`).
6. `app/run_orchestrator.py` — wire steps 3-4 (§5), remove/replace Slice 0's hardcoded-fake-idea insert with the real (fake-session-driven) path, add `_build_deep_dive_contexts` helper.
7. `app/main.py` — update `RunOrchestrator(...)` construction site to pass a `FakeHaikuSession()` instance as `haiku_session` (this is the only wiring change main.py needs; no settings/config flag is introduced this slice since there is exactly one implementation to choose from — Slice 7 is where a real-vs-fake selection point gets added, per vertical-slice-plan's note that a "dev/test config toggle" is a Slice 7 concern, not required here).
8. Template update (§8).
9. `tests/test_run_orchestrator_slice4.py` — integration tests (§10) against the real `RunOrchestrator` wired to `FakeHaikuSession` and the existing fake/stub sourcing from earlier slices.
10. Run the full suite (`pytest tests/ -v`), fix regressions, then do the manual demonstration (§11).

---

## 10. Exact test files and cases

Run with: `pytest tests/ -v`

### `tests/test_fake_haiku_session.py`
- `test_run_sweep_returns_default_shortlist_and_records_call` — `await fake.run_sweep(items)` returns `DEFAULT_SHORTLIST`; `fake.sweep_calls == [items]`.
- `test_run_deep_dive_returns_canned_result_and_records_call` — `await fake.run_deep_dive("RELIANCE", ctx)` returns `DEFAULT_DEEP_DIVES["RELIANCE"]`; `fake.deep_dive_calls == [("RELIANCE", ctx)]`.
- `test_run_deep_dive_unknown_ticker_raises_keyerror` — a ticker with no canned entry and not in `fail_tickers` raises `KeyError`.
- `test_fail_tickers_set_raises_runtimeerror_for_configured_ticker` — `FakeHaikuSession(fail_tickers={"TATAMOTORS"})`; `run_deep_dive("TATAMOTORS", ctx)` raises `RuntimeError`; `run_deep_dive("RELIANCE", ctx)` still succeeds normally.
- `test_fail_tickers_dict_raises_the_given_exception` — `FakeHaikuSession(fail_tickers={"X": ValueError("boom")})`; raises exactly that `ValueError` instance/type.
- `test_custom_shortlist_and_deep_dives_override_defaults` — constructing with explicit `shortlist=`/`deep_dives=` args returns those instead of the module defaults.

### `tests/test_sweep_stage.py`
- `test_shortlist_truncated_to_max_size` — fake configured with a 25-candidate shortlist; `run_sweep_stage` returns exactly 18 (`MAX_SHORTLIST_SIZE`), preserving original order (first 18).
- `test_shortlist_under_bound_returned_unchanged` — fake with 3 candidates (the default); `run_sweep_stage` returns all 3.

### `tests/test_deep_dive_stage.py`
- `test_one_deep_dive_call_per_shortlisted_ticker` — default 3-candidate shortlist, no failures; `run_deep_dive_stage` returns 3 results; `fake.deep_dive_calls` has exactly 3 entries, tickers matching the shortlist in order.
- `test_per_stock_failure_is_skipped_and_run_continues` — `FakeHaikuSession(fail_tickers={"TATAMOTORS"})`, default 3-candidate shortlist; `run_deep_dive_stage` returns exactly 2 results (`RELIANCE`, `INFY`), `TATAMOTORS` absent; `fake.deep_dive_calls` still has 3 entries (the failing call was still attempted and recorded).

### `tests/test_run_orchestrator_slice4.py`
- `test_full_run_produces_shortlist_bound_and_candidate_rows` — construct `RunOrchestrator` with a stubbed/fake sourcing aggregator (reusing Slice 1/2's existing fake sourcing fixture) and a `FakeHaikuSession` with a 25-item shortlist override; execute a run; query `candidates` table for that `run_id`; assert row count == 18 (shortlist bound respected end-to-end, through persistence).
- `test_full_run_one_deep_dive_call_per_shortlisted_ticker` — default 3-ticker fake; execute a run; assert `fake.sweep_calls` has length 1 (exactly one sweep call per run) and `fake.deep_dive_calls` has length 3, tickers matching.
- `test_full_run_per_stock_failure_skip_and_continue` — `FakeHaikuSession(fail_tickers={"TATAMOTORS"})`; execute a run; assert the run's final status is `"complete"` (not `"error"`), `candidates` table for this run has exactly 2 rows (`RELIANCE`, `INFY`), and `ideas` table mirrors the same 2 tickers — proving a per-stock failure never aborts the run.
- `test_full_run_ideas_table_populated_with_real_subscores` — default fake; execute a run; query `ideas` for the run; assert `sub_score_catalyst`/`sub_score_momentum`/`sub_score_macro` match the fake's canned `DeepDiveResult` values exactly (not null, not the Slice 0 placeholders) and `tier == "unscored"`.

Exact command: `pytest tests/ -v` (same as Slice 0 — no new pytest config/markers needed; all tests here are fast, no network, no sleeps beyond what the existing orchestrator stub already does).

---

## 11. Manual demonstration

1. Start the server: `uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload` (`app/main.py` wired to construct `RunOrchestrator(..., haiku_session=FakeHaikuSession())` per §9 step 7).
2. Open `http://127.0.0.1:8000/`, click "Run now."
3. Once the run completes (polling, unchanged from Slice 0/3's mechanism), the card list should now show **three distinct cards** — `RELIANCE`, `TATAMOTORS`, `INFY` — each with its own catalyst/sector-momentum/macro sub-score values and its own reasoning text (visibly different per card), instead of Slice 0's single static `RELIANCE` fake idea with one hardcoded rationale string. The tier badge on all three should render as the neutral "unscored" state (not red/yellow/green, since Slice 5 hasn't run yet).
4. Inspect the SQLite DB directly (`sqlite3 ~/.swingtrade/app.db "SELECT ticker, catalyst_subscore, sector_momentum_subscore, macro_subscore FROM candidates ORDER BY id;"`) and confirm three rows matching the fake's canned `DeepDiveResult` values exactly.
5. To demonstrate the failure-skip path manually: temporarily edit `app/main.py`'s wiring to pass `FakeHaikuSession(fail_tickers={"TATAMOTORS"})`, restart the server, trigger a run, and confirm only two cards (`RELIANCE`, `INFY`) appear and the run still reports `status: complete` (not `error`) — then revert the temporary edit.

---

## 12. Acceptance criteria and verification evidence

- [ ] A run that proceeds past quick-sweep produces a shortlist via the fake sweep call, then one deep-dive call per shortlisted ticker via the fake session. **Evidence:** `test_full_run_one_deep_dive_call_per_shortlisted_ticker` passing; manual step 3.
- [ ] Shortlist size is bounded at `MAX_SHORTLIST_SIZE = 18`, enforced end-to-end through persistence. **Evidence:** `test_shortlist_truncated_to_max_size` and `test_full_run_produces_shortlist_bound_and_candidate_rows` passing.
- [ ] A per-stock deep-dive failure (simulated via the fake raising for one ticker) results in that ticker being skipped, with the rest of the run completing normally — not an aborted run. **Evidence:** `test_per_stock_failure_is_skipped_and_run_continues`, `test_full_run_per_stock_failure_skip_and_continue` passing; manual step 5.
- [ ] `FakeHaikuSession`'s call-recording attributes show exactly one sweep call and one deep-dive call per surviving shortlisted candidate. **Evidence:** `test_full_run_one_deep_dive_call_per_shortlisted_ticker` asserting `len(fake.sweep_calls) == 1` and `len(fake.deep_dive_calls) == len(shortlist)`.
- [ ] Idea cards reflect distinct per-ticker canned reasoning/sub-scores instead of Slice 0's one static fake idea. **Evidence:** manual step 3 (visual, three distinct cards); `test_full_run_ideas_table_populated_with_real_subscores` passing.
- [ ] No real `ClaudeSDKClient`/SDK import exists anywhere in this slice's new code. **Evidence:** `grep -rn "claude_agent_sdk\|ClaudeSDKClient" app/agent/ app/fakes/` returns no matches.
- [ ] `pytest tests/ -v` — all tests (Slice 0-4 combined) pass, zero skips/xfails.

Slice 4 is complete only when every checkbox above is verified with the stated evidence, not merely claimed.
