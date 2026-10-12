# Slice 11 — Detailed Technical Plan: Cost Visibility and Logging (FR13)

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 11 only
**Inputs (locked, not reopened):** `tech-spec.md` (FR13: "logged per stage, never gates a run"), `initial-plan.md`, `vertical-slice-plan.md` (Slice 11 section, lines 486-520), `plan-detailed/slice-0.md` §2 (schema: `cost_sweep_usd`, `cost_deep_dive_usd`, `cost_compilation_usd`, `total_cost_usd` already exist as placeholder columns on `runs` — reuse exactly, do not rename or re-add)

**Dependency note:** per the vertical-slice-plan, this slice depends on Slices 7-8 (real SDK calls) for genuinely real cost data, but its persistence/aggregation/"never gates" logic must be fully testable against **stubbed** cost figures from `FakeHaikuSession`/`FakeCompilationSession` (Slice 4/8's fakes) without any live call. This plan treats the fakes' stub-cost addition as an in-scope, small addition coordinated here (see §3) rather than assuming it was already built into Slice 4/8 — Slice 4/8's plans should be checked and amended if they predate this requirement.

---

## 1. Mechanism for capturing cost from the Claude Agent SDK — verified, not guessed

**Finding, verified directly against the installed SDK in the sibling repo's own virtualenv** (`ai-job-finder-console/.venv/lib/python3.13/site-packages/claude_agent_sdk-0.2.163`, `claude_agent_sdk/types.py` line 1340):

```python
@dataclass
class ResultMessage:
    """Result message with cost and usage information."""
    subtype: str
    duration_ms: int
    duration_api_ms: int
    is_error: bool
    num_turns: int
    session_id: str
    stop_reason: str | None = None
    total_cost_usd: float | None = None
    usage: dict[str, Any] | None = None
    result: str | None = None
    structured_output: Any = None
    model_usage: dict[str, ModelUsage] | None = None
    ...
```

`ResultMessage.total_cost_usd` is the exact per-call cost figure the SDK already surfaces — it is a real, named field on a type the sibling project already imports and uses (`app/agent/claude_session.py` imports `ResultMessage` from `claude_agent_sdk` and already inspects `result.is_error`/`result.result`/`result.subtype` on it inside `collect_text()`). The sibling project's `collect_text()` (lines 98-119) currently discards `total_cost_usd` — it is captured by the SDK on every exchange already, just not read by the sibling's code. There is no further guessing needed: the mechanism is `total_cost_usd` on the terminating `ResultMessage` of each `client.receive_response()` iteration.

**Flag to verify during implementation (stated honestly, per the task's instruction):** this project is a *separate* repo/venv from `ai-job-finder-console`. The exact installed `claude-agent-sdk` version in *this* project's own virtualenv may differ from the sibling's pinned `0.2.163` — confirm `total_cost_usd` is present on `ResultMessage` in whatever version this project's `pyproject.toml` pins (run `python3 -c "from claude_agent_sdk import ResultMessage; import dataclasses; print([f.name for f in dataclasses.fields(ResultMessage)])"` against this project's own venv before relying on it) before writing `agent/sessions.py`'s cost-extraction code. If the field is absent or renamed in whatever version lands here, fall back to `usage` (a raw token-usage dict) and compute cost manually from published per-model per-token pricing — but `total_cost_usd` should be tried first since it is the SDK's own authoritative figure (it already accounts for cache discounts etc. that a manual token-based calculation would have to reproduce).

**Where to extract it:** in `agent/sessions.py` (per `initial-plan.md` §Decision A's two-client design), modify the per-call exchange helper (the equivalent of the sibling's `collect_text()`) to also capture and return `result.total_cost_usd` alongside the text, e.g.:

```python
async def collect_text_and_cost(client) -> tuple[str, float]:
    """Like the sibling's collect_text(), but also returns the exchange's
    ResultMessage.total_cost_usd (0.0 if the SDK ever returns None for it,
    e.g. a cache-only/free exchange)."""
    parts: list[str] = []
    result: ResultMessage | None = None
    async for message in client.receive_response():
        if isinstance(message, AssistantMessage):
            if message.parent_tool_use_id is None:
                parts.extend(b.text for b in message.content if isinstance(b, TextBlock))
        elif isinstance(message, ResultMessage):
            result = message
    if result is not None and result.is_error:
        detail = result.result or result.subtype or "unknown error"
        raise ClaudeExchangeError(f"agent returned an error result: {detail}")
    text = "".join(parts).strip() or ((result.result or "").strip() if result else "")
    if not text:
        raise ClaudeExchangeError("agent returned an empty response")
    cost = (result.total_cost_usd if result else None) or 0.0
    return text, cost
```
This is called once per exchange: once for the sweep call, once per deep-dive call (up to 10), once for the compilation call. Each call site is already a distinct, identifiable call in the orchestrator (Slice 4/7's `run_sweep`/`run_deep_dive`, Slice 8's `run_compilation`), so attributing each returned cost to the correct stage bucket (§2 below) is mechanical — no ambiguity about which call produced which figure.

---

## 2. Exact aggregation

Per-call costs are summed into the four existing `runs` columns from `plan-detailed/slice-0.md` §2 (confirmed unchanged, reused exactly — no rename, no new column):

- `cost_sweep_usd` = the single sweep call's `total_cost_usd` (exactly one call per run, so this is not actually a sum — just that one value).
- `cost_deep_dive_usd` = **sum** of every per-ticker deep-dive call's `total_cost_usd` (0 to 10 calls per run, depending on shortlist size and any per-stock skips from Slice 7's failure handling — a skipped/failed deep-dive contributes `0.0`, not an error, to this sum; the run continues per Slice 7's "continue, skip that ticker" policy).
- `cost_compilation_usd` = the single compilation call's `total_cost_usd` (exactly one call per run, per FR5/Slice 8's invariant).
- `total_cost_usd` = `cost_sweep_usd + cost_deep_dive_usd + cost_compilation_usd`. Computed once, in application code, after all three stage totals are known (end of the pipeline, just before the final `runs` row update) — never recomputed or touched afterward, consistent with every other "final, immutable once persisted" field on the `runs` row.

**Where aggregation happens:** `run_orchestrator.py`'s `RunOrchestrator`. The orchestrator already threads one `float` accumulator per stage through its existing step sequence (step 3 = sweep, step 4 = deep-dives, step 7 = compilation, per `tech-spec.md` §5's 9-step list) — each step's session-wrapper call now returns `(result, cost)` instead of just `result` (per §1's `collect_text_and_cost`), and the orchestrator adds `cost` into the right accumulator at each step. At step 8 (persistence), the orchestrator writes all four columns in the same `UPDATE runs SET ... WHERE id = ?` statement that already sets `status='complete'`/`finished_at` — one write, not an incremental running total written mid-run (avoids partial-cost rows being visible while a run is still in progress; the columns stay at their Slice-0 placeholder `0.0` default until the run's single terminal update, which is consistent with how `quick_sweep_skipped` and the idea rows are already only written at completion).

**Quick-sweep-skipped runs (FR2 interaction):** when the quick-sweep short-circuits a run (no deep-dive/compilation invoked), `cost_sweep_usd` is still the real sweep-stage cost (the quick-sweep comparison itself is pre-LLM/programmatic per FR2 and costs nothing; but note some pipeline designs may still run a cheap Haiku call even on a skip path — confirm against Slice 3's actual implementation before assuming; if Slice 3's skip path makes zero LLM calls at all, `cost_sweep_usd` is correctly `0.0` for a skipped run), and `cost_deep_dive_usd`/`cost_compilation_usd` are `0.0` (those stages never ran). This is the correct, expected behavior — not a bug — and should be asserted in a test (§6).

---

## 3. Fakes must return a stubbed cost figure — exact values

`FakeHaikuSession` and `FakeCompilationSession` (Slice 4/8's fakes, in `fakes/fake_sessions.py`) must be extended so every canned response they return includes a stubbed cost figure, making Slice 11's aggregation logic testable without any live SDK call. This is stated here as a requirement Slice 4/8's plans should already support; if those slices' plans/implementations predate this requirement, add this as a small, backward-compatible addition to the existing fakes (not a redesign) when Slice 11 is implemented.

**Exact stub values (concrete, not left to the coder to invent arbitrarily):**
- `FakeHaikuSession.run_sweep(...)` returns its existing canned shortlist plus a cost of **`0.001`** (USD) per call.
- `FakeHaikuSession.run_deep_dive(ticker, ...)` returns its existing canned sub-scores/reasoning plus a cost of **`0.0005`** (USD) per call — distinct from the sweep's stub value so a test can distinguish "sweep cost landed in `cost_sweep_usd`" from "deep-dive cost landed in `cost_deep_dive_usd`" by value alone, not just by which field was non-zero.
- `FakeCompilationSession.run_compilation(...)` returns its existing canned rationale/ranking text plus a cost of **`0.01`** (USD) per call — again a distinct value from the other two, for the same reason.
- These three constants should be named module-level constants in `fakes/fake_sessions.py` (e.g. `FAKE_SWEEP_COST_USD = 0.001`, `FAKE_DEEP_DIVE_COST_USD = 0.0005`, `FAKE_COMPILATION_COST_USD = 0.01`) so tests can assert against the named constant rather than a magic number, and so a future "huge cost" test (§5) can cleanly override just one of them via constructor injection rather than editing the fake's return values inline.
- Each fake's protocol-conforming method signature changes from returning just the parsed result to returning `(result, cost: float)` — matching the real session wrapper's new `collect_text_and_cost`-based return shape from §1, so the orchestrator's calling code is identical whether it's talking to the fake or the real session (this is exactly the protocol-conformance guarantee Slice 7's plan already calls out as a goal).
- **Constructor override for the "huge cost" test (§5):** add an optional constructor parameter to each fake, e.g. `FakeCompilationSession(cost_usd: float = FAKE_COMPILATION_COST_USD)`, so a test can construct `FakeCompilationSession(cost_usd=999_999.0)` without needing a separate fake class or monkeypatching a module constant.

---

## 4. UI display

- **Run detail view** (Slice 0's latest-run card view on `/`, and Slice 10's history-detail view on `/history`): add a small cost line near the run's status/timestamp metadata, e.g.:
  `Cost: $0.0152 (sweep $0.0010 · deep-dive $0.0042 · compilation $0.0100)`
  Rendered as plain text (not a chart, per the task's explicit instruction), using the four-decimal-place formatting shown above (costs here are small-dollar figures per spec §7's "$2-10/day order of magnitude" estimate for a whole day's runs, so per-run figures are typically sub-cent-to-low-cent; 4 decimal places avoids rounding every real run's cost down to a misleading `$0.00`). If `total_cost_usd == 0.0` (Slice 0-10 placeholder state, or genuinely free run), render `Cost: $0.0000` rather than hiding the line — consistent visibility is the point of FR13, not a conditional display.
- **History list view** (`/history`'s `GET /api/runs`-backed row list, Slice 10): the `total_cost_usd` column already present in each row (per Slice 10's `history_store.list_runs`) is rendered as a plain `$X.XXXX` text value per row — no new API shape needed, since Slice 10 already selected and returned `total_cost_usd` in anticipation of this slice (confirmed in `plan-detailed/slice-10.md` §2/§3).
- No chart, sparkline, or cumulative-cost-over-time view — explicitly out of scope per the vertical-slice-plan's "no budget/threshold UI of any kind" exclusion and the task's "simple text, not a chart" instruction.

---

## 5. The "never gates" requirement — explicit design and test

**Design guarantee (code-review-verifiable, not just test-verifiable):** cost values are written to the `runs` row exactly once, at the same terminal `UPDATE` as `status`/`finished_at` (§2), and are read only by: (a) the JSON API response serializers in `app/routers/run.py`/`app/history_store.py`, and (b) the two template-rendering JS files (`run.js`'s/`cards.js`'s render function, `history.js`). **No other code path reads `cost_sweep_usd`/`cost_deep_dive_usd`/`cost_compilation_usd`/`total_cost_usd` at all** — in particular, `run_orchestrator.py`'s control flow (whether to proceed to the next stage, whether to mark a run `complete` vs. `error`, whether to retry a failed exchange) never branches on any cost value. This is enforceable by code review: `grep -rn "cost_sweep_usd\|cost_deep_dive_usd\|cost_compilation_usd\|total_cost_usd" app/run_orchestrator.py` should show only *write* sites (assignment/accumulation), never inside an `if`/`assert`/`raise` condition.

**Negative test (explicitly requested by the task):** construct a full orchestrator run using `FakeCompilationSession(cost_usd=999_999_999.0)` (an artificially huge stubbed value, using the constructor override from §3) alongside normally-stubbed `FakeHaikuSession`/other fakes, execute the run end-to-end, and assert:
1. The run completes with `status == "complete"` (not `"error"`, not stuck `"running"`).
2. No exception is raised anywhere in the orchestrator's execute path.
3. The persisted `cost_compilation_usd` on the `runs` row is exactly `999_999_999.0` and `total_cost_usd` correctly includes it in the sum (proves the huge value was captured and summed, not silently clamped/dropped as a side effect of some unrelated validation).
4. The API response for that run (`GET /api/run/{id}`) returns `200` (not `400`/`413`/any rejection) and includes the huge figure verbatim in its JSON body.
5. No warning/notice field appears anywhere in the response (there is no "cost_warning" field in the schema at all — confirming its absence, not just that it's `false`/`null`, is part of the assertion: `assert "warning" not in response_json and "cost_warning" not in response_json`).

This directly and concretely demonstrates FR13's "never gates" requirement rather than merely asserting an absence of exceptions.

---

## 6. Step-by-step implementation sequence

1. **Verify the SDK field** (per §1's flag) against this project's own installed `claude-agent-sdk` version before writing any extraction code — a 2-minute check that prevents building against a wrong assumption.
2. **`fakes/fake_sessions.py`** — add the three named cost constants and the constructor-override parameters (§3); change each fake's relevant method to return `(result, cost)` tuples. Update any existing Slice 4/8 tests that unpack these methods' return values (a small, mechanical signature-change ripple — not a redesign).
3. **`agent/sessions.py`** (real implementation, Slice 7/8's code) — add `collect_text_and_cost` (§1) and update `run_sweep`/`run_deep_dive`/`run_compilation`'s real implementations to return `(result, cost)` too, matching the fakes' new shape exactly (protocol conformance).
4. **`run_orchestrator.py`** — thread `cost_sweep`, `cost_deep_dive_total` (accumulator, starts at `0.0`, `+=` per deep-dive call), `cost_compilation` through the existing step sequence; compute `total_cost_usd` just before the terminal persistence write; extend the existing `UPDATE runs SET status=..., finished_at=... WHERE id=?` to also set the four cost columns in the same statement.
5. **`app/routers/run.py` / `app/history_store.py`** — confirm (no code change expected, since Slice 10 already selected these columns) that `total_cost_usd` and the three per-stage columns are included wherever a run's own fields are serialized; if Slice 10's responses only included `total_cost_usd` and not the three per-stage breakdown fields, extend `GET /api/run/{run_id}` (and `GET /api/run/last`, for consistency) to also include `cost_sweep_usd`/`cost_deep_dive_usd`/`cost_compilation_usd` in the JSON body (the UI display in §4 needs the breakdown, not just the total).
6. **`app/static/js/cards.js`** (shared run-detail rendering, introduced in Slice 10) — add the cost line per §4's format.
7. **`app/static/js/history.js`** — render the per-row `total_cost_usd` in the list view (§4) — likely already partially done in Slice 10 if it echoed the API field directly; confirm formatting matches §4's `$X.XXXX` convention.
8. **Manual smoke test** (§8) before writing automated tests, including at least one real run if live SDK access is available at implementation time (to sanity-check the real `total_cost_usd` values are plausible, not just that stubbed values round-trip).
9. **`tests/test_cost_tracking.py`** — write and run every case in §7.
10. Code-review pass per §5's `grep` check (no cost value read inside a conditional/control-flow branch in `run_orchestrator.py`).
11. Run full suite (`pytest tests/ -v`), fix anything red.

---

## 7. Exact test cases

File: `tests/test_cost_tracking.py`. Uses `FakeHaikuSession`/`FakeCompilationSession` (with the §3 cost stubs) wired into a full orchestrator run via the existing fake-sourcing/fake-scoring test harness established in Slices 0/4/8 — no live SDK calls.

- `test_cost_sweep_persisted_from_single_sweep_call` — run the orchestrator with default-stub fakes (one sweep call made); assert the persisted `cost_sweep_usd == FAKE_SWEEP_COST_USD` (`0.001`) exactly.
- `test_cost_deep_dive_sums_across_multiple_candidates` — run with a shortlist of, say, 4 candidates (4 deep-dive calls made); assert `cost_deep_dive_usd == 4 * FAKE_DEEP_DIVE_COST_USD` (`0.002`) exactly — proves summation, not just single-call capture.
- `test_cost_deep_dive_excludes_skipped_candidate` — run with a shortlist of 3 candidates where one deep-dive call is made to fail/raise (Slice 7's per-stock skip-on-failure path); assert `cost_deep_dive_usd == 2 * FAKE_DEEP_DIVE_COST_USD` (the failed candidate contributes `0.0`, not an error, to the sum, and does not abort the run).
- `test_cost_compilation_persisted_from_single_call` — assert `cost_compilation_usd == FAKE_COMPILATION_COST_USD` (`0.01`) exactly, and that the compilation fake's call count is still exactly 1 (reconfirms Slice 8's existing invariant isn't disturbed by this slice's changes).
- `test_total_cost_is_sum_of_all_three_stages` — with the above default stubs and e.g. 4 deep-dive candidates, assert `total_cost_usd == cost_sweep_usd + cost_deep_dive_usd + cost_compilation_usd` exactly (`0.001 + 0.002 + 0.01 == 0.013`), both as a formula-level assertion and as an exact literal value.
- `test_quick_sweep_skip_leaves_deep_dive_and_compilation_cost_at_zero` — run a scenario where the quick-sweep (Slice 3) short-circuits the run; assert `cost_deep_dive_usd == 0.0` and `cost_compilation_usd == 0.0`, and `cost_sweep_usd` matches whatever Slice 3's actual skip-path behavior is (either `0.0` if no LLM call happens on the skip path, or the real sweep-call stub cost if the quick-sweep still needs one Haiku call to decide — confirm against Slice 3's implementation and assert the actually-correct value, not an assumed one).
- **"Never gates" negative test (explicitly requested):** `test_huge_compilation_cost_does_not_block_or_warn_run` — construct `FakeCompilationSession(cost_usd=999_999_999.0)`, run the full orchestrator end-to-end; assert (a) the run's final `status == "complete"`, (b) no exception propagates out of `execute_run`, (c) the persisted `cost_compilation_usd == 999_999_999.0` and `total_cost_usd` includes it correctly, (d) `GET /api/run/{run_id}` returns `200` with that exact figure in the body, and (e) the response JSON contains no `warning`/`cost_warning`/similarly-named field at all (`assert not any(k for k in response_json if "warn" in k.lower())`).
- `test_cost_breakdown_visible_in_run_detail_api` — a normal run; `GET /api/run/{run_id}` response includes `cost_sweep_usd`, `cost_deep_dive_usd`, `cost_compilation_usd`, `total_cost_usd`, each matching the persisted row exactly (covers the §6 step 5 API-extension requirement).
- `test_cost_visible_in_history_list_api` — a normal run; `GET /api/runs` response's corresponding row includes the correct `total_cost_usd` (regression check that Slice 10's existing selection still works correctly once real non-zero values exist, not just the `0.0` placeholder it was built/tested against).

Command to run: `pytest tests/test_cost_tracking.py -v` (or `pytest tests/ -v` for the full suite).

---

## 8. How to manually demonstrate

**Start the server:** `uvicorn app.main:app --host 127.0.0.1 --port 8000 --reload`

1. If live SDK access (`claude login`) is available: trigger a real "Run now" on `/`. Once complete, confirm the run-detail view shows a `Cost: $0.XXXX (sweep $... · deep-dive $... · compilation $...)` line with plausible non-zero values (not all zero, not an obviously-wrong huge number) — sanity-check against the spec's soft "$2-10/day all-Sonnet" estimate (§7/§11 of `tech-spec.md`): a single Haiku+Sonnet-split run should read dramatically lower than that daily estimate.
2. If live SDK access is not available at demo time: temporarily wire the app to use the fakes (as tests do) and trigger a run; confirm the same cost line renders with the known stub values (`$0.0010`, `$0.0020` for a 4-candidate shortlist, `$0.0100`, totaling `$0.0130`) — proves the display path end-to-end without needing a live call.
3. Navigate to `/history`; confirm the same run's row shows the matching `total_cost_usd` figure in the list, and clicking into its detail shows the same per-stage breakdown as step 1/2.
4. Confirm visually that nothing about the run's completion was delayed, blocked, or accompanied by any warning banner/text, regardless of the cost figure shown — there is no cost-threshold UI element anywhere to even trigger.

---

## 9. Acceptance criteria and verification evidence

- [ ] After any run, the run record shows a logged `total_cost_usd` broken out into `cost_sweep_usd`/`cost_deep_dive_usd`/`cost_compilation_usd`, summing correctly. **Evidence:** `test_total_cost_is_sum_of_all_three_stages` and related tests passing; manual demonstration steps 1-2.
- [ ] Deep-dive cost correctly sums across multiple per-candidate calls, excluding skipped/failed candidates. **Evidence:** `test_cost_deep_dive_sums_across_multiple_candidates`, `test_cost_deep_dive_excludes_skipped_candidate`.
- [ ] No code path blocks, delays, or warns a run based on the cost figure's magnitude, verified with a deliberately huge stubbed value. **Evidence:** `test_huge_compilation_cost_does_not_block_or_warn_run` passing; code-review `grep` check from §5/§6 step 10 showing zero conditional reads of any cost column in `run_orchestrator.py`.
- [ ] Cost figures persist correctly and display on both the latest-run view and the history view, as plain text (not a chart). **Evidence:** `test_cost_breakdown_visible_in_run_detail_api`, `test_cost_visible_in_history_list_api`; manual demonstration steps 1-3.
- [ ] `FakeHaikuSession`/`FakeCompilationSession` return stubbed, named, overridable cost figures usable without any live call. **Evidence:** code review of `fakes/fake_sessions.py`'s new constants/constructor params; all tests in `tests/test_cost_tracking.py` pass without network/SDK access.
- [ ] The SDK cost-extraction mechanism (`ResultMessage.total_cost_usd`) is confirmed present in this project's actually-installed `claude-agent-sdk` version before being relied upon. **Evidence:** the one-line verification command from §6 step 1, run and recorded (its output) during implementation — flagged here as unverified until that step is actually executed in this project's own environment, since it was only confirmed directly against the sibling repo's separate venv during this planning pass.
- [ ] `pytest tests/test_cost_tracking.py -v` — all tests pass, zero skips/xfails.

Slice 11 is complete only when every checkbox above is verified with the stated evidence, not merely claimed.
