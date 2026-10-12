# Slice 12 — Detailed Technical Plan: Cross-Cutting Hardening + Full Regression Gate

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 12 only
**Inputs (locked, not reopened):** `tech-spec.md` §4 (FR1-FR13), §6, §7 (hard constraints), §9 (Acceptance Criteria), §10 (Test Expectations); `vertical-slice-plan.md` Slice 12 section (lines 524-566); `plan-detailed/slice-0.md` (conventions: no auth layer, `127.0.0.1`-only binding, disclaimer exact string, retained-field shape, SQLite schema placeholders).

**Nature of this slice:** Slice 12 adds **no new product functionality**. It is the closing verification/hardening gate before Stage 5 independent validation. Its job is to (a) write cross-cutting automated tests that re-check every hard constraint *across the whole finished system* (not just within the slice that originally introduced it), (b) run the full suite together, and (c) produce a literal, ready-to-use manual walkthrough checklist mirroring tech-spec.md §9. Because Slices 1-11 are being planned/built in parallel, this plan is written structurally — in terms of "every adapter module," "every results-rendering route/template" — rather than hardcoding file names Slice 12 cannot yet see. Step 0 of the implementation sequence is to enumerate those real paths once Slices 1-11 exist, before writing the tests below.

---

## 1. Hard constraints this slice must re-verify end-to-end

Transcribed directly from tech-spec.md so nothing is missed. These are the non-negotiable, non-configurable constraints (§7) plus the full §9 acceptance-criteria list (§9) plus the §10 test-expectations list. Slice 12's automated tests and manual checklist must trace back to every line below.

### 1.1 Hard constraints (§7)
- HC1. Maximum 10 ideas per run.
- HC2. Mandatory citation per idea — no idea without a citation may appear in output.
- HC3. No auto-execution of trades under any circumstance.
- HC4. Mandatory disclaimer on every run's output.
- HC5. Never persist full article body text — headline/source/date/URL/snippet only.
- HC6. App binds to `127.0.0.1` only, never `0.0.0.0`.
- HC7. No Zerodha Kite (or any brokerage) automation in any form.
- HC8. No paid APIs/data sources in v1.

### 1.2 §9 Acceptance Criteria (one line per FR, verbatim intent)
- AC-FR1 (Data collection): All configured sources are fetched and normalized to headline/source/date/URL/snippet form; zero full-article-body fields exist anywhere, including the raw sweep cache.
- AC-FR2/FR12 (Quick-sweep skip): A second run shortly after a materially-unchanged first run skips the deep-dive LLM stage and visibly reports the prior output still stands.
- AC-FR3/FR4 (Sweep + deep-dive separation): Haiku sweep runs with web tools enabled and narrows to a shortlist; each Haiku deep-dive runs without web tools over already-fetched content and returns sub-scores + reasoning + citation(s), never a final tier.
- AC-FR6 (Deterministic scoring): The final tier is always reproducible by re-applying the documented formula/thresholds in application code alone; the Sonnet compilation stage never changes it.
- AC-FR5 (Compilation/verdict): Exactly one Sonnet call per run (not per candidate) over all candidates together; output has ranking commentary + polished rationale; every idea's score/tier are byte-for-byte identical to the pre-compilation deterministic output.
- AC-FR7 (Output cap/ordering/citation): Never more than 10 ideas; ordered green > yellow > red; yellow/green fill first; red appears only as backfill when fewer than 10 yellow/green exist, and every backfilled idea is visibly/distinctly labeled low-confidence; every idea has ≥1 citation; an idea without a valid citation is dropped, never shown.
- AC-FR8 (Retention): Inspecting the SQLite DB and any on-disk cache after a run shows only headline/source/date/URL/snippet fields for every referenced article — no full article text anywhere.
- AC-FR9 (Disclaimer): Every run's output (UI and any other presentation) visibly includes the required disclaimer text.
- AC-FR10 (No auto-execution): No code path capable of placing/modifying/cancelling a brokerage order; no brokerage credentials or order-placement integration at all.
- AC-FR11 (App shell/access control): Reachable only at `127.0.0.1` (never `0.0.0.0`); no token-mint/Origin-Host-check layer present or required; a second concurrent run attempt is rejected (e.g. HTTP 409); UI correctly displays latest + historical runs after a restart (state in SQLite, not memory).
- AC-FR13 (Cost visibility): Run record shows a logged `total_cost_usd`-style figure broken out by stage (sweep/deep-dive/compilation); no run is blocked/delayed/aborted due to cost regardless of magnitude.
- AC-Negative-filtering (within FR4): A candidate exhibiting pump-and-dump indicators or already-priced-in news is flagged/excluded rather than surfaced uncritically.

