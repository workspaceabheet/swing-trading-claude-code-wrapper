# Slice 0 — Detailed Technical Plan: App Shell, Run-Lock, Fully Fake End-to-End Run

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 0 only
**Inputs (locked, not reopened):** `tech-spec.md`, `initial-plan.md`, `vertical-slice-plan.md` (Slice 0 section, lines 49-93)
**Precedent repo:** `ai-job-finder-console` (`app/main.py`, `app/run_lock.py`, `app/db.py`, `app/routers/run.py`, `app/templates/index.html`, `app/static/js/run.js`, `pyproject.toml`, `tests/conftest.py`)

**Key deviations from the sibling precedent (intentional, per locked decisions):**
- **No auth/token layer.** Sibling's `app/auth.py`, `X-App-Token` header, `mint_token()`, Origin/Host pinning — none of that exists in this project. `127.0.0.1`-only binding is the sole access control (spec FR11, §5). Routes have no `Depends(verify_request)`.
- **Polling, not SSE.** Sibling uses `text/event-stream` + hand-rolled fetch parsing. This project uses plain polling: `POST /api/run` returns immediately (run id only), and the frontend polls `GET /api/run/status` + `GET /api/run/last` on an interval. No `StreamingResponse`, no SSE formatting, no `RunEvent` streaming.
- **Lighter structure.** No `ports.py` Protocol-zoo, no `routers/settings.py`, `routers/chat.py`, `resume_store.py`, `dedup.py`. Only what Slice 0 needs.

---

## 1. Files to create

