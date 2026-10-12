# Slice 1 — Detailed Technical Plan: First Real Source Adapter (Moneycontrol RSS)

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 1 only
**Inputs (locked, not reopened):** `tech-spec.md`, `initial-plan.md`, `vertical-slice-plan.md` (Slice 1 section, lines 96-134), `plan-detailed/slice-0.md` (established layout/schema/conventions)
**Precedent:** sibling `ai-job-finder-console`'s `app/sourcing/real_sourcing.py` (per-platform fetch, `asyncio.gather(..., return_exceptions=True)`, failure recorded by name, run continues) and `app/fakes/fake_sourcing.py` (canned-list fake with `calls` recording, injectable failure). This project's version is lighter (no dedup/discovery/role-keyword matching — those are job-finder-specific), but reuses the exact failure-isolation shape.

**Builds on Slice 0 exactly as established:** FastAPI app in `app/`, SQLite via `app/db.py` (`SCHEMA_SQL` executescript pattern, `get_connection()`, `db_session()`), `run_lock.py` singleton, `run_orchestrator.py` (`RunOrchestrator.execute_run`), `routers/run.py`, Jinja2 `templates/`, `static/js/`. No schema migration machinery is introduced — new tables are added via `CREATE TABLE IF NOT EXISTS` in the same `SCHEMA_SQL` string, consistent with Slice 0's "name placeholder columns up front" philosophy.

---

## 1. Files to create / modify

| Path | Change | Responsibility |
|---|---|---|
| `app/sources/__init__.py` | create | Empty, package marker. |
| `app/sources/base.py` | create | `NormalizedItem` dataclass + `SourceAdapter` Protocol + the retention-safe snippet-truncation helper. |
| `app/sources/moneycontrol_rss.py` | create | Fetch Moneycontrol's RSS feed(s) over HTTP, parse the XML, normalize each `<item>` into a `NormalizedItem`. |
| `app/db.py` | modify | Add `sweep_items` table to `SCHEMA_SQL`; add `insert_sweep_items(conn, run_id, items)` and `get_sweep_items(conn, run_id)` helper functions. |
| `app/run_orchestrator.py` | modify | `execute_run` gains a real sourcing step: call `moneycontrol_rss.fetch()`, catch adapter failure (log + continue, do not abort the run), persist returned items via `db.insert_sweep_items`. Idea output stays the Slice-0 fake idea (unchanged). |
| `app/routers/run.py` | modify | `GET /api/run/last` (and/or a new endpoint) response gains a `sources` list reflecting this run's persisted `sweep_items`. |
| `app/templates/index.html` | modify | Add a "Sources seen" section below the idea card(s), listing fetched headlines (headline, source, date, link). |
| `app/static/js/run.js` | modify | Render the new `sources` array from `GET /api/run/last` into the "Sources seen" section. |
| `pyproject.toml` | modify | Add `feedparser` dependency. |
| `tests/fixtures/moneycontrol_sample.xml` | create | A small canned RSS XML fixture (3-4 `<item>`s, one with a long `<description>` to exercise truncation) used by the adapter unit test. |
| `tests/test_moneycontrol_rss.py` | create | Fixture-based parse test + retention-guarantee test for this adapter. |
| `tests/test_sources_base.py` | create | Retention-guarantee test at the `NormalizedItem`/truncation-helper level (adapter-agnostic). |
| `tests/test_run_orchestrator_sourcing.py` | create | Integration test: orchestrator run persists items from a stubbed adapter; orchestrator run survives a stubbed adapter failure. |

No files are removed. Slice 0's `FAKE_IDEA` constant and its insertion logic in `run_orchestrator.py` are untouched — this slice adds a parallel sourcing step, it does not touch idea assembly.

---

## 2. The shared `NormalizedItem` shape (`app/sources/base.py`)