### 1.3 §10 Test Expectations this slice closes out
- Repo-wide data-retention guarantee (no adapter/cache-write path ever stores full article body text).
- No-auto-execution / no-brokerage-code static verification.
- `127.0.0.1`-only binding verification (never `0.0.0.0`), no token-mint/Origin-pinning code path exists.
- Disclaimer presence across every results-rendering surface.
- Full-suite regression (all unit + integration tests from Slices 0-11 passing together, not just individually).

---

## 2. Files to create

```
tests/test_disclaimer_coverage.py
tests/test_retention_guarantee.py
tests/test_no_brokerage_code.py
tests/test_binding_config.py
.sessions/swingtrade-20261011-130148/slice-12-walkthrough.md   # the manual AC checklist (also embedded in §6 below)
```

No application code files are expected to be created by this slice. If any of the four test files above fail on first run, the fix lands in the *offending* module (e.g., a missing disclaimer render in a template, a `0.0.0.0` default somewhere) — not in new Slice 12 modules. Any such fix must be logged in this plan's "Findings" addendum (append a `## Findings` section to this file during implementation) rather than silently patched, so the orchestrator/user can see what Slice 12 actually had to repair versus purely verify.

Rationale for splitting into four files rather than one `test_hardening.py`: each has a distinct, independent failure mode (template rendering vs. data persistence vs. static source scanning vs. config inspection) and distinct fixture needs; keeping them separate makes `pytest -k` targeting and CI triage easier, and matches the sibling project's convention of one test file per concern.

---

## 3. Step 0 — Enumerate real targets (must happen first, once Slices 1-11 exist)

Before writing a single assertion, run:
```
grep -rln "render\|TemplateResponse" app/routers/ app/templates/ 2>/dev/null
ls app/sources/ 2>/dev/null   # or wherever Slice 1-2 put adapters
grep -rn "disclaimer" app/ --include=*.py --include=*.html
grep -rn "127.0.0.1\|0.0.0.0" app/
```
and build two concrete lists to drive the parametrized tests below:
- **Results-rendering routes/templates list** — expected members based on the vertical-slice plan: the latest-run view (Slice 0/9, e.g. `GET /` or `/api/run/last` + `index.html`), the run-detail view (Slice 9, e.g. `GET /run/{run_id}` + a detail template), the history-list and history-detail views (Slice 10, e.g. `GET /history` + `history.html`, `GET /history/{run_id}` + a detail template). Confirm actual route paths/template file names against what Slices 9-10 actually built; do not assume the names above are final.
- **Adapter module list** — expected members based on Slice 1-2: Moneycontrol RSS, optional secondary RSS, NSE Bhavcopy, Screener.in, Trading Economics. Confirm the actual module paths (e.g. `app/sources/moneycontrol_rss.py`) against what exists.

Record both lists at the top of each relevant test file as an explicit constant (e.g. `RESULT_ROUTES = [...]`, `ADAPTER_MODULES = [...]`) so a reviewer can see exactly what was covered, and so a missing adapter/route is a visible one-line diff to fix rather than a silent gap.

---

## 4. Test files — precise, concrete logic

### 4.1 `tests/test_disclaimer_coverage.py`

