# Slice 2 — Detailed Technical Plan: Remaining Source Adapters + Aggregator

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 2 only
**Inputs (locked, not reopened):** `tech-spec.md`, `initial-plan.md`, `vertical-slice-plan.md` (Slice 2 section, lines 137-174), `plan-detailed/slice-0.md`, `plan-detailed/slice-1.md` (adapter pattern, shared shape, `sweep_items` table, failure-isolation pattern — all reused, not re-decided)
**Precedent:** sibling `ai-job-finder-console`'s `app/sourcing/real_sourcing.py` (`asyncio.gather(..., return_exceptions=True)`, per-platform failure recorded by name, run continues with partial results) and `app/fakes/fake_sourcing.py` (canned-list fake, injectable failure, `calls` recording for assertions).

**Builds on Slice 1 exactly as established:** `app/sources/base.py`'s `NormalizedItem`/`SourceAdapter`/`make_snippet`/`SourceFetchError`, the `sweep_items` table and `insert_sweep_items`/`get_sweep_items` helpers, the try/except-log-continue failure pattern in the orchestrator's sourcing step. This slice promotes that single-adapter pattern to a genuine multi-adapter aggregator and extends `sweep_items` with nullable source-specific columns rather than introducing a second table — keeping one unified sweep-items store, consistent with Slice 1's schema design intent.

---

## 1. Files to create / modify