```python
from __future__ import annotations

import dataclasses
import datetime as dt
from typing import Protocol

SNIPPET_MAX_CHARS = 280  # ~1-2 sentences; hard cap, documented convention (spec FR8)


def make_snippet(raw_text: str, max_chars: int = SNIPPET_MAX_CHARS) -> str:
    """Truncates arbitrary input text down to the retention-safe snippet
    length. This is the ONLY function in the codebase allowed to turn a raw
    description/body string into a `NormalizedItem.snippet` value — every
    adapter must route through it rather than assigning a raw string
    directly, so the retention guarantee holds structurally, not just by
    adapter-author discipline. Collapses whitespace, strips HTML tags if
    present (RSS <description> fields are frequently HTML-escaped markup),
    then truncates to `max_chars`, appending "..." if truncated."""
    ...


@dataclasses.dataclass(frozen=True)
class NormalizedItem:
    source: str                 # e.g. "moneycontrol_rss" — adapter's fixed name
    headline: str                # short title/label, NOT the full body
    url: str                     # canonical link to the original source
    published_at: dt.datetime    # UTC; adapters must parse/normalize feed-local timestamps
    snippet: str                 # <= SNIPPET_MAX_CHARS chars; MUST be produced via make_snippet()
    ticker: str | None = None    # NSE/BSE symbol if the adapter can associate one; None for most RSS items

    def __post_init__(self) -> None:
        if len(self.snippet) > SNIPPET_MAX_CHARS + 3:  # +3 tolerates the "..." suffix
            raise ValueError(
                f"snippet exceeds retention-safe max ({SNIPPET_MAX_CHARS} chars); "
                "route all snippet text through make_snippet() — never assign raw body text"
            )


class SourceAdapter(Protocol):
    name: str

    async def fetch(self) -> list[NormalizedItem]:
        """Fetches and normalizes this source's current items. Must never
        raise for 'this source has nothing new right now' (return [] instead)
        — only raise for genuine fetch/parse failure, which the caller (the
        orchestrator in Slice 1, the aggregator in Slice 2) will catch and
        isolate per-adapter."""
        ...
```

Design intent: `NormalizedItem.__post_init__` makes the dataclass itself incapable of silently holding a full article body — any attempt to construct one with an over-length snippet raises immediately at construction time, not just at a later "retention test" checkpoint. This is the "make the schema itself incapable" requirement applied at the Python-object layer; §3 applies the same idea at the SQLite layer.

`ticker` is `None` for virtually all Moneycontrol RSS items in this slice (headline→ticker mapping is an LLM-sweep-stage concern per the vertical-slice-plan, not a sourcing concern) — included now because Slice 2's Bhavcopy/Screener.in adapters always populate it, and the shared shape should not need to change between Slice 1 and Slice 2.

---

## 3. New SQLite schema: `sweep_items` table

Added to `app/db.py`'s `SCHEMA_SQL` (appended to the existing Slice-0 DDL, same `executescript` string):

```sql
CREATE TABLE IF NOT EXISTS sweep_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    source          TEXT NOT NULL,              -- adapter name, e.g. 'moneycontrol_rss'
    headline        TEXT NOT NULL,
    url             TEXT NOT NULL,
    published_at    TEXT NOT NULL,               -- ISO 8601 UTC
    snippet         TEXT NOT NULL CHECK (length(snippet) <= 300),  -- hard DB-level cap; see note below
    ticker          TEXT,                        -- NULL when adapter can't associate a symbol
    fetched_at      TEXT NOT NULL                -- ISO 8601 UTC; when THIS run's fetch happened (distinct from published_at)
);

CREATE INDEX IF NOT EXISTS idx_sweep_items_run_id ON sweep_items (run_id);
```

**Retention-safety-by-design notes:**
- There is no column of unbounded/body-sized intent anywhere in this table — only `headline`, `url`, `published_at`, `snippet`, `ticker`, plus bookkeeping (`id`, `run_id`, `source`, `fetched_at`). There is deliberately no `body`, `content`, `full_text`, `description`, or `html` column — the schema cannot hold a full article even if application code tried to pass one in.
- The `CHECK (length(snippet) <= 300)` constraint is a second, DB-level enforcement layer independent of the Python-level `NormalizedItem.__post_init__` check in §2 (300 = `SNIPPET_MAX_CHARS` + headroom for the "..." suffix and minor encoding variance; the two constants must be kept in sync — documented as a comment at both definition sites). A write that violates this raises `sqlite3.IntegrityError` rather than silently truncating at the DB layer — truncation is `make_snippet()`'s job, upstream of the DB; the CHECK exists purely as a defense-in-depth backstop, not the primary truncation mechanism.
- `headline` has no explicit length cap in the schema (headlines are inherently short; a cap is not needed for the "no full body" guarantee — the retention concern is specifically about `snippet`/body-length fields, not titles).
- Source-specific extra fields (Slice 2's Bhavcopy OHLC/volume, Screener.in fundamentals, Trading Economics indicator values) are deliberately NOT added to `sweep_items` in this slice — Slice 2 extends this table (see Slice 2's plan §3) with nullable columns, since Slice 1 only needs the shared base shape for one news-only source.