Purpose: assert the exact disclaimer string (from `plan-detailed/slice-0.md` §4) appears on every results-rendering surface, system-wide.

```python
DISCLAIMER_TEXT = (
    "For personal informational use only. Not investment advice. "
    "Not a registered investment adviser. No trades are placed "
    "automatically — review and decide manually."
)
```
(Pull this constant from the actual shared location if Slice 0/9 centralized it into a `app/config.py` or `app/constants.py` constant rather than hardcoding it per-template — prefer importing the real constant over re-typing the literal, so the test fails loudly if the two ever diverge instead of silently testing a stale copy.)

Test cases (parametrized over the route list from Step 0):
1. `test_latest_run_view_contains_disclaimer` — seed a completed run with ≥1 idea via the test DB fixture (reuse the `conftest.py` pattern from Slice 0), `GET` the latest-run route, assert `response.status_code == 200` and `DISCLAIMER_TEXT in response.text` (HTML route) or the disclaimer field equals `DISCLAIMER_TEXT` exactly (JSON API route) — cover **both** the HTML page and the JSON API response if the UI renders client-side from JSON, since the disclaimer must be visible in the UI regardless of which layer injects it.
2. `test_run_detail_view_contains_disclaimer` — same pattern against the run-detail route for a specific `run_id`.
3. `test_history_list_view_contains_disclaimer_or_links_to_it` — history list view either repeats the disclaimer or every linked history-detail view carries it (decide based on actual Slice 10 design found in Step 0; default assumption: disclaimer must appear on every page that shows actual idea rationale/entry/target data, not merely a list of run timestamps with no idea content).
4. `test_history_detail_view_contains_disclaimer` — same pattern against a specific past run's detail route.
5. `test_disclaimer_present_even_on_quick_sweep_skipped_run` — seed a run with `quick_sweep_skipped=True` (reusing the prior run's ideas per FR2/AC-FR2), assert the disclaimer still renders (the "nothing changed, here's the prior output" response must still carry it, since it's still displaying idea output).
6. `test_disclaimer_absent_on_pages_with_no_results` (negative control, optional but recommended) — the empty "no runs yet" state is **not required** to show the disclaimer (nothing to disclaim), confirming the test isn't accidentally checking for an unconditional site-wide footer that would mask a real per-view gap.

Implementation note: if Slices 9-10 implement the disclaimer as one shared partial template (e.g. `_disclaimer.html` included via `{% include %}`) covering all routes, these tests still run per-route (never collapse to "the partial exists") — a missing `{% include %}` call in exactly one route is precisely the gap this slice exists to catch.

### 4.2 `tests/test_retention_guarantee.py`

Purpose: a structural, adapter-set-wide guarantee that no persisted/returned record can ever carry full article body text — stronger than a per-adapter unit test because it runs against every adapter together and against the shared `NormalizedItem` type itself.

Two complementary mechanisms, both implemented (per the task's "propose the most robust concrete mechanism" instruction, use defense-in-depth rather than picking only one):

**Mechanism A — structural/type-level check (most robust, catches future adapters automatically):**
```python
import dataclasses
from app.sources.base import NormalizedItem   # or actual shared type location

MAX_SNIPPET_LEN = 400  # confirm the real constant from Slice 1/2's base module; use that, don't invent a new number

def test_normalized_item_has_no_full_body_field():
    field_names = {f.name for f in dataclasses.fields(NormalizedItem)}
    forbidden = {"body", "full_text", "content", "article_body", "raw_html", "text"}
    assert not (field_names & forbidden), (
        f"NormalizedItem exposes a field capable of holding full article "
        f"text: {field_names & forbidden}"
    )

def test_snippet_field_is_length_constrained_by_construction():
    # Construct with an oversized snippet input and assert the stored value
    # is truncated to MAX_SNIPPET_LEN, not silently accepted at full length.
    long_text = "x" * 50_000
    item = NormalizedItem(source="test", headline="h", url="https://x",
                           published_at=..., snippet=long_text)
    assert len(item.snippet) <= MAX_SNIPPET_LEN
```
If Slice 1/2 enforces truncation via a `__post_init__`/validator rather than a hard dataclass constraint, this test still exercises that path — the point is behavioral proof, not just reading the source.

**Mechanism B — per-adapter fixture fuzz test (covers every concrete adapter from Slices 1-2):**
```python
ADAPTER_CLASSES = [
    MoneycontrolRssAdapter, SecondaryRssAdapter, NseBhavcopyAdapter,
    ScreenerInAdapter, TradingEconomicsAdapter,
]  # populate from the real Step-0 enumeration; this is the list to keep in sync

@pytest.mark.parametrize("adapter_cls", ADAPTER_CLASSES)
async def test_adapter_never_returns_full_body_given_long_source_fixture(adapter_cls, monkeypatch):
    # Monkeypatch/stub this adapter's underlying HTTP fetch to return a
    # fixture payload whose "article" field is a 50,000-character body
    # (reuse each adapter's existing test fixture file from Slices 1-2,
    # but with the body field replaced/extended to an oversized string).
    adapter = adapter_cls()
    items = await adapter.fetch()
    for item in items:
        assert len(item.snippet) <= MAX_SNIPPET_LEN
        assert "x" * 1000 not in item.snippet  # oversized marker text must not leak through
        assert not hasattr(item, "body") and not hasattr(item, "full_text")
```
Each adapter's fixture file is the one created in its own Slice 1/2 plan; Slice 12 does not re-author fixtures from scratch — it extends/reuses them with an oversized-body variant. If an adapter's existing test fixtures cannot be cheaply extended this way (e.g. Bhavcopy's CSV has no free-text "body" column at all), that adapter is instead covered only by Mechanism A plus a one-line comment explaining why Mechanism B doesn't apply to it (do not force a fuzz fixture onto a source shape where "body" isn't a meaningful concept).

**Mechanism C — DB-level check (closes the loop end-to-end):**
```python
def test_no_persisted_row_exceeds_snippet_length(db_conn):
    rows = db_conn.execute("SELECT * FROM source_items").fetchall()  # actual table name per Slice 2/3's schema
    for row in rows:
        for col in ("snippet",):
            assert len(row[col] or "") <= MAX_SNIPPET_LEN
    # Also assert no column named body/full_text/content/raw_html exists in the schema at all:
    cols = {c[1] for c in db_conn.execute("PRAGMA table_info(source_items)")}
    assert not (cols & {"body", "full_text", "content", "raw_html"})
```
Run this against the real SQLite schema produced by whichever slice persists sweep-cache/source data (Slice 2 or 3, per Step 0's confirmation).

### 4.3 `tests/test_no_brokerage_code.py`

Purpose: a static, repo-wide scan — no live import attempt, no network call — proving no brokerage SDK or order-placement code path exists.

```python
import ast
import pathlib

BROKERAGE_NAME_FRAGMENTS = [
    "kite", "zerodha", "kiteconnect", "upstox", "angelone", "angel_one",
    "icicidirect", "icici_direct", "fyers", "aliceblue", "alice_blue",
    "5paisa", "dhan", "shoonya", "smartapi",
]

ORDER_ENDPOINT_FRAGMENTS = [
    "/orders", "placeorder", "place_order", "orders/regular",
    "orders/place",  # Kite Connect's actual order-placement path shape
]

PROJECT_SRC = pathlib.Path("app")

def _all_py_files():
    return list(PROJECT_SRC.rglob("*.py"))

def test_no_brokerage_sdk_imports():
    for path in _all_py_files():
        tree = ast.parse(path.read_text(), filename=str(path))
        for node in ast.walk(tree):
            if isinstance(node, (ast.Import, ast.ImportFrom)):
                names = []
                if isinstance(node, ast.Import):
                    names = [a.name for a in node.names]
                else:
                    names = [node.module or ""]
                for n in names:
                    low = n.lower()
                    assert not any(frag in low for frag in BROKERAGE_NAME_FRAGMENTS), (
                        f"{path}: forbidden brokerage-related import '{n}'"
                    )

def test_no_brokerage_substring_anywhere_in_source():
    # Broader net than AST: catches string-literal URLs, comments referencing
    # a brokerage API, dynamic imports (importlib.import_module("kiteconnect")), etc.
    for path in _all_py_files():
        text = path.read_text().lower()
        for frag in BROKERAGE_NAME_FRAGMENTS:
            assert frag not in text, f"{path}: forbidden brokerage reference '{frag}'"

def test_no_order_placement_endpoint_strings():
    for path in _all_py_files():
        text = path.read_text().lower()
        for frag in ORDER_ENDPOINT_FRAGMENTS:
            assert frag not in text, f"{path}: possible order-placement endpoint reference '{frag}'"

def test_pyproject_has_no_brokerage_dependency():
    pyproject = pathlib.Path("pyproject.toml").read_text().lower()
    for frag in BROKERAGE_NAME_FRAGMENTS:
        assert frag not in pyproject, f"pyproject.toml declares a forbidden dependency containing '{frag}'"
```
Note on `test_no_brokerage_substring_anywhere_in_source`: this is intentionally stricter than the AST import check and may need a documented allowlist exception if, e.g., a code comment legitimately says "per spec, no Zerodha Kite integration" (the word "zerodha" appearing in a comment that *disclaims* the integration, not implements it). If that happens, scope the substring scan to exclude comment lines containing "no " / "never " / "out of scope" immediately before the match, or maintain a tiny explicit allowlist of (file, line) exceptions reviewed by hand — do not weaken the check globally.

### 4.4 `tests/test_binding_config.py`

Purpose: assert the app's actual startup invocation always specifies `127.0.0.1`, never `0.0.0.0`, both by source inspection and by constant-level assertion.

```python
import ast
import pathlib
import app.main as main_module  # or app.config, wherever Slice 0 put the bind-host constant

def test_main_module_source_never_references_0_0_0_0():
    source = pathlib.Path("app/main.py").read_text()
    assert "0.0.0.0" not in source

def test_uvicorn_run_call_uses_127_0_0_1():
    tree = ast.parse(pathlib.Path("app/main.py").read_text())
    found_call = False
    for node in ast.walk(tree):
        if isinstance(node, ast.Call):
            func = node.func
            name = getattr(func, "attr", getattr(func, "id", None))
            if name == "run":
                found_call = True
                kwargs = {kw.arg: kw.value for kw in node.keywords}
                host_node = kwargs.get("host")
                assert host_node is not None, "uvicorn.run() call has no explicit host= kwarg"
                assert isinstance(host_node, ast.Constant) and host_node.value == "127.0.0.1"
    assert found_call, "no uvicorn.run()-style call found in app/main.py"

def test_bind_host_constant_if_centralized_equals_localhost():
    # If Slice 0 centralized the bind host into a named constant (e.g.
    # app.config.BIND_HOST) rather than inlining "127.0.0.1" at the call
    # site, assert that constant directly instead of/in addition to the
    # AST check above.
    if hasattr(main_module, "BIND_HOST"):
        assert main_module.BIND_HOST == "127.0.0.1"

def test_no_token_mint_or_origin_pinning_code_exists():
    # Per spec §5/§11 (decided, out of scope for v1): confirm no auth layer
    # was accidentally introduced by a later slice.
    text = pathlib.Path("app").rglob("*.py")
    forbidden = ["mint_token", "x-app-token", "origin_check", "verify_request", "verify_origin"]
    for path in text:
        low = path.read_text().lower()
        for frag in forbidden:
            assert frag not in low, f"{path}: unexpected auth-layer code '{frag}' (out of scope per spec)"
```
Adjust the AST matcher if the real entry point wraps `uvicorn.run(app, host=..., port=...)` differently (e.g., via `uvicorn.Config`/`uvicorn.Server` objects instead of the simple `uvicorn.run()` call) — confirm the actual shape against Slice 0's real `app/main.py` at Step 0 and adjust the matcher accordingly; the *intent* (no code path can bind `0.0.0.0`) is the fixed requirement, the AST shape matched is not.

### 4.5 Full-suite regression

Command:
```
pytest tests/ -v
```
**"Passing" at this gate means:**
- Zero failures.
- Zero errors.
- Zero skips, **except** tests explicitly marked as opt-in "live" SDK tests from Slices 7-8 (e.g. `@pytest.mark.live_sdk` or similar, per whatever marker convention those slices use — confirm exact marker name at Step 0) which require live Claude Agent SDK network access and real cost, and are expected to be skipped by default in CI/local runs without an explicit opt-in flag. Every other test in the suite — unit and integration, including everything from Slices 0-11 and the four new files above — must run and pass with no skip.
- Run `pytest tests/ -v -rs` to get an explicit list of any skipped tests with reasons, and manually confirm every listed skip reason is exactly "requires live SDK/opt-in" and nothing else (e.g., not "TODO: fixture not implemented" or "flaky, skipped for now" — either of those is a real gap this slice must escalate, not wave through).
- If a marker-based opt-in exists, also run the live-marked subset at least once during this slice with real credentials if the user is willing (`pytest tests/ -v -m live_sdk`), to confirm those tests are not permanently broken — but do not block the gate on this if the user prefers to skip real-cost live runs; note the decision explicitly in the Findings section either way.

---

## 5. Step-by-step implementation sequence

1. Confirm Slices 0-11 are implemented and their individual test suites pass independently (`pytest tests/ -v` should already be close to green before Slice 12 starts — Slice 12 is not meant to discover Slice 1-11 were never finished).
2. Run Step 0's enumeration commands; populate the real route list, template list, adapter-module list, bind-host constant location, and live-test marker name. Record these as constants at the top of the four new test files.
3. Write `tests/test_binding_config.py` first (cheapest, no fixtures needed, fastest feedback on whether `app/main.py` is even in the expected shape).
4. Write `tests/test_no_brokerage_code.py` second (also cheap, pure static scan, no app/DB fixtures needed).
5. Write `tests/test_disclaimer_coverage.py` third (needs the `client`/DB fixtures from `tests/conftest.py` — reuse, do not duplicate, the Slice 0 fixture setup).
6. Write `tests/test_retention_guarantee.py` fourth (needs per-adapter fixtures from Slices 1-2 — the most dependency-heavy of the four, hence last).
7. Run each new file individually (`pytest tests/test_binding_config.py -v`, etc.) and fix any genuine gap found in application code (not in the test) — logging each fix in a `## Findings` section appended to this plan file.
8. Run the full suite: `pytest tests/ -v -rs`. Triage any skip that isn't the documented live-SDK opt-in case.
9. If all green, do the one full manual end-to-end real run (§6 below) with the user, ticking off every §9 line against the actual running app.
10. Mark Slice 12 complete only when step 8's full suite is green and step 9's walkthrough has no unresolved gap (per Workflow 2 Stage 4's "never report full acceptance when criteria remain unverified or failing").

---

## 6. Manual walkthrough checklist (deliverable artifact for this slice)

Use this section directly with the user against the real running app (`uvicorn app.main:app --host 127.0.0.1 --port 8000`). Tick each line only against observed behavior, not code review alone, except where noted as a code-review-based check.

- [ ] **FR1 — Data collection:** Trigger a real run. Inspect the sweep-cache/source-items table after it completes. Every row has only headline/source/date/URL/snippet fields populated; no column anywhere contains full article text.
- [ ] **FR2/FR12 — Quick-sweep skip:** Immediately trigger a second run with no material news change. Confirm the UI reports the prior output still stands, and no deep-dive LLM calls were made (check cost log — sweep/deep-dive costs should be ~0 or unchanged on the skipped run).
- [ ] **FR3/FR4 — Sweep + deep-dive separation:** On a real (non-skipped) run, confirm (via logs or cost breakdown) the sweep stage ran with web tools and the deep-dive stage(s) ran without web tools over already-fetched content; each surviving candidate shows sub-scores + written reasoning + at least one citation, with no LLM-assigned final tier visible prior to the deterministic scoring step.
- [ ] **FR6 — Deterministic scoring:** Pick one idea's sub-scores from the run output; re-apply the documented formula/thresholds by hand (or via a quick script); confirm the resulting tier matches exactly what the UI shows.
- [ ] **FR5 — Compilation/verdict:** Confirm (via cost log/stage breakdown) exactly one Sonnet call was made for the whole run, not one per candidate; confirm every idea's score/tier shown in the final UI matches the pre-compilation deterministic values noted in the FR6 check above.
- [ ] **FR7 — Output cap/ordering/citation:** Confirm the run returns ≤10 ideas; confirm ordering is green-before-yellow-before-red; if any red-tier idea appears, confirm it is visibly and distinctly labeled low-confidence and appears only after all yellow/green ideas; confirm every idea shown has a visible citation link.
- [ ] **FR8 — Retention:** Open the SQLite DB file directly (e.g. `sqlite3 app.db`) and manually inspect every table referencing source articles; confirm no column holds more than a short snippet.
- [ ] **FR9 — Disclaimer:** Visit the latest-run view, a run-detail view, and a history-detail view; confirm the exact disclaimer text is visible on each.
- [ ] **FR10 — No auto-execution:** Confirm (code-review-based, not runtime-observable) there is no brokerage credential field anywhere in config/settings/env, and `tests/test_no_brokerage_code.py` is green.
- [ ] **FR11 — App shell/access control:** Confirm the app is unreachable at any address other than `127.0.0.1` (try `curl http://0.0.0.0:8000/` from the same machine and confirm it does not respond on that bind, or inspect `netstat`/`lsof` to see the listening address is `127.0.0.1` only); start a run, then immediately trigger a second run and confirm HTTP 409; restart the server process and confirm the latest/history views still show prior data.
- [ ] **FR13 — Cost visibility:** Confirm the completed run's record shows a logged cost figure broken out by sweep/deep-dive/compilation stage, and confirm no run was ever blocked or warned regardless of the figure's size.
- [ ] **Negative filtering (within FR4):** If a real or seeded-fixture candidate exhibits pump-and-dump indicators or stale/already-priced-in news, confirm it is excluded/flagged rather than surfaced as a clean idea.

---

## 7. Acceptance criteria for Slice 12 itself

(Distinct from the spec's own §9 AC, which is what the walkthrough above checks — this is the AC for the slice's own deliverable.)

- [ ] All four new test files (`test_disclaimer_coverage.py`, `test_retention_guarantee.py`, `test_no_brokerage_code.py`, `test_binding_config.py`) exist, with the concrete test cases described in §4, and all pass.
- [ ] `pytest tests/ -v -rs` run against the full Slice 0-12 codebase shows zero failures, zero errors, and zero skips other than the documented opt-in live-SDK tests from Slices 7-8.
- [ ] Any gap found and fixed during this slice (e.g., a missing disclaimer render, a stray `0.0.0.0` default) is logged in this file's `## Findings` section with before/after evidence.
- [ ] The user has completed the §6 manual walkthrough against the real running app with no unresolved "fail" or "blocked" line; any line that cannot be checked is explicitly labeled blocked/untested with a reason, per Workflow 2's "never report full acceptance when criteria remain unverified" principle — it is not silently marked done.
- [ ] This plan file (with any appended Findings) is the artifact handed to Stage 5's independent validator as evidence that the Slice 0-11 implementation was internally regression-tested before independent validation begins.