| Path | Change | Responsibility |
|---|---|---|
| `app/sources/nse_bhavcopy.py` | create | Fetch NSE's daily Bhavcopy EOD CSV, parse rows, normalize into `NormalizedItem` + OHLC/volume extension fields, one row per ticker. |
| `app/sources/screener_in.py` | create | Fetch a Screener.in company page per candidate ticker, parse fundamentals (P/E, market cap, latest-quarter highlights), normalize into `NormalizedItem` + fundamentals extension fields. |
| `app/sources/trading_economics.py` | create | Fetch Trading Economics' free macro calendar, parse upcoming/recent indicator events, normalize into `NormalizedItem` (no ticker — macro-level, not stock-level). |
| `app/sources/aggregator.py` | create | `SourcingAggregator` — calls all configured adapters concurrently, merges results, isolates per-adapter failures, returns `(items: list[NormalizedItem], failed_sources: list[str])`. |
| `app/sources/base.py` | modify | Extend `NormalizedItem` with optional, source-specific extension fields (see §2) — additive only, no change to Slice 1's existing fields/semantics. |
| `app/db.py` | modify | Extend `sweep_items` DDL with nullable OHLC/volume + fundamentals columns (additive `CREATE TABLE IF NOT EXISTS` — no `ALTER TABLE` needed since the table is still new enough in this project's lifecycle that the full DDL can simply be rewritten; see §3 note on why this is safe here specifically). `insert_sweep_items` updated to write the new optional columns. |
| `app/run_orchestrator.py` | modify | Sourcing step now calls `SourcingAggregator.fetch_all()` instead of the single Slice-1 adapter directly; persists the merged, failure-isolated result; `failed_sources` surfaced onto the run record (new column — see §3). |
| `app/routers/run.py` | modify | `GET /api/run/last` response's `sources` array now reflects all configured sources together; add `failed_sources` to the run summary payload. |
| `app/templates/index.html` | modify | "Sources seen" section groups/labels items by source; shows a small "sources unavailable this run: X" notice when `failed_sources` is non-empty. |
| `app/static/js/run.js` | modify | Render grouped-by-source items and the failed-sources notice. |
| `pyproject.toml` | modify | Add dependency for CSV parsing (stdlib `csv` — no new dependency) and an HTML parser for Screener.in: `selectolax` (preferred — lightweight, fast, minimal transitive deps) or `beautifulsoup4` as fallback if `selectolax` proves awkward; decision documented in §4. |
| `tests/fixtures/bhavcopy_sample.csv` | create | A small canned Bhavcopy-format CSV (3-4 ticker rows) matching NSE's real column layout. |
| `tests/fixtures/screener_sample.html` | create | A minimal canned Screener.in company-page HTML snippet with the fundamentals table present. |
| `tests/fixtures/trading_economics_sample.html` (or `.json`) | create | A minimal canned macro-calendar fixture matching whichever response shape §4 settles on. |
| `tests/test_nse_bhavcopy.py` | create | Fixture-based parse test + retention test for this adapter. |
| `tests/test_screener_in.py` | create | Fixture-based parse test + retention test for this adapter. |
| `tests/test_trading_economics.py` | create | Fixture-based parse test + retention test for this adapter. |
| `tests/test_aggregator.py` | create | Partial-failure test: one adapter stubbed to fail, others succeed, aggregator returns the merged partial result and names the failed one. |
| `tests/test_run_orchestrator_sourcing.py` | modify | Extend Slice 1's orchestrator tests to use the aggregator (multiple stub adapters) rather than one hardcoded adapter. |

Optional secondary RSS adapter (`app/sources/secondary_rss.py`, e.g. Economic Times or Mint): **deferred to a backlog note, not built in this slice.** Judgment call — the vertical-slice-plan lists it as "[, optional secondary RSS]" and the research doc treats it as diversification rather than a hard requirement; `moneycontrol_rss.py`'s adapter shape from Slice 1 is already proven and directly reusable (same RSS-via-`feedparser` pattern, different URL constant) if the user wants it added later — adding it would be a same-shaped, low-risk follow-up, not a reason to hold up Slice 2's four core sources. Flagging for user confirmation; easy to pull in if they want it now instead.

---

## 2. Extending `NormalizedItem` with source-specific extra fields

Slice 1's base shape (`source`, `headline`, `url`, `published_at`, `snippet`, `ticker`) is preserved exactly. This slice adds **optional, nullable, source-agnostic extension fields** directly on `NormalizedItem` (not a separate per-source subclass hierarchy) — chosen over subclassing because: (a) it keeps `sweep_items` a single flat table with a stable column set across all sources, matching Slice 1's "one unified table" design intent; (b) the retention guarantee (§3) needs to validate one shape, not N subclasses; (c) the aggregator (§5) needs a single list type to merge, not a union type.

```python
@dataclasses.dataclass(frozen=True)
class NormalizedItem:
    source: str
    headline: str
    url: str
    published_at: dt.datetime
    snippet: str
    ticker: str | None = None

    # --- Optional extension fields, populated only by the adapters that
    # have this data; always None/absent for adapters that don't. ---
    close: float | None = None          # Bhavcopy: EOD close price
    prev_close: float | None = None      # Bhavcopy: previous day's close
    volume: int | None = None            # Bhavcopy: traded quantity for the day
    pe_ratio: float | None = None        # Screener.in: trailing P/E
    market_cap_cr: float | None = None   # Screener.in: market cap, INR crore
    indicator_name: str | None = None    # Trading Economics: e.g. "India CPI YoY"
    indicator_value: str | None = None   # Trading Economics: e.g. "5.2%" (kept as a short formatted string, not a raw unbounded text blob)

    def __post_init__(self) -> None:
        if len(self.snippet) > SNIPPET_MAX_CHARS + 3:
            raise ValueError(...)  # unchanged from Slice 1
```

- Each adapter populates only the extension fields relevant to it; all others stay `None`. This is intentionally simple (a wide, mostly-null row) rather than a polymorphic type — appropriate at this project's scale (4-5 sources, single-user tool), and it is what Slice 5/6's deterministic scoring and negative-filtering stages will read sub-score inputs from later (Bhavcopy's `volume` directly feeds the pump-and-dump check per spec FR4 — this is why Bhavcopy's extension lives on the *same* `NormalizedItem`/`sweep_items` row shape rather than a separate price-data table: later stages need to join sourcing data back to a ticker without a second join).
- `indicator_value` is deliberately typed as a short formatted string (e.g. `"5.2%"`, `"102.3 (prior 101.8)"`), not a float, because Trading Economics' calendar reports heterogeneous units (%, index points, counts) — keeping it as a short pre-formatted string avoids inventing a unit-conversion scheme this slice doesn't need, while still respecting the retention/length constraint implicitly (it is always short by construction, never body text).
- None of the new fields are body/content fields — they are all short scalars (price, ratio, a formatted indicator value) — so they introduce no new retention risk; the existing `snippet`-length guard remains the only field capable of accidentally holding long text, and it is unchanged from Slice 1.

---

## 3. `sweep_items` schema extension

Slice 1's table gains nullable columns (additive, no removal/rename of Slice 1's columns):