| Path | Responsibility |
|---|---|
| `pyproject.toml` | Project metadata + pinned dependencies (fastapi, uvicorn, jinja2, pydantic, httpx, pytest) + `[tool.pytest.ini_options]`. |
| `app/__init__.py` | Empty, marks `app` as a package. |
| `app/config.py` | `DATA_DIR` (env-overridable, e.g. `SWINGTRADE_DATA_DIR`, default `~/.swingtrade`), `DB_PATH = DATA_DIR / "app.db"`. No auth/port-pinning constants (not needed — no auth layer). |
| `app/db.py` | SQLite schema (DDL below) + `init_db()` + `get_connection()` + `db_session()` context manager — same pattern as sibling's `app/db.py`, trimmed to this project's two tables. |
| `app/run_lock.py` | `RunLock` class + module-level `run_lock` singleton — copied near-verbatim from sibling's `app/run_lock.py` (no changes needed; it's already generic). |
| `app/run_orchestrator.py` | `RunOrchestrator` stub class with one method `async def execute_run(self, conn) -> None` (or similar) that: inserts a `running` row, simulates minimal work (e.g. `await asyncio.sleep(1)`), inserts the one hardcoded fake idea, updates the run row to `complete` with `finished_at`. No `RunEvent` streaming (no SSE) — it's a plain background coroutine; progress is inferred purely from polling `runs.status`. |
| `app/main.py` | FastAPI app factory, lifespan (schema init + reconciliation sweep), route for `GET /`, mounts `/api` router and `/static`, binds `127.0.0.1` in `run()`. |
| `app/routers/__init__.py` | Empty, package marker. |
| `app/routers/run.py` | `POST /api/run`, `GET /api/run/status`, `GET /api/run/last` route handlers. |
| `app/templates/index.html` | Single-page UI: "Run now" button, status/progress area, one idea card template area, disclaimer footer. |
| `app/static/css/main.css` | Minimal styling for the card, button, disclaimer, status states. |
| `app/static/js/api.js` | Tiny `apiFetch(path, opts)` wrapper (fetch + JSON parse + non-2xx → throw with `.status`) — no token header needed, so this is much simpler than the sibling's `api.js`. |
| `app/static/js/run.js` | "Run now" click handler, polling loop, render-idea-card logic, 409 handling. |
| `tests/__init__.py` | Empty, package marker (or omit if using rootdir-relative imports; mirror sibling's actual layout — check if sibling has this file; if not, omit). |
| `tests/conftest.py` | `data_dir` fixture (isolates `DB_PATH` via `tmp_path` + `monkeypatch`), `client` fixture (`TestClient(create_app())`). |
| `tests/test_run_lock.py` | Unit tests for `RunLock`. |
| `tests/test_run_api.py` | Integration tests for the `POST /api/run` → poll → `GET /api/run/last` flow, 409 behavior. |
| `tests/test_reconciliation.py` | Integration test for the startup reconciliation sweep. |

Note: check whether the sibling repo actually has `tests/__init__.py` before adding one; if absent there too, omit it to match convention.

---

## 2. SQLite schema (schema v0 — Slice 0)

```sql
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,              -- ISO 8601 UTC
    finished_at     TEXT,                        -- NULL while running
    status          TEXT NOT NULL,               -- 'running' | 'complete' | 'error'
    quick_sweep_skipped   INTEGER NOT NULL DEFAULT 0,  -- placeholder bool (0/1); real logic lands in Slice 3 (FR2)
    cost_sweep_usd        REAL NOT NULL DEFAULT 0.0,   -- placeholder; real value lands in Slice 11 (FR13)
    cost_deep_dive_usd    REAL NOT NULL DEFAULT 0.0,   -- placeholder; Slice 11
    cost_compilation_usd  REAL NOT NULL DEFAULT 0.0,   -- placeholder; Slice 11
    total_cost_usd        REAL NOT NULL DEFAULT 0.0    -- placeholder; Slice 11
);

CREATE TABLE IF NOT EXISTS ideas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    ticker          TEXT NOT NULL,
    entry           REAL NOT NULL,               -- buy/entry reference price
    target          REAL NOT NULL,               -- target price
    hold_days       INTEGER NOT NULL,            -- hold-duration estimate in days
    tier            TEXT NOT NULL,               -- 'green' | 'yellow' | 'red'
    score           INTEGER,                     -- placeholder; real 0-100 deterministic score lands in Slice 5 (FR6). NULL in Slice 0.
    sub_score_catalyst   INTEGER,                -- placeholder; Slice 5/4
    sub_score_momentum   INTEGER,                -- placeholder; Slice 5/4
    sub_score_macro      INTEGER,                -- placeholder; Slice 5/4
    rationale       TEXT NOT NULL,               -- written rationale text (Sonnet-polished in later slices; hardcoded in Slice 0)
    citation_url    TEXT NOT NULL,               -- at least one citation URL; hardcoded in Slice 0
    citation_source TEXT,                        -- placeholder for citation source name (Slice 1+); NULL in Slice 0
    citation_headline TEXT,                      -- placeholder for citation headline (Slice 1+); NULL in Slice 0
    low_confidence  INTEGER NOT NULL DEFAULT 0,  -- bool (0/1): red-tier backfill label, per FR7. Always 0 in Slice 0 (fake idea is green).
    rank            INTEGER NOT NULL DEFAULT 1   -- ordering position within the run's idea list (1 = best); trivial with one idea in Slice 0, real ordering logic lands in Slice 9 (FR7)
);
```

Rationale for naming placeholder columns now: per the user's constraint, this avoids an ALTER-TABLE migration in Slices 1-9 for columns whose *name and type* are already knowable from the spec, even though their *values* are fake/zero/NULL until the corresponding slice lands. `score`/sub-scores are nullable (unknown shape risk is low: integers); everything else is `NOT NULL` with sensible zero-ish defaults because Slice 0's fake idea always provides a concrete value for those fields.

`db.py` implementation notes (mirroring sibling pattern):
- `SCHEMA_SQL` is one `executescript` string with `CREATE TABLE IF NOT EXISTS` for both tables (no `_ADDED_COLUMNS` migration machinery needed in Slice 0 — it's a fresh schema; keep the sibling's `_ADDED_COLUMNS` mechanism as a model to reach for in later slices if a genuinely new column is needed after the fact, which this plan has tried to avoid by naming placeholders up front).
- `get_connection()`: `sqlite3.connect(db_path, check_same_thread=False)`, `row_factory = sqlite3.Row`, init-once-per-process-per-path exactly as sibling does.
- `db_session()`: same commit/rollback contextmanager as sibling.

---

## 3. API contract

All responses are JSON (`application/json`), no streaming, no auth headers required.

### `GET /`
Returns the index HTML page (Jinja2 `index.html`), no template context needed beyond static strings (no `app_token` to inject, unlike sibling).

### `POST /api/run`
Request: no body.

Success (lock acquired) — `202 Accepted` with body:
```json
{ "run_id": 7 }
```
Behavior: synchronously tries `run_lock.try_acquire()`. If acquired, inserts a `runs` row with `status='running'`, schedules `RunOrchestrator.execute_run(run_id)` as a FastAPI `BackgroundTasks` task (or `asyncio.create_task`), and returns immediately with the new `run_id`. The background task releases the lock in a `finally` block when it finishes (success or error).

Conflict (lock already held) — `409 Conflict`:
```json
{ "error": "run already in progress" }
```

### `GET /api/run/status`
Response, always `200`:
```json
{ "in_progress": true }
```
Pure read of `run_lock.in_progress` — no DB query.

### `GET /api/run/last`
Response when no run has ever completed or started:
```json
{ "has_run": false }
```
Response when a run exists:
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
      "rationale": "Fake Slice-0 idea: placeholder rationale text used only to prove the end-to-end pipeline wiring works before any real data or LLM analysis is introduced. This is not a real trade recommendation.",
      "citation_url": "https://example.com/fake-citation",
      "low_confidence": false
    }
  ],
  "disclaimer": "For personal informational use only. Not investment advice. Not a registered investment adviser. No trades are placed automatically — review and decide manually."
}
```
Always returns the single most-recently-started run (by `id DESC LIMIT 1`), regardless of its status (`running`, `complete`, or `error`) — this lets the frontend poll this one endpoint during an in-progress run too. If `status == 'running'`, `ideas` is `[]`.

---

## 4. Fake idea — exact hardcoded content

Hardcode this exact idea (constant in `run_orchestrator.py`, e.g. a module-level `FAKE_IDEA` dict/dataclass), inserted as the single row in `ideas` for every Slice-0 run:

- `ticker`: `"RELIANCE"`
- `entry`: `2850.00`
- `target`: `2990.00`
- `hold_days`: `7`
- `tier`: `"green"`
- `low_confidence`: `false`
- `rationale`: `"Fake Slice-0 idea: placeholder rationale text used only to prove the end-to-end pipeline wiring (UI -> API -> run-lock -> background task -> SQLite -> polling -> UI) works before any real data sourcing or LLM analysis is introduced. This is not a real trade recommendation."`
- `citation_url`: `"https://example.com/fake-citation"`
- `citation_source`: `null` (placeholder column, unused until Slice 1)
- `citation_headline`: `null` (placeholder column, unused until Slice 1)
- `score`, `sub_score_catalyst`, `sub_score_momentum`, `sub_score_macro`: `null`
- `rank`: `1`

Disclaimer text (rendered on every results view, exact string — reused later per FR9):
`"For personal informational use only. Not investment advice. Not a registered investment adviser. No trades are placed automatically — review and decide manually."`

---

## 5. Run-lock design

Interface (near-identical to sibling's `app/run_lock.py` — reuse as-is):

```
class RunLock:
    def try_acquire(self) -> bool
        # Returns False immediately if a run is already in progress.
        # Otherwise sets in_progress = True and returns True.
    def release(self) -> None
        # Sets in_progress = False unconditionally.
    @property
    def in_progress(self) -> bool