**`db.py` additions:**
- `insert_sweep_items(conn, run_id: int, items: list[NormalizedItem]) -> None` — bulk `executemany` insert; sets `fetched_at = now()` once for the whole batch.
- `get_sweep_items(conn, run_id: int) -> list[sqlite3.Row]` — `SELECT * FROM sweep_items WHERE run_id = ? ORDER BY published_at DESC`.

---

## 4. Fetch/parse approach: Moneycontrol RSS

- **Library:** `feedparser` (pure-Python, handles RSS 2.0/Atom variance, malformed-XML tolerance, and date parsing via `entry.published_parsed` — far less error-prone than hand-rolling `xml.etree` against a feed whose exact dialect isn't guaranteed stable, consistent with research note "Source fragility... can change without notice"). Added as a new dependency in `pyproject.toml`.
- **HTTP fetch:** `httpx.AsyncClient` (already a Slice-0/sibling-precedent dependency) performs the GET with a short timeout (`REQUEST_TIMEOUT = 8.0`, mirroring the sibling's constant name/value) and a realistic `User-Agent` header (per research note: Moneycontrol RSS has low ToS risk at this polling frequency, but a generic Python UA is still worth avoiding).
- **URL:** Moneycontrol's markets/business RSS feed — concrete default `https://www.moneycontrol.com/rss/business.xml` (Moneycontrol publishes several topic feeds under `moneycontrol.com/rss/*.xml`; `business.xml` is the broadest company-news feed and the reasonable default for "news/earnings/deals" per the research doc). Stored as a module-level constant `MONEYCONTROL_RSS_URL` so it can be swapped if the exact feed path changes without a code review.
- **Parse shape expected:** `feedparser.parse(raw_bytes)` returns a `FeedParserDict` with `.entries`, each entry exposing `.title`, `.link`, `.published_parsed` (a `time.struct_time`, convert via `datetime.fromtimestamp(calendar.timegm(...), tz=UTC)` — UTC-safe, avoids local-timezone bugs), and `.summary`/`.description` (raw, HTML-escaped body-ish text — this is exactly the field that must NEVER be stored whole; it only ever flows through `make_snippet()`).
- **Normalization into `NormalizedItem`:**
  - `source = "moneycontrol_rss"`
  - `headline = entry.title.strip()`
  - `url = entry.link`
  - `published_at` = parsed from `entry.published_parsed` (fallback: `datetime.now(UTC)` if the feed omits a date, logged as a warning — do not fail the whole fetch over one malformed entry's date)
  - `snippet = make_snippet(entry.get("summary", ""))`
  - `ticker = None` (RSS items are not pre-mapped to a symbol in this slice)
- **Adapter class shape:**
  ```python
  class MoneycontrolRSSAdapter:
      name = "moneycontrol_rss"

      def __init__(self, url: str = MONEYCONTROL_RSS_URL, http_client: httpx.AsyncClient | None = None):
          self.url = url
          self.http_client = http_client

      async def fetch(self) -> list[NormalizedItem]:
          # uses self.http_client if injected (tests), else opens a short-lived
          # httpx.AsyncClient for this call only — same pattern as sibling's
          # RealSourcingPort.fetch_candidates()
          ...
  ```
- A malformed/empty feed response (HTTP error, non-XML body, zero entries) results in `fetch()` either returning `[]` (zero entries is not an error) or raising a plain `Exception` subclass — e.g. `SourceFetchError` defined in `app/sources/base.py` — for genuine fetch/transport failures (non-2xx, timeout, connection error, XML parse failure). The adapter itself never swallows a real failure into an empty list; that decision belongs to the caller (§5).

---

## 5. Per-adapter failure isolation (orchestrator-level, Slice 1 scope)

Only one adapter exists in this slice, but the isolation pattern must be identical to what Slice 2's aggregator will reuse across many adapters (so it is designed once, correctly, here):

- `run_orchestrator.py`'s sourcing step wraps the adapter call:
  ```python
  try:
      items = await MoneycontrolRSSAdapter().fetch()
  except Exception as exc:          # SourceFetchError or any unexpected failure
      log.warning("sourcing: moneycontrol_rss failed: %r", exc)
      items = []
      failed_sources = ["moneycontrol_rss"]
  else:
      failed_sources = []
  db.insert_sweep_items(conn, run_id, items)
  ```
- This mirrors the sibling's `RealSourcingPort._query_companies` pattern (`asyncio.gather(..., return_exceptions=True)`, failure recorded by name, run continues) collapsed to the single-adapter case; Slice 2's aggregator will promote this to a real `gather`-based multi-adapter loop.
- A sourcing failure is **never** a run failure: the run still proceeds to the (still-fake, per Slice 0) idea-assembly step and completes with `status='complete'`, exactly as it would with zero items persisted. This is the acceptance-criteria-mandated resilience behavior ("If the RSS feed is unreachable, the run still completes").
- `failed_sources` is computed but not yet persisted to a dedicated column in Slice 1 (no spec requirement to surface it yet); it is logged only. Slice 2's aggregator plan may choose to surface it in the run record if useful — flagged there, not decided here, to avoid a schema change later needing to be retrofitted onto Slice 1's narrower scope. (Judgment call: logging only, no persistence, keeps Slice 1 minimal — acceptable since no acceptance criterion in the vertical-slice-plan requires UI visibility of failed sources yet.)

---

## 6. Step-by-step implementation sequence

1. `pyproject.toml` — add `feedparser` dependency; `uv sync`/`pip install -e .` (whichever the sibling project's actual install mechanism is) to confirm resolution.
2. `app/sources/__init__.py`, `app/sources/base.py` — `NormalizedItem`, `make_snippet`, `SourceAdapter` Protocol, `SourceFetchError`. Unit-test `make_snippet` and the `__post_init__` guard in isolation before writing any adapter.
3. `app/db.py` — add `sweep_items` DDL to `SCHEMA_SQL`, add `insert_sweep_items`/`get_sweep_items`. Verify manually: `python -c "from app.db import get_connection; get_connection()"` then inspect `sqlite3 <db> '.schema sweep_items'`.
4. `tests/fixtures/moneycontrol_sample.xml` — hand-write a 3-4-item RSS fixture (one item with a deliberately long `<description>` to exercise truncation).
5. `app/sources/moneycontrol_rss.py` — adapter implementation.
6. `tests/test_moneycontrol_rss.py` — fixture parse test + retention test (see §8) against the adapter, using a stubbed `httpx.AsyncClient`/`feedparser.parse` input rather than a live network call.
7. `app/run_orchestrator.py` — wire the sourcing step (try/except/log pattern from §5) into `execute_run`, before the existing fake-idea insertion logic; persist via `insert_sweep_items`.
8. `tests/test_run_orchestrator_sourcing.py` — integration tests against a stubbed adapter (success case persists items; failure case still completes the run with zero items and `status='complete'`).
9. `app/routers/run.py` — extend `GET /api/run/last` response with a `sources` array (`db.get_sweep_items`, serialized).
10. `app/templates/index.html` + `app/static/js/run.js` — render the "Sources seen" section.
11. Manual smoke test (§9) against the live feed.
12. Run full suite (`pytest tests/ -v`), fix anything red.

---

## 7. Test files and test cases

Run with: `pytest tests/ -v`

### `tests/test_sources_base.py`
- `test_make_snippet_truncates_long_text` — a 2000-char input is truncated to `SNIPPET_MAX_CHARS` (plus "..." suffix), never stored whole.
- `test_make_snippet_strips_html_tags` — HTML-escaped `<description>`-style input (e.g. `"<p>Reliance <b>surges</b> on...</p>"`) comes out as plain text.
- `test_normalized_item_rejects_oversized_snippet` — directly constructing `NormalizedItem(..., snippet="x" * 1000)` (bypassing `make_snippet`) raises `ValueError` — proves the dataclass itself refuses to hold a full body, not just that `make_snippet` happens to truncate correctly.

### `tests/test_moneycontrol_rss.py`
- `test_parses_fixture_into_expected_items` — load `tests/fixtures/moneycontrol_sample.xml` via a stubbed HTTP response, call `adapter.fetch()`, assert the returned list has the expected count, and each item's `source == "moneycontrol_rss"`, `headline`, `url`, `published_at` (correct UTC datetime), and `ticker is None`.
- `test_long_description_item_produces_bounded_snippet` — the fixture's deliberately-long-description item produces a `snippet` of length `<= SNIPPET_MAX_CHARS + 3`, never containing the full original description text verbatim.
- `test_fetch_raises_on_http_error` — a stubbed 500/timeout response causes `fetch()` to raise `SourceFetchError` (not silently return `[]`).
- `test_fetch_returns_empty_list_on_zero_entries` — a fixture with a valid-but-empty `<channel>` returns `[]` without raising.

### `tests/test_run_orchestrator_sourcing.py`
- `test_run_persists_fetched_items` — inject a stub adapter returning 3 canned `NormalizedItem`s into the orchestrator (constructor/parameter injection, not monkeypatching the module-level class, mirroring the sibling's injectable-port style); run `execute_run`; assert `sweep_items` table has exactly 3 rows for that `run_id` matching the stub's data.
- `test_run_completes_when_adapter_raises` — inject a stub adapter whose `fetch()` raises `SourceFetchError`; run `execute_run`; assert the run still reaches `status='complete'` (not `'error'`) and `sweep_items` has zero rows for that run.
- `test_sweep_items_never_contain_full_body` — a retention-guarantee integration check: run with a stub adapter configured to attempt to pass an oversized snippet; assert the orchestrator either rejects it before persistence (propagating the `ValueError` from `NormalizedItem.__post_init__`) or — preferably — assert this scenario cannot occur because the stub itself can only be constructed via `NormalizedItem`, which already enforces the cap; this test's real purpose is to assert the DB `CHECK` constraint fires if the Python-level guard were ever bypassed (construct the row via raw SQL with an oversized snippet directly against `sweep_items` and assert `sqlite3.IntegrityError`).

Command to run all tests: `pytest tests/ -v`

---

## 8. How to run / demonstrate the slice

**Start the server** (unchanged from Slice 0):
```
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Manual demonstration steps:**
1. Load `http://127.0.0.1:8000/` — existing Slice-0 UI (Run now button, last-run idea card) renders as before.
2. Click "Run now." Wait for completion (polling, as established in Slice 0).
3. The run detail/last-run view now shows a new **"Sources seen"** section beneath the idea card, listing real, current Moneycontrol headlines fetched during this run — each with headline text, source label (`moneycontrol_rss`), published date, and a clickable link to the original article.
4. Open the SQLite DB directly (`sqlite3 ~/.swingtrade/app.db "SELECT source, headline, length(snippet), url FROM sweep_items ORDER BY id DESC LIMIT 10;"`) and visually confirm: `length(snippet)` is always well under 300 for every row, and no column contains obviously-full-article text (spot check 2-3 rows against the live site to confirm the snippet is a short excerpt, not the whole piece).
5. Temporarily point `MONEYCONTROL_RSS_URL` at an unreachable host (or disconnect network) and re-run — confirm the run still completes (`status='complete'`), the idea card (still the Slice-0 fake) still renders, and the "Sources seen" section is simply empty rather than the page erroring.

---

## 9. Acceptance criteria and verification evidence

- [ ] A real run fetches current Moneycontrol RSS content and persists it with only `headline`/`source`/`published_at`/`url`/`snippet` fields. **Evidence:** manual step 3-4 above; `test_parses_fixture_into_expected_items` passing.
- [ ] No code path in the adapter or its persistence ever stores or returns full article body text. **Evidence:** `test_normalized_item_rejects_oversized_snippet`, `test_make_snippet_truncates_long_text`, `test_sweep_items_never_contain_full_body`, and the DB `CHECK (length(snippet) <= 300)` constraint existing in the schema (code review of `app/db.py`).
- [ ] If the RSS feed is unreachable, the run still completes. **Evidence:** `test_run_completes_when_adapter_raises` passing; manual step 5.
- [ ] `sweep_items` schema contains no column capable of holding a full article body (no `body`/`content`/`full_text`/`html` column exists). **Evidence:** code review of the DDL in §3; `sqlite3 <db> ".schema sweep_items"` output inspected directly.
- [ ] `pytest tests/ -v` — all tests pass, zero skips/xfails, including the new test files from this slice plus all of Slice 0's still passing (regression).
- [ ] The "Sources seen" UI section displays real, current headlines from a live run. **Evidence:** manual step 3, visually confirmed by the user.

Slice 1 is complete only when every checkbox above is verified with the stated evidence, not merely claimed.