```sql
CREATE TABLE IF NOT EXISTS sweep_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    source          TEXT NOT NULL,
    headline        TEXT NOT NULL,
    url             TEXT NOT NULL,
    published_at    TEXT NOT NULL,
    snippet         TEXT NOT NULL CHECK (length(snippet) <= 300),
    ticker          TEXT,
    fetched_at      TEXT NOT NULL,
    -- New in Slice 2 (all nullable; only populated by the adapter that owns the field):
    close           REAL,
    prev_close      REAL,
    volume          INTEGER,
    pe_ratio        REAL,
    market_cap_cr   REAL,
    indicator_name  TEXT,
    indicator_value TEXT CHECK (indicator_value IS NULL OR length(indicator_value) <= 64)  -- short formatted scalar, not body text
);
```

**Why a plain DDL rewrite (not an `ALTER TABLE ... ADD COLUMN` migration) is safe here:** this project has no shipped/external users and no migration framework (per Slice 0's explicit note that `CREATE TABLE IF NOT EXISTS` is sufficient at this stage; the sibling project's `_ADDED_COLUMNS` mechanism was flagged in Slice 0 as "a model to reach for... if a genuinely new column is needed after the fact" — but since schema changes here are still happening within the planning phase, before any real persisted data exists that must survive a column addition across app restarts in the field, a full fresh-DDL rewrite is equivalent and simpler). **If by the time Slice 2 is implemented real Slice-0/Slice-1 run data already exists in a developer's local DB that must be preserved,** use the sibling's `_ADDED_COLUMNS`-style `ALTER TABLE sweep_items ADD COLUMN ...` additive migration instead of dropping/recreating — flagging this as an implementation-time judgment call based on actual local DB state at that point, not a decision to make now.

**Retention-safety preserved:** every new column is a short bounded scalar (float/int) or a length-capped string (`indicator_value <= 64` chars) — none can hold article-body-length text. The table still has no `body`/`content`/`full_text`/`html` column of any kind.