```

- Module-level singleton `run_lock = RunLock()` in `app/run_lock.py`, imported by `app/routers/run.py`.
- Guards exactly one thing: whether a pipeline run is currently executing. It does NOT guard DB access or any other resource.
- `POST /api/run` calls `try_acquire()` synchronously in the request handler, before scheduling the background task. If it returns `False`, respond `409` immediately without touching the DB.
- The background task (`run_orchestrator.execute_run`) is responsible for calling `run_lock.release()` in a `finally` block that covers both the success path and any exception path, so a crash mid-run doesn't leave the lock stuck (the *in-memory* lock self-heals on next process start anyway since it's reset to `False` by construction — but within the same process, the `finally` is what prevents a leaked lock after an unhandled exception).
- Not thread-safe via actual locking primitives — relies on the single-threaded asyncio event loop's cooperative scheduling, exactly as the sibling documents. This is fine for a single-user local tool.

---

## 6. Startup lifespan reconciliation

In `app/main.py`'s `lifespan`:
1. On startup, call `get_connection()` (triggers `init_db` — creates tables if missing).
2. Run: `UPDATE runs SET status = 'error', finished_at = <now> WHERE status = 'running'`. Commit.
   - Rationale: this process just started, so any row still `'running'` from a previous process cannot actually be running anymore (prior process crashed, was killed, or the host rebooted) — exactly the sibling's reconciliation sweep, adapted to the `runs` table name.
3. No other startup side effects in Slice 0 (no token minting — no auth layer; no resume/settings seeding — not applicable to this project).
4. No shutdown-time cleanup needed in Slice 0 (no live session/subprocess to close yet — that concern starts in later slices with the Claude Agent SDK sessions).

---

## 7. Frontend polling mechanism

- On page load (`GET /`), `run.js`'s init calls `hydrateLastRun()`: fetches `GET /api/run/last` and `GET /api/run/status` once, renders whatever is found (idea card if `status == 'complete'`, "running" state if `in_progress == true`, empty state if `has_run == false`).
- Clicking "Run now": disable the button, POST to `/api/run`.
  - On `202` success: start a polling interval.
  - On `409`: show a brief "a run is already in progress" notice, and still start the polling interval (so the UI catches up to whatever run is actually in flight) rather than silently doing nothing.
- **Polling interval:** `setInterval` at **2000 ms** (2 seconds — matches the sibling's polling cadence, reused here since SSE isn't available), calling `GET /api/run/status`.
- **Stop condition:** when `GET /api/run/status` returns `in_progress: false`, clear the interval, then make one final `GET /api/run/last` call to fetch the completed (or errored) run's data and render it (idea card + disclaimer, or an error state if `status == 'error'`).
- No exponential backoff needed (single user, 2-second fixed interval is cheap enough locally); no maximum poll-count/timeout cutoff is required for Slice 0 (a stub run completes in ~1 second), but note this as a candidate hardening item for a later slice once real LLM calls can run long — not required now.
- Button re-enables only once polling stops (run complete or errored).

---

## 8. Step-by-step implementation sequence

1. **`pyproject.toml`** — dependencies and pytest config first, so nothing else can be run without it.
2. **`app/config.py`** — `DATA_DIR`/`DB_PATH` constants.
3. **`app/db.py`** — schema DDL + `init_db`/`get_connection`/`db_session`. Verify manually (`python -c "from app.db import get_connection; get_connection()"`) that a DB file and both tables are created.
4. **`app/run_lock.py`** — copy sibling's pattern verbatim, no changes needed.
5. **`app/run_orchestrator.py`** — the fake-idea stub pipeline (insert `running` row -> sleep -> insert fake idea -> update row to `complete`). Keep it synchronous-logic-in-an-async-function; no real I/O yet besides SQLite.
6. **`app/routers/run.py`** — the three route handlers, wired to `run_lock` + `run_orchestrator` + `db.db_session`.
7. **`app/main.py`** — app factory, lifespan reconciliation, mounts the router and `/static`, `GET /` route, `run()` entry point binding `127.0.0.1`.
8. **`app/templates/index.html` + `app/static/css/main.css`** — minimal page: run button, progress/status area, idea-card container, disclaimer footer.
9. **`app/static/js/api.js` + `app/static/js/run.js`** — fetch wrapper, click handler, polling loop, render logic.
10. **Manual smoke test** — run the server, click through by hand (see §10) before writing automated tests, to catch obvious wiring bugs cheaply.
11. **`tests/conftest.py`** — fixtures.
12. **`tests/test_run_lock.py`** — unit tests (fast, no FastAPI needed).
13. **`tests/test_run_api.py`** — integration tests against `TestClient`.
14. **`tests/test_reconciliation.py`** — integration test for the lifespan sweep.
15. Run the full suite, fix anything red, then re-do the manual smoke test once more end-to-end as a final check.

This order matches the dependency chain: schema before lock (lock doesn't need schema, but orchestrator does) before orchestrator stub before routes before app wiring before UI before tests — DB-up-the-stack, consistent with the sibling's own layering.

---

## 9. Exact test files and test cases

Run with: `pytest tests/ -v`

### `tests/test_run_lock.py`
- `test_try_acquire_succeeds_when_free` — a fresh `RunLock()` returns `True` from `try_acquire()` and `in_progress` is `True` afterward.
- `test_try_acquire_fails_when_already_held` — after one successful `try_acquire()`, a second `try_acquire()` call returns `False` and `in_progress` remains `True`.
- `test_release_allows_reacquire` — after `acquire()` then `release()`, `in_progress` is `False` and a subsequent `try_acquire()` returns `True` again.

### `tests/test_run_api.py` (uses `client` fixture / `TestClient`)
- `test_get_root_returns_html` — `GET /` returns `200` and `text/html` content type.
- `test_run_last_with_no_runs_returns_has_run_false` — on a fresh DB, `GET /api/run/last` returns `{"has_run": false}`.
- `test_post_run_returns_run_id_and_202` — `POST /api/run` returns `202` with a JSON body containing an integer `run_id`.
- `test_post_run_then_poll_until_complete_returns_fake_idea` — `POST /api/run`, then loop polling `GET /api/run/status` (with a bounded max iteration count, e.g. up to 5 seconds, to avoid an infinite test hang) until `in_progress` is `False`; then `GET /api/run/last` and assert: `status == "complete"`, `len(ideas) == 1`, and the single idea's `ticker`, `entry`, `target`, `hold_days`, `tier`, `rationale`, `citation_url`, `low_confidence` fields exactly match the hardcoded fake-idea constants in §4; also assert the `disclaimer` field in the response is non-empty and contains the phrase "not investment advice" (case-insensitive).
- `test_second_run_while_in_progress_returns_409` — call `run_lock.try_acquire()` directly in test setup so a run is "in progress," then `POST /api/run` and assert `409` with the `{"error": "run already in progress"}` body, and that no second `runs` row was inserted as a result of the rejected attempt.
- `test_run_status_reflects_lock_state` — `GET /api/run/status` returns `{"in_progress": false}` at rest, and `{"in_progress": true}` while a run is active (tested by directly calling `run_lock.try_acquire()` in test setup rather than relying on timing).

### `tests/test_reconciliation.py`
- `test_stale_running_row_reconciled_to_error_on_startup` — directly insert a `runs` row with `status='running'` and no `finished_at` into a fresh DB (bypassing the API, simulating a crashed prior process), then construct the app (triggering `lifespan` startup), then query the DB directly and assert that row's `status` is now `'error'` and `finished_at` is no longer `NULL`.
- `test_completed_row_not_touched_by_reconciliation` — insert a `runs` row with `status='complete'`, trigger lifespan startup, assert the row is unchanged.

Command to run all tests: `pytest tests/ -v`

---

## 10. Launching and demonstrating the slice

**Start the server:**
```
uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload
```

**Open:** `http://127.0.0.1:8000/`

