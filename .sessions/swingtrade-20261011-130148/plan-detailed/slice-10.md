# Slice 10 — Detailed Technical Plan: Run History Browsing (J3)

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 10 only
**Inputs (locked, not reopened):** `tech-spec.md` (FR13, J3), `initial-plan.md`, `vertical-slice-plan.md` (Slice 10 section, lines 450-484), `plan-detailed/slice-0.md` (schema, API conventions, polling pattern)
**Precedent repo:** `ai-job-finder-console` — note the sibling has **no dedicated history-listing endpoint or template**; its `app/routers/run.py` only has `GET /api/run/last` (most-recent-only) and `GET /api/run/{run_id}/results` (paginated results for one run, used for the *current* run's own pagination, not historical browsing). Slice 10 is net-new relative to the sibling, but reuses its JSON-shape and pagination conventions (`page`/`page_size` query params, `{"error": ...}` bodies, `db_session()` context manager).

**Locked decision carried forward from vertical-slice-plan.md (do not reopen):** history data (the `runs`/`ideas` rows) is populated progressively by every slice since Slice 0 — Slice 10 adds only read/browse capability, not new write paths. Per the user-approved note in the vertical-slice-plan, this slice is sequenced after Slice 9 so there is real, fully-assembled data to browse, even though persistence has technically existed since Slice 0.

---

## 1. Files to create/modify

| Path | Change |
|---|---|
| `app/routers/run.py` | **Modify.** Add `GET /api/runs` and `GET /api/run/{run_id}` handlers. |
| `app/history_store.py` | **Create.** Query functions: `list_runs(conn, limit, offset) -> list[dict]`, `get_run(conn, run_id) -> dict | None`, `get_ideas_for_run(conn, run_id) -> list[dict]`. Mirrors the separation the sibling keeps in `results_store.py` (DB-query logic lives outside the router). |
| `app/templates/history.html` | **Create.** New template — see §4 for "which template" reasoning. |
| `app/templates/index.html` | **Modify.** Add a "History" nav link pointing to `/history`. |
| `app/main.py` | **Modify.** Add `GET /history` route rendering `history.html`. |
| `app/static/js/history.js` | **Create.** Fetches `/api/runs`, renders the list; fetches `/api/run/{id}` on detail click, renders detail inline or navigates to a detail sub-view (see §4). |
| `app/static/css/main.css` | **Modify.** Add styles for the history list rows and detail view (reuse existing idea-card CSS classes from Slice 0/9 — no new visual language needed). |
| `tests/test_history_api.py` | **Create.** Integration tests per §6. |

No new tables, no migrations, no `ALTER TABLE`. This slice is 100% new read queries over the existing `runs`/`ideas` schema from `plan-detailed/slice-0.md` §2.

---

## 2. API contract

### `GET /api/runs`

Query params: `limit` (int, optional, default **50**, max **200**), `offset` (int, optional, default `0`).

Rationale for default limit of 50: this is a single-user, daily-or-less-frequency tool (tech-spec §7 assumption) — 50 runs is ~7 weeks of once-daily runs, comfortably more than needed for a single page of browsing, while staying small enough to never need a loading spinner. `offset`-based paging (not cursor-based) matches the sibling's `page`/`page_size` convention in spirit but uses `limit`/`offset` directly since there's no natural "page" concept for a reverse-chronological run list the way there is for a run's own paginated idea results.

Response, `200`, always (empty array if no runs exist yet):
```json
{
  "runs": [
    {
      "run_id": 12,
      "status": "complete",
      "started_at": "2026-10-12T09:00:00+00:00",
      "finished_at": "2026-10-12T09:00:47+00:00",
      "quick_sweep_skipped": false,
      "total_cost_usd": 0.0
    },
    {
      "run_id": 11,
      "status": "error",
      "started_at": "2026-10-11T09:00:00+00:00",
      "finished_at": "2026-10-11T09:00:03+00:00",
      "quick_sweep_skipped": false,
      "total_cost_usd": 0.0
    }
  ],
  "limit": 50,
  "offset": 0,
  "total_count": 12
}
```
- Ordered strictly by `id DESC` (reverse-chronological; `id` is monotonically increasing by construction, so this is equivalent to and cheaper than ordering by `started_at DESC`, and avoids any ambiguity from identical timestamps).
- `total_count` is a separate `SELECT COUNT(*) FROM runs` so the frontend can show "12 runs total" / decide whether a "load more" control is needed — cheap on SQLite at this scale (dozens-hundreds of rows, not millions).
- `total_cost_usd` is drawn directly from the column named in `plan-detailed/slice-0.md` §2 — until Slice 11 lands, this is always `0.0` (the placeholder default), which is expected and correct, not a bug introduced by Slice 10.
- No ideas are included in this list response (summary only, per the slice scope) — keeps the payload small regardless of `limit`.

### `GET /api/run/{run_id}`

Path param: `run_id` (int).

Response, `200`, when found — **same shape as Slice 0's `GET /api/run/last`** (per the task's explicit instruction), but for the given arbitrary id instead of always the most recent row:
```json
{
  "has_run": true,
  "run_id": 7,
  "status": "complete",
  "started_at": "2026-10-12T09:00:00+00:00",
  "finished_at": "2026-10-12T09:00:01+00:00",
  "quick_sweep_skipped": false,
  "total_cost_usd": 0.0,
  "ideas": [
    {
      "ticker": "RELIANCE",
      "entry": 2850.0,
      "target": 2990.0,
      "hold_days": 7,
      "tier": "green",
      "score": null,
      "rationale": "...",
      "citation_url": "https://example.com/fake-citation",
      "low_confidence": false
    }
  ],
  "disclaimer": "For personal informational use only. Not investment advice. Not a registered investment adviser. No trades are placed automatically — review and decide manually."
}
```
Ideas are ordered by the `rank` column ascending (per `slice-0.md` §2's `rank` column — "1 = best"), matching Slice 9's assembly ordering exactly as persisted; Slice 10 does not re-derive or re-sort anything, it reads `rank` as-is.

Response, `404`, when `run_id` does not exist:
```json
{ "error": "run not found" }
```
This 404 (not a `{"has_run": false}` 200, unlike Slice 0's `/api/run/last`) is intentional: `/api/run/last`'s `has_run: false` means "no runs exist in the whole system yet" (a legitimate, expected empty-DB state), whereas `GET /api/run/{run_id}` for a *specific, named* id that doesn't exist is a client error (bad link, stale bookmark, typo) — 404 is the correct signal, consistent with the sibling's own `run_results` handler (`raise HTTPException(status_code=404, ...)` for an unknown `run_id`, see `app/routers/run.py:81-82`).

---

## 3. `app/history_store.py` — exact functions

```python
def list_runs(conn, limit: int, offset: int) -> tuple[list[dict], int]:
    """Returns (rows, total_count). rows ordered by id DESC."""
    total_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    rows = conn.execute(
        "SELECT id, status, started_at, finished_at, quick_sweep_skipped, "
        "total_cost_usd FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [
        {
            "run_id": r["id"],
            "status": r["status"],
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
            "quick_sweep_skipped": bool(r["quick_sweep_skipped"]),
            "total_cost_usd": r["total_cost_usd"],
        }
        for r in rows
    ], total_count


def get_run(conn, run_id: int) -> dict | None:
    """Returns the run's own fields (no ideas) or None if run_id doesn't exist."""
    row = conn.execute(
        "SELECT id, status, started_at, finished_at, quick_sweep_skipped, "
        "total_cost_usd FROM runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "run_id": row["id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "quick_sweep_skipped": bool(row["quick_sweep_skipped"]),
        "total_cost_usd": row["total_cost_usd"],
    }


def get_ideas_for_run(conn, run_id: int) -> list[dict]:
    """Ordered by rank ASC. Returns [] if the run has no ideas (e.g. still
    running, errored before assembly, or quick-sweep-skipped with no new
    ideas to show)."""
    rows = conn.execute(
        "SELECT ticker, entry, target, hold_days, tier, score, rationale, "
        "citation_url, low_confidence FROM ideas WHERE run_id = ? ORDER BY rank ASC",
        (run_id,),
    ).fetchall()
    return [
        {
            "ticker": r["ticker"],
            "entry": r["entry"],
            "target": r["target"],
            "hold_days": r["hold_days"],
            "tier": r["tier"],
            "score": r["score"],
            "rationale": r["rationale"],
            "citation_url": r["citation_url"],
            "low_confidence": bool(r["low_confidence"]),
        }
        for r in rows
    ]
```

`app/routers/run.py` additions call these three functions and assemble the JSON response shapes from §2; the router layer owns HTTP concerns (404, query-param validation/clamping) and `history_store.py` owns SQL only — matching the sibling's `results_store.py`/router split.

---

## 4. Template/UI addition: `history.html` (new file) — reasoning

**Decision: add a separate `history.html`, not a view-toggle inside `index.html`.**

Reasoning:
- `index.html` (per Slice 0/9) is already doing real work: run-trigger button, polling loop, latest-run idea-card rendering, disclaimer. Folding a second, independently-navigable list+detail view into the same template/JS file via a show/hide toggle adds branching state (which view is "active," whether polling should keep running while the history view is shown) for no real benefit — the sibling project itself keeps distinct concerns in distinct templates where it has more than one (though in practice the sibling only ever had one главный template; there's no multi-page precedent to contradict this call).
- A separate route (`GET /history`) and template gives clean browser back/forward navigation and a bookmarkable/shareable URL per view, consistent with "simple server-rendered listing patterns" the task asks to reuse (plain Jinja2 page, not a SPA-style route).
- The history **list** view and the history **detail** view (one past run's full idea list) are combined into the same `history.html` template using a client-side state switch within `history.js` (list mode vs. detail mode), rather than two separate `.html` files — because both need the same "disclaimer footer" and layout shell, and the detail view reuses the exact same idea-card rendering function Slice 9 already wrote for `index.html` (factor that card-rendering function into `app/static/js/api.js` or a new tiny `app/static/js/cards.js` shared by both `run.js` and `history.js`, rather than duplicating it).

**`history.html` structure:**
```html
<!-- same head/CSS links as index.html -->
<body><div class="app">
  <nav><a href="/">Latest run</a> <a href="/history">History</a></nav>
  <main class="main">
    <div id="history-list-view">
      <h1>Past runs</h1>
      <div id="history-rows"></div>   <!-- one row per run: id, status, started_at, skip-flag, cost; click -> detail -->
    </div>
    <div id="history-detail-view" hidden>
      <button id="back-to-list">&larr; Back to list</button>
      <div id="history-detail-meta"></div>
      <div class="grid" id="history-detail-ideas"></div>  <!-- reuses index.html's idea-card markup/CSS classes -->
      <div class="disclaimer">...</div>
    </div>
  </main>
</div>
<script src="/static/js/api.js"></script>
<script src="/static/js/cards.js"></script>
<script src="/static/js/history.js"></script>
</body>
```
`app/templates/index.html` gets one addition: a `<nav>` with a "History" link, matching the new nav block above (keep both pages' nav consistent).

---

## 5. No new persistence — confirmation

Confirmed against `plan-detailed/slice-0.md` §2: the `runs` table already has every column `GET /api/runs` and `GET /api/run/{run_id}` need (`id`, `started_at`, `finished_at`, `status`, `quick_sweep_skipped`, `total_cost_usd`), and `ideas` already has every column needed for the detail view's idea list (`ticker`, `entry`, `target`, `hold_days`, `tier`, `score`, `rationale`, `citation_url`, `low_confidence`, `rank`). Slice 10 adds zero columns and zero tables — only `history_store.py`'s read-only `SELECT`s and two new router handlers. No `ALTER TABLE`, no new migration.

---

## 6. Step-by-step implementation sequence

1. **`app/history_store.py`** — write `list_runs`, `get_run`, `get_ideas_for_run` as plain functions against an existing `conn`. Verify manually against a hand-populated test DB (`python3 -c` with a few inserted rows) before wiring routes.
2. **`app/routers/run.py`** — add `GET /api/runs` (param validation: clamp `limit` to `[1, 200]`, `offset >= 0`) and `GET /api/run/{run_id}` (404 on missing).
3. **`app/main.py`** — add `GET /history` route rendering `history.html` (no server-side data needed in the template context; all data loads client-side via `history.js`, consistent with `index.html`'s client-driven rendering pattern).
4. **`app/static/js/cards.js`** — extract the idea-card-rendering function from `run.js` (written in Slice 0/9) into this shared file; update `run.js` to import/call it from here instead of its own copy (small refactor, not a behavior change — verify Slice 0/9's existing tests/manual flow still work identically after the extraction).
5. **`app/templates/history.html`** — build per §4.
6. **`app/static/js/history.js`** — `loadList()` (fetch `/api/runs`, render rows, click handler -> `loadDetail(run_id)`), `loadDetail(run_id)` (fetch `/api/run/{id}`, render via `cards.js`, handle 404 by showing "run not found" and returning to list), `backToList()` handler.
7. **`app/templates/index.html`** — add the nav link.
8. **`app/static/css/main.css`** — add `.history-row`, `.history-row--error`, `.history-row--skipped` (or similar) classes; reuse existing `.card`/`.tier-*`/`.low-confidence` classes for the detail view's ideas — no new visual system.
9. **Manual smoke test** (see §8) before writing automated tests.
10. **`tests/test_history_api.py`** — write and run the test cases in §7.
11. Run full suite (`pytest tests/ -v`), fix anything red, re-do the manual smoke test once more end-to-end.

---

## 7. Exact test cases

File: `tests/test_history_api.py`. Uses the `client`/`data_dir` fixtures established in Slice 0's `tests/conftest.py`. Seeds multiple runs directly via SQL inserts against the test DB connection (bypassing the full pipeline/orchestrator — this is a pure persistence/read-path test, not an orchestrator test) so the fixtures are simple, deterministic, and independent of whichever slices (fake or real LLM) happen to be wired in at the time this test runs.

- `test_runs_list_empty_db_returns_empty_array` — fresh DB, `GET /api/runs` returns `200` with `{"runs": [], "limit": 50, "offset": 0, "total_count": 0}`.
- `test_runs_list_default_limit_is_50` — assert the response's `"limit"` field is `50` when no `limit` query param is passed (documents the concrete default chosen in §2).
- `test_runs_list_reverse_chronological_order` — insert 3 runs with increasing `id`/`started_at` (run A, then B, then C), call `GET /api/runs`, assert `runs[0]["run_id"] == C's id`, `runs[1] == B`, `runs[2] == A` (strict `id DESC` order).
- `test_runs_list_content_matches_seeded_fields` — insert one run with known `status`, `started_at`, `finished_at`, `quick_sweep_skipped=1`, `total_cost_usd=1.23`; assert the corresponding entry in `GET /api/runs`'s `runs` array matches every field exactly, including `quick_sweep_skipped` round-tripping as JSON `true` (not `1`).
- `test_runs_list_respects_limit_and_offset` — insert 5 runs; call `GET /api/runs?limit=2&offset=1`; assert exactly 2 runs returned, and they are the 2nd and 3rd most recent (not the 1st or the oldest); assert `total_count == 5`.
- `test_runs_list_limit_clamped_to_max` — call `GET /api/runs?limit=9999`; assert the response does not error and `"limit"` is clamped to `200` (or the handler returns `422` for out-of-range `limit` — pick one behavior and assert it explicitly; recommend clamping over erroring, for a read-only browse endpoint with no security implication either way).
- `test_run_detail_returns_full_record_for_existing_run` — insert one run with 2 seeded ideas (distinct tickers, tiers, ranks); call `GET /api/run/{that_id}`; assert `has_run == true`, every run-level field matches, `ideas` has exactly 2 entries in `rank` order, and each idea's fields match the seeded values exactly (ticker, entry, target, hold_days, tier, score, rationale, citation_url, low_confidence).
- `test_run_detail_404_for_nonexistent_run` — call `GET /api/run/999999` (no such id); assert `404` and body `{"error": "run not found"}`.
- **Immutability test (explicitly requested):** `test_editing_later_run_does_not_affect_earlier_runs_stored_record` — insert run #1 with idea A (`ticker="FOO"`, `tier="green"`, `rationale="original"`); insert run #2 with a different idea B; call `GET /api/run/1` and record the full response; then directly `UPDATE ideas SET rationale='mutated', tier='red' WHERE run_id=2` (simulating a later run's data changing) — **note:** this is deliberately mutating run #2's own row only, never run #1's row (nothing in this system actually provides a code path to mutate an already-persisted earlier run; this test exists to prove that fact, not to work around a mutation bug); re-call `GET /api/run/1` and assert the response is byte-for-byte identical to the first call's response — run #1's stored record was never touched by anything that happened to run #2. This directly demonstrates the "immutability" property the task calls for: each run's row is independent and nothing in Slice 10's (or any other slice's) code path writes across run boundaries.
- `test_history_page_route_returns_html` — `GET /history` returns `200` and `text/html` content type (smoke test for the new page route existing and rendering).

Command to run: `pytest tests/test_history_api.py -v` (or `pytest tests/ -v` for the full suite including this file).

---

## 8. How to manually demonstrate

**Start the server** (same as Slice 0): `uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`

1. Trigger 2-3 runs via "Run now" on `/` (or, faster for manual testing, insert a couple of rows directly via `sqlite3 ~/.swingtrade/app.db` using the schema from `plan-detailed/slice-0.md` §2, varying `status`/`quick_sweep_skipped`/idea content across rows) so there is more than one run to browse.
2. Navigate to `http://127.0.0.1:8000/history`. Confirm the list shows all seeded/real runs in reverse-chronological order (most recent first), each row showing status, started_at, a skip-flag indicator, and a cost figure (will read `0.0` until Slice 11 lands — expected).
3. Click into the most recent run's row. Confirm the detail view shows that run's exact idea list (same card rendering as `/`'s latest-run view), ordered by rank, with the disclaimer visible.
4. Click "Back to list," then click into an older run. Confirm its distinct idea list renders correctly (different tickers/tiers than the run just viewed) — proves the detail view is keyed correctly per `run_id`, not accidentally always showing the latest run.
5. Restart the server (Ctrl+C, relaunch), reload `/history` — confirm the same list and detail content still renders identically (SQLite persistence, not in-memory state, matching Slice 0's own restart-survival acceptance criterion).
6. Try `http://127.0.0.1:8000/api/run/999999` directly in the browser — confirm a `404` JSON response, not a crash or blank page.

---

## 9. Acceptance criteria and verification evidence

- [ ] `GET /api/runs` lists all past runs in reverse-chronological order with `id`, `status`, `started_at`, `finished_at`, `quick_sweep_skipped`, `total_cost_usd`, honoring a default limit of 50 and accepting `limit`/`offset` overrides. **Evidence:** `test_runs_list_*` tests passing.
- [ ] `GET /api/run/{run_id}` returns one past run's full idea list + metadata, in the same shape as `GET /api/run/last`, ordered by `rank`, and 404s cleanly for an unknown id. **Evidence:** `test_run_detail_*` tests passing.
- [ ] No new tables/columns were added; only new `SELECT` queries against the existing Slice-0 schema. **Evidence:** code review of `app/history_store.py` (no DDL) and `git diff` on `app/db.py` showing no changes.
- [ ] A later run's data can never retroactively change an earlier run's stored record (immutability). **Evidence:** `test_editing_later_run_does_not_affect_earlier_runs_stored_record` passing.
- [ ] The history view (new `history.html` + `/history` route) lists past runs and links into each run's detail, reachable from the main page's nav. **Evidence:** manual demonstration steps 2-4 above.
- [ ] History is correct after an app restart (queried from SQLite, not memory). **Evidence:** manual demonstration step 5.
- [ ] `pytest tests/test_history_api.py -v` — all tests pass, zero skips/xfails.

Slice 10 is complete only when every checkbox above is verified with the stated evidence, not merely claimed.