**New `runs`-table column (orchestrator-level, not sourcing-level):**
```sql
ALTER TABLE runs ADD COLUMN failed_sources TEXT;  -- JSON-encoded list[str] of adapter names that failed this run, or NULL/'[]'
```
(This is genuinely additive to an existing, already-populated table from Slice 0/1, so it is expressed as an explicit `ALTER TABLE` guarded by the sibling's `_ADDED_COLUMNS`-style "add column if not already present" check, rather than folded into `CREATE TABLE IF NOT EXISTS runs` which would not apply to an already-created table.)

---

## 4. Fetch/parse approach per source

### `app/sources/nse_bhavcopy.py` — NSE Bhavcopy EOD CSV
- **URL pattern:** NSE's official daily Bhavcopy CSV, named by date, e.g. `https://nsearchives.nseindia.com/content/historical/EQUITIES/{YYYY}/{MON}/cm{DD}{MON}{YYYY}bhav.csv.zip` (NSE serves this zipped; the research doc also flags `getbhavcopy.com` as a free mirror if NSE's own archive path proves unreliable/blocked — module-level constant for the base URL template so the exact path can be swapped without a code review, same pattern as Slice 1's `MONEYCONTROL_RSS_URL`). Date used is "most recent trading day" — if today's file isn't yet published (markets still open, or today is a holiday/weekend), fall back to the most recent previous trading day by walking backward up to 5 calendar days until a fetch succeeds or the budget is exhausted (then raise `SourceFetchError`).
- **Fetch:** `httpx.AsyncClient` GET of the `.zip`; unzip in-memory (stdlib `zipfile.ZipFile` + `io.BytesIO`, no temp file needed) to get the raw CSV bytes.
- **Parse:** stdlib `csv.DictReader` over the decoded CSV text. Expected columns (NSE Bhavcopy's standard layout): `SYMBOL`, `SERIES` (filter to `SERIES == "EQ"` only — excludes non-equity series), `OPEN`, `HIGH`, `LOW`, `CLOSE`, `PREVCLOSE`, `TOTTRDQTY` (volume), `TIMESTAMP` (trade date).
- **Scope of tickers fetched:** NOT every one of NSE's ~2000 listed symbols — this slice filters Bhavcopy rows down to a small watchlist (module-level constant list, e.g. a few dozen large/liquid NSE symbols, or — simpler and sufficient for this slice — every symbol that already appears as a `ticker` on some other source's `NormalizedItem` in this run, e.g. Screener.in's candidate list below). **Judgment call:** keep it simple for Slice 2 — fetch the full day's CSV (NSE publishes the whole market in one file regardless) but only normalize rows for a fixed small watchlist constant (`WATCHLIST_TICKERS`, documented in the module, e.g. 20-30 liquid large/mid-cap NSE symbols) rather than normalizing ~2000 rows into `sweep_items` every run. This keeps the sweep dataset's size sane; the real stock-universe-selection logic belongs to the later Haiku sweep stage (Slice 4+), not to sourcing.
- **Normalization:** one `NormalizedItem` per watchlisted ticker: `source="nse_bhavcopy"`, `headline=f"{symbol} EOD — close {close}"`, `url=` the Bhavcopy file's own URL (there's no per-row URL; the file URL is the best available citation target), `published_at=` the trade date (midnight UTC of that date), `snippet=make_snippet(f"Close {close}, prev close {prev_close}, volume {volume}")` (always short — never raw CSV row text), `ticker=symbol`, `close`, `prev_close`, `volume` populated.
- **Failure mode:** HTTP error, zip-extraction error, or CSV missing expected columns → raise `SourceFetchError`; walking-backward date-fallback logic exhausting its budget also raises `SourceFetchError`.

### `app/sources/screener_in.py` — Screener.in fundamentals
- **URL pattern:** `https://www.screener.in/company/{SYMBOL}/` (Screener.in's canonical per-company page; `{SYMBOL}` is the NSE ticker, consistent with the watchlist used by the Bhavcopy adapter — same `WATCHLIST_TICKERS` constant, imported from a shared `app/sources/watchlist.py` to avoid duplicating the list in two adapter modules).
- **Fetch:** `httpx.AsyncClient` GET per ticker, sequential with a small randomized delay between requests (`asyncio.sleep(random.uniform(2, 5))`, per the research doc's explicit guidance: "use randomized 2-5s delays, realistic user-agent, no concurrency" for Screener.in specifically — this is the one adapter in this slice that must NOT be fetched concurrently with itself across tickers, unlike Bhavcopy/RSS which are single-fetch-per-run).
- **Parse:** HTML parsing via `selectolax` (`HTMLParser(html).css_first(...)`) — chosen over `beautifulsoup4` for this project because it has fewer transitive dependencies and is fast enough for a 20-30-page sequential crawl; if `selectolax`'s CSS-selector ergonomics prove awkward against Screener.in's actual DOM at implementation time, falling back to `beautifulsoup4` is an acceptable substitution with no architectural impact (documented here as the one adapter where the exact parsing library is a soft, not hard, decision). Target DOM elements: Screener.in's top summary ratios table (P/E, market cap are both rendered in a `#top-ratios` list of `<li>` elements with a label `<span>` and value `<span>`, per Screener.in's known page structure) — exact selector confirmed/adjusted at implementation time against a real fetched page, since Screener.in's markup is explicitly flagged as fragile (research §"Source fragility").
- **Normalization:** one `NormalizedItem` per ticker: `source="screener_in"`, `headline=f"{symbol} fundamentals"`, `url=` the company page URL, `published_at=` time of fetch (Screener.in pages don't carry a clear "as of" date for every field; using fetch time is an honest, documented simplification), `snippet=make_snippet(f"P/E {pe_ratio}, market cap ₹{market_cap_cr} cr")`, `ticker=symbol`, `pe_ratio`, `market_cap_cr` populated.
- **Failure mode:** HTTP error, 404 (delisted/renamed ticker), or the expected ratios table missing from the DOM → caught **per ticker** (not per whole adapter — one bad ticker must not sink the other 19-29), logged, that ticker's row simply omitted; the adapter's `fetch()` itself only raises `SourceFetchError` for a total failure (e.g., Screener.in itself unreachable for every ticker), consistent with returning a partial list being the normal/expected outcome for this specific adapter.

### `app/sources/trading_economics.py` — Trading Economics macro calendar
- **URL pattern:** Trading Economics' free calendar page/feed for India, e.g. `https://tradingeconomics.com/india/calendar` (page-scrape) — Trading Economics also exposes a free-tier JSON API (per research doc: "API with JSON/CSV export") but that tier requires an API key signup; **default to the public calendar page scrape** to keep this adapter key-free and consistent with the spec's "no paid APIs... no required signups" framing, while noting the JSON API as a strictly-better future swap if the user later wants to register for a free key (flagged, not decided — no signup is performed in this slice).
- **Fetch:** `httpx.AsyncClient` GET of the calendar page, once per run (macro calendar changes infrequently intraday; once-daily polling is explicitly low-risk per the research doc).
- **Parse:** HTML parsing (same library choice as Screener.in — `selectolax`) targeting the calendar table's rows: each row has a date, an indicator name (e.g. "Inflation Rate YoY"), and a value/forecast/previous triple.
- **Normalization:** one `NormalizedItem` per calendar row within a bounded recent/near-term window (e.g. last 7 days + next 7 days — a module constant, since the full calendar can span months and only near-term items are relevant to a days-to-two-weeks swing horizon per the spec's problem statement): `source="trading_economics"`, `headline=indicator_name`, `url=` the calendar page URL, `published_at=` the row's event date, `snippet=make_snippet(f"Actual {value}, forecast {forecast}, previous {previous}")`, `ticker=None` (macro-level, not stock-specific — intentionally the one adapter in this slice that never populates `ticker`), `indicator_name`, `indicator_value` (the "Actual" value, or forecast if actual isn't yet published) populated.
- **Failure mode:** HTTP error or the calendar table missing from the DOM → raise `SourceFetchError` for the whole adapter (no natural per-row partial-failure concept here, unlike Screener.in).

---

## 5. Aggregator design (`app/sources/aggregator.py`)

```python
class SourcingAggregator:
    """Calls every configured SourceAdapter concurrently and merges results,
    isolating failures per adapter so one source going down never takes
    down sourcing for the others. Directly mirrors the sibling project's
    RealSourcingPort._query_companies pattern (asyncio.gather with
    return_exceptions=True, failures recorded by adapter name, run
    continues with the partial result)."""

    def __init__(self, adapters: list[SourceAdapter] | None = None):
        self.adapters = adapters or [
            MoneycontrolRSSAdapter(),
            NSEBhavcopyAdapter(),
            ScreenerInAdapter(),
            TradingEconomicsAdapter(),
        ]

    async def fetch_all(self) -> tuple[list[NormalizedItem], list[str]]:
        results = await asyncio.gather(
            *(adapter.fetch() for adapter in self.adapters),
            return_exceptions=True,
        )
        items: list[NormalizedItem] = []
        failed: list[str] = []
        for adapter, result in zip(self.adapters, results, strict=True):
            if isinstance(result, BaseException):
                log.warning("sourcing: %s failed: %r", adapter.name, result)
                failed.append(adapter.name)
            else:
                items.extend(result)
        return items, sorted(failed)
```

- **Isolation mechanism:** `asyncio.gather(..., return_exceptions=True)` — an exception from any one adapter's `fetch()` is captured as a value in the `results` list rather than propagating and cancelling the sibling tasks; this is the exact mechanism the sibling project uses, reused verbatim rather than reinvented.
- Each adapter is independently constructed and independently fetches (no shared mutable state between adapters); Screener.in's internal per-ticker sequential-with-delay behavior (§4) is entirely inside that one adapter's `fetch()` call and does not block/serialize the other adapters relative to each other — `gather` still runs Bhavcopy/RSS/Trading-Economics concurrently with Screener.in's slower sequential crawl.
- The orchestrator (`run_orchestrator.py`) calls `SourcingAggregator().fetch_all()` once, persists all returned `items` via `db.insert_sweep_items` (one bulk call, same as Slice 1), and writes `failed_sources` (JSON-encoded) onto the `runs` row.
- A **total** sourcing wipeout (all four adapters fail) is still not a run failure — `items` is simply `[]`, `failed_sources` lists all four, and the run proceeds to the (still-fake, per Slice 0/1) idea-assembly step and completes normally. This preserves Slice 1's "sourcing failure is never a run failure" guarantee at the aggregate level, not just the single-adapter level.

---

## 6. Step-by-step implementation sequence

1. `app/sources/base.py` — extend `NormalizedItem` with the new optional fields (§2); update `test_sources_base.py` if needed (new fields default to `None`, no behavior change for existing tests).
2. `app/db.py` — extend `sweep_items` DDL (§3) and `insert_sweep_items` to write the new columns; add the `runs.failed_sources` column (additive `ALTER TABLE`, guarded). Verify manually via `sqlite3 <db> ".schema sweep_items"` / `.schema runs"`.
3. `app/sources/watchlist.py` — define `WATCHLIST_TICKERS` (shared by Bhavcopy and Screener.in), a module constant list of ~20-30 NSE symbols.
4. `tests/fixtures/bhavcopy_sample.csv` — canned CSV fixture.
5. `app/sources/nse_bhavcopy.py` — adapter implementation (fetch → unzip → parse → filter to watchlist → normalize).
6. `tests/test_nse_bhavcopy.py` — fixture parse test + retention test, stubbed HTTP (no real network in CI).
7. `tests/fixtures/screener_sample.html` — canned fixture.
8. `app/sources/screener_in.py` — adapter implementation (sequential per-ticker fetch with delay, per-ticker failure isolation, HTML parse).
9. `tests/test_screener_in.py` — fixture parse test, per-ticker-failure test, retention test; stub the delay (`delay_seconds=0` injectable, or monkeypatch `asyncio.sleep`) so tests run fast.
10. `tests/fixtures/trading_economics_sample.html` — canned fixture.
11. `app/sources/trading_economics.py` — adapter implementation.
12. `tests/test_trading_economics.py` — fixture parse test + retention test.
13. `app/sources/aggregator.py` — `SourcingAggregator` (§5).
14. `tests/test_aggregator.py` — partial-failure test (one stub adapter raises, others return canned items; assert merged partial result + correct `failed_sources` naming).
15. `app/run_orchestrator.py` — swap the Slice-1 single-adapter call for `SourcingAggregator().fetch_all()`; persist `failed_sources` onto the run row.
16. `tests/test_run_orchestrator_sourcing.py` — update/extend to exercise the aggregator path (multi-adapter stub list) instead of Slice 1's single hardcoded adapter.
17. `app/routers/run.py`, `templates/index.html`, `static/js/run.js` — surface `failed_sources` and the grouped multi-source "Sources seen" section.
18. Manual smoke test (§8) against all four live sources.
19. Run full suite (`pytest tests/ -v`), fix anything red; confirm Slice 0/Slice 1 tests still pass unmodified (regression).

---

## 7. Test files and test cases

Run with: `pytest tests/ -v`

### `tests/test_nse_bhavcopy.py`
- `test_parses_fixture_csv_into_expected_items` — fixture CSV with 4 rows (3 on the watchlist, 1 not) → `fetch()` returns exactly 3 `NormalizedItem`s, each with correct `close`/`prev_close`/`volume`/`ticker`, `EQ`-series filter applied correctly (a non-`EQ` row in the fixture is excluded).
- `test_retention_guarantee` — snippet for every Bhavcopy item is short/bounded (never the raw CSV row text).
- `test_fetch_raises_on_missing_file` — stubbed 404/unreachable response → `SourceFetchError`.
- `test_date_fallback_walks_backward` — stubbed "today's file 404s, yesterday's succeeds" scenario → `fetch()` succeeds using yesterday's file.

### `tests/test_screener_in.py`
- `test_parses_fixture_html_into_expected_item` — canned HTML fixture → correct `pe_ratio`/`market_cap_cr`/`ticker`.
- `test_one_ticker_failure_does_not_block_others` — stub HTTP responses where one ticker 404s and two succeed → `fetch()` returns 2 items, not an exception, not 0 items.
- `test_retention_guarantee` — snippet is a short formatted string, never raw page HTML/text.
- `test_total_failure_raises` — all tickers fail → `SourceFetchError` raised (not a silently-empty success).

### `tests/test_trading_economics.py`
- `test_parses_fixture_into_expected_items` — canned calendar fixture → correct `indicator_name`/`indicator_value`, `ticker is None` for every item.
- `test_filters_to_near_term_window` — fixture includes one row far outside the +/-7-day window → excluded from the result.
- `test_retention_guarantee` — snippet bounded.
- `test_fetch_raises_on_missing_table` — fixture HTML with no calendar table → `SourceFetchError`.

### `tests/test_aggregator.py`
- `test_merges_results_from_all_succeeding_adapters` — 4 stub adapters, all succeed with distinct canned items → `fetch_all()` returns the union, `failed_sources == []`.
- `test_one_adapter_failure_isolated` — 3 stub adapters succeed, 1 raises → `fetch_all()` returns the 3 successful adapters' items, `failed_sources == [<the one that failed>]`, no exception propagates out of `fetch_all()`.
- `test_all_adapters_fail_returns_empty_not_exception` — all 4 stub adapters raise → `fetch_all()` returns `([], [all four names, sorted])`, does not raise.

### `tests/test_run_orchestrator_sourcing.py` (extended from Slice 1)
- `test_run_persists_merged_multi_source_items` — orchestrator wired to a stub `SourcingAggregator` (or 4 stub adapters) returning a mix of sources → `sweep_items` rows reflect all sources together, correctly tagged by `source`.
- `test_run_records_failed_sources_on_run_row` — one stub adapter fails → the `runs.failed_sources` column (JSON-decoded) contains exactly that adapter's name after the run completes.
- `test_run_completes_with_zero_sources_available` — all stub adapters fail → run still reaches `status='complete'`, `sweep_items` has zero rows for that run, idea card (still Slice 0/1's fake) still renders.

Command to run all tests: `pytest tests/ -v`

---

## 8. How to run / demonstrate the slice

**Start the server** (unchanged):
```
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Manual demonstration steps:**
1. Load `http://127.0.0.1:8000/`, click "Run now," wait for completion.
2. The "Sources seen" section now shows items grouped by source: Moneycontrol headlines, NSE Bhavcopy EOD rows (for the watchlist tickers), Screener.in fundamentals (P/E, market cap per ticker), and Trading Economics calendar entries — all in one run.
3. Spot-check correctness for one known ticker (e.g. `RELIANCE`, if on the watchlist): confirm the displayed Bhavcopy close price and Screener.in P/E/market-cap look plausible against the live sites opened manually in a browser.
4. Inspect the DB directly: `sqlite3 ~/.swingtrade/app.db "SELECT source, count(*) FROM sweep_items WHERE run_id = (SELECT max(id) FROM runs) GROUP BY source;"` — confirm rows exist for all four sources (or fewer, if one genuinely failed that day — check `failed_sources` on the run row in that case).
5. Simulate one adapter failure (e.g., temporarily break the Screener.in URL constant) and re-run — confirm the run completes, the other three sources' data still appears, and the UI's "sources unavailable this run" notice names `screener_in`.
6. `sqlite3 ~/.swingtrade/app.db ".schema sweep_items"` — visually confirm no `body`/`content`/`full_text`/`html` column exists anywhere in the extended schema.

---

## 9. Acceptance criteria and verification evidence

- [ ] A run fetches and normalizes data from all four configured sources into the shared base shape with source-specific extensions where applicable. **Evidence:** manual steps 2-4; `test_merges_results_from_all_succeeding_adapters`, `test_run_persists_merged_multi_source_items` passing.
- [ ] Zero full-article-body or full-page-content fields are persisted from any adapter. **Evidence:** `test_retention_guarantee` in each of the three new adapter test files; schema review confirming no body/content/html column exists (manual step 6).
- [ ] If any single adapter fails, the run still completes with the remaining sources' data. **Evidence:** `test_one_adapter_failure_isolated`, `test_run_records_failed_sources_on_run_row` passing; manual step 5.
- [ ] If all adapters fail, the run still completes (does not crash or hang). **Evidence:** `test_all_adapters_fail_returns_empty_not_exception`, `test_run_completes_with_zero_sources_available` passing.
- [ ] Screener.in fetching respects the research-documented low-risk polling pattern (sequential, randomized 2-5s delay, no concurrency across its own tickers). **Evidence:** code review of `app/sources/screener_in.py`'s fetch loop.
- [ ] `pytest tests/ -v` — all tests pass, zero skips/xfails, including Slice 0 and Slice 1's tests still passing unmodified (regression).
- [ ] One manual full-sweep run reviewed by the user, confirming all four sources appear together and values look sane for at least one known ticker. **Evidence:** manual steps 2-3, user sign-off.

Slice 2 is complete only when every checkbox above is verified with the stated evidence, not merely claimed.