**Manual click-through steps:**
1. Load the page — empty state (no runs yet) should render: no idea card, no disclaimer-with-content yet (or a neutral "no runs yet" message), "Run now" button enabled.
2. Click "Run now." Button should visibly enter a busy/disabled state within the same interaction; a status/progress indicator should appear.
3. Within a few seconds, the page updates (no manual reload) to show: one idea card for `RELIANCE` with entry 2850, target 2990, 7-day hold, green tier badge, the hardcoded rationale text, a citation link to `https://example.com/fake-citation`, and the disclaimer text visible below/near the card.
4. Immediately click "Run now" again while the first run might still be completing (timing-dependent — if the first run already finished by the time you click, re-trigger quickly or add an artificial delay in the orchestrator stub temporarily for this manual check) and confirm the UI surfaces the `409` gracefully (a brief notice, not a crash/blank page).
5. Stop the server process (Ctrl+C), restart it with the same command, reload `http://127.0.0.1:8000/` — the same completed run's idea card should still render (proves SQLite persistence, not in-memory state).
6. To verify crash reconciliation: start a run, kill the server process (`kill -9` or Ctrl+C mid-run — may require temporarily lengthening the orchestrator's simulated sleep to make this timeable by hand) while status is still `running`, then restart the server and reload the page — the run should now show as `error`, not stuck `running` forever.

---

## 11. Acceptance criteria and verification evidence

- [ ] Clicking "Run now" transitions run status `running` -> `complete`, reflected in the UI via polling, with no page reload. **Evidence:** manual click-through step 2-3 above, plus `test_post_run_then_poll_until_complete_returns_fake_idea` passing.
- [ ] A second run attempt while one is in progress returns HTTP 409. **Evidence:** `test_second_run_while_in_progress_returns_409` passing, plus manual step 4.
- [ ] The fake idea renders as a card with ticker, entry/target/hold, tier badge, rationale, citation link, and the disclaimer is visible. **Evidence:** manual step 3 (visual check), plus the field-level assertions in `test_post_run_then_poll_until_complete_returns_fake_idea`.
- [ ] Restarting the app with no run in progress and reloading `/` still shows the last completed run (state in SQLite, not memory). **Evidence:** manual step 5.
- [ ] A run interrupted by process crash is reconciled to `error` on next startup. **Evidence:** `test_stale_running_row_reconciled_to_error_on_startup` passing, plus manual step 6.
- [ ] App only binds to `127.0.0.1`, never `0.0.0.0`. **Evidence:** code review of `app/main.py`'s `run()` function and the documented `uvicorn` launch command — both must hardcode `127.0.0.1`.
- [ ] No real data sourcing or LLM code paths exist yet. **Evidence:** `grep -rn "claude_agent_sdk\|httpx.get\|feedparser\|BeautifulSoup" app/` returns no matches (or only matches explicitly justified as unrelated) — confirms Slice 0's explicit exclusions were respected.
- [ ] `pytest tests/ -v` — all tests pass, zero skips/xfails.

Slice 0 is complete only when every checkbox above is verified with the stated evidence, not merely claimed.
