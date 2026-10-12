# Slice 8 — Detailed Technical Plan: Sonnet Compilation/Verdict Stage (FR5)

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 8 only
**Inputs (locked, not reopened):** `tech-spec.md` §4 FR5/FR6, §5, §9; `initial-plan.md`; `vertical-slice-plan.md` Slice 8 section ("fake then real, single compilation call over ALL surviving candidates together, exactly once per run"); `plan-detailed/slice-0.md` (project conventions: `ideas` table shape, `db_session`, fake/real session seam naming, pytest layout).
**Precedent repo:** `ai-job-finder-console` — `app/agent/claude_session.py` (`ClaudeSessionManager`, ephemeral-client lifecycle, `collect_text`/`ClaudeExchangeError`), `app/agent/claude_scoring.py` (`ClaudeScoringPort`, strict separation of LLM sub-scores from app-computed final score, JSON-object-only prompt pattern, `parse_sub_scores`), `app/fakes/fake_session.py` (Fake session shape), `tests/test_sourcing_live_manual.py` (opt-in live-test pattern: `pytestmark = pytest.mark.skipif(os.environ.get(FLAG) != "1", ...)`).

**Integration-point assumption (stated explicitly per the task's instruction):** By the time this stage runs, Slices 4-7 have already produced, for every surviving candidate, a finalized and immutable: ticker, deterministic 0-100 score + red/yellow/green tier (from Slice 5's `scoring.py`, applied to Haiku's sub-scores), Haiku's raw sub-scores + reasoning + citations (from Slice 4/7's deep-dive stage), and filter status (from Slice 6 — only candidates that passed negative filtering reach this stage). **This plan treats all of that as a read-only input type (`ScoredCandidate`) and does not modify Slices 4-7's code, schema columns, or scoring logic in any way.** The only new/modified surface this slice owns is: the `CompilationSession` protocol (shared file with Slice 4's `HaikuSession` — flagged below), `FakeCompilationSession`, the real Sonnet client, the orchestrator's compilation step, and new rationale/commentary columns.

---

## 1. Files to create / modify

| Path | Change | Responsibility |
|---|---|---|
| `app/agent/sessions.py` | **modify** (shared with Slice 4) | Add `CompilationSession` Protocol alongside `HaikuSession`. **Coordination point** — see §2. |
| `app/fakes/fake_sessions.py` | **modify** (shared with Slice 4) | Add `FakeCompilationSession` alongside `FakeHaikuSession`. |
| `app/agent/sonnet_session.py` | **create** | Real `CompilationSession` implementation: builds one ephemeral `ClaudeSDKClient` (Sonnet), connects, sends the one compilation prompt, parses the JSON response, disconnects. |
| `app/agent/compilation.py` | **create** | `run_compilation_stage(candidates, session) -> CompilationResult` orchestration glue: builds the prompt payload, calls `session.run_compilation(...)`, parses/validates, and exposes a pure `merge_compilation_into_candidates(...)` merge function (the structural enforcement point — see §4). |
| `app/agent/prompts.py` | **modify** (or create if Slice 4/7 hasn't yet) | Add `COMPILATION_PROMPT` template + `build_compilation_prompt(candidates)`. |
| `app/db.py` | **modify** | Add two nullable `TEXT` columns to `ideas`: `polished_rationale`, `ranking_commentary`. Placeholder-column convention from Slice 0 §2 applies — if Slice 1-7 plans already reserved these columns, this slice only starts writing real values into them; otherwise this slice adds them via `_ADDED_COLUMNS` migration (per Slice 0's documented escape hatch, since this is a genuinely new need discovered after the fact relative to Slice 0's schema). |
| `app/run_orchestrator.py` | **modify** | Insert orchestrator step 7 (compilation) between negative filtering (step 6, Slice 6) and output assembly (step 8, Slice 9). |
| `tests/test_compilation.py` | **create** | Integration tests against `FakeCompilationSession`. |
| `tests/test_compilation_live_manual.py` | **create** | Opt-in live test against the real Sonnet client. |

---

## 2. `CompilationSession` Protocol — shared-file coordination point

`app/agent/sessions.py` already holds (per Slice 4) `HaikuSession` (sweep + deep-dive methods). This slice adds a second Protocol in the **same file**, not a new file, so that both session Protocols live together as the one place the orchestrator imports session contracts from — mirroring the sibling project's single `ports.py` convention of grouping related Protocols.

**Coordination flag:** Slice 4/7's agent and this slice's agent must not edit `app/agent/sessions.py` concurrently without rebasing on each other — append-only edits (adding a new Protocol class at the end of the file) are expected to merge cleanly, but this must be confirmed before Slice 8 implementation starts if Slice 4/7 is still landing in parallel. Same coordination note applies to `app/fakes/fake_sessions.py`.

```python
# app/agent/sessions.py (addition)

from dataclasses import dataclass
from typing import Protocol


@dataclass(frozen=True)
class ScoredCandidate:
    """Read-only input to compilation. Produced entirely by Slices 4-7;
    this slice never constructs one with invented score/tier/sub-score
    values — only test fixtures do, and only to stand in for upstream
    output."""
    ticker: str
    score: int                      # 0-100, from scoring.py (Slice 5) — immutable here
    tier: str                       # "green" | "yellow" | "red" — immutable here
    sub_score_catalyst: int
    sub_score_momentum: int
    sub_score_macro: int
    haiku_reasoning: str             # Haiku's deep-dive rationale text (Slice 4/7)
    citations: list[dict]            # [{"headline": ..., "source": ..., "published_at": ..., "url": ..., "snippet": ...}]
    low_confidence: bool = False     # backfill flag, set by Slice 9 — False/unused at this stage


@dataclass(frozen=True)
class CompiledIdea:
    """Compilation output for exactly one candidate. Deliberately has NO
    score/tier/sub_score fields — see §4."""
    ticker: str
    polished_rationale: str
    ranking_commentary_fragment: str


@dataclass(frozen=True)
class CompilationResult:
    """Keyed by ticker. `ideas` covers every input candidate (compilation
    must not drop or add tickers). `overall_ranking_commentary` is the
    shared cross-candidate paragraph; `ideas[*].ranking_commentary_fragment`
    is optional per-idea color commentary that supplements it."""
    ideas: dict[str, CompiledIdea]
    overall_ranking_commentary: str


class CompilationSession(Protocol):
    async def run_compilation(
        self, candidates: list[ScoredCandidate]
    ) -> CompilationResult: ...
```

Exact protocol method signature (as required by the task):
```python
async def run_compilation(candidates: list[ScoredCandidate]) -> CompilationResult
```

---

## 3. `FakeCompilationSession` — exact canned behavior + call-count recording

```python
# app/fakes/fake_sessions.py (addition)

from app.agent.sessions import CompilationResult, CompiledIdea, ScoredCandidate


class FakeCompilationSession:
    """Canned, deterministic compilation output. Records every call's
    candidate-ticker list so tests can assert exactly-one-call-per-run and
    inspect exactly what was sent."""

    def __init__(self):
        self.calls: list[list[str]] = []  # one entry per call: tickers passed in, in order

    async def run_compilation(self, candidates: list[ScoredCandidate]) -> CompilationResult:
        self.calls.append([c.ticker for c in candidates])
        ideas = {
            c.ticker: CompiledIdea(
                ticker=c.ticker,
                polished_rationale=(
                    f"[FAKE polished] {c.ticker}: building on the deep-dive "
                    f"finding -- {c.haiku_reasoning[:80]}"
                ),
                ranking_commentary_fragment=f"[FAKE fragment] {c.ticker} ranked per its tier.",
            )
            for c in candidates
        }
        return CompilationResult(
            ideas=ideas,
            overall_ranking_commentary=(
                "[FAKE overall] Ranked by deterministic tier/score, "
                f"covering {len(candidates)} candidate(s): "
                + ", ".join(c.ticker for c in candidates) + "."
            ),
        )
```

`self.calls` is the call-count/order record: `len(fake.calls) == 1` after one run is the exactly-once assertion; `fake.calls[0]` is the exact ticker list sent, used to assert "all surviving candidates together" (not per-candidate calls).

---

## 4. The HARD INVARIANT and its structural enforcement

**Statement (from tech-spec FR5/FR6):** The compilation stage's output must never include or imply a different score/tier than it was given. This is enforced at two independent layers, not just by prompt wording:

**Layer 1 — output schema has no score/tier field at all (structural, not instructional).**
`CompiledIdea` (§2) has exactly three fields: `ticker`, `polished_rationale`, `ranking_commentary_fragment`. There is no `score`, `tier`, `sub_score_*`, or any numeric/tier-shaped field anywhere in `CompiledIdea` or `CompilationResult`. The real session's JSON parser (`app/agent/sonnet_session.py`) only ever reads these three keys per idea out of Sonnet's JSON response and constructs a `CompiledIdea` from them — even if Sonnet's raw text happened to also emit a `"score"` or `"tier"` key (e.g. a model mistake), the parser never looks at that key, so it can never reach a `CompiledIdea` instance, and `CompiledIdea`'s dataclass has no slot to hold it if it tried. This makes "Sonnet outputs a score" physically incapable of propagating downstream, independent of whether the prompt successfully suppresses it.

**Layer 2 — the merge function's write surface is structurally restricted.**
`app/agent/compilation.py::merge_compilation_into_candidates(candidates: list[ScoredCandidate], result: CompilationResult) -> list[ScoredCandidate]` (or the equivalent persistence-layer merge into `ideas` rows) is written so that:
- Its input type (`ScoredCandidate`, carrying score/tier) and the compilation output type (`CompiledIdea`, with no score/tier field) are different dataclasses.
- The merge function builds its return value by copying every field of the original `ScoredCandidate` (`score`, `tier`, `sub_score_*`, `haiku_reasoning`, `citations`, `low_confidence`) **unchanged**, and only *adds* `polished_rationale`/`ranking_commentary_fragment` attributes sourced from `CompiledIdea`. There is no code path in this function that assigns to `.score` or `.tier` from anything compilation-derived — `CompiledIdea` has no such attribute to assign from, so a typo like `candidate.score = compiled.score` would be a hard `AttributeError` at the call site, not a silent bug. This is the same shape as `claude_scoring.py`'s precedent: `ClaudeScoringPort.score_posting` returns only `SubScores`, and `run_orchestrator.py` (sibling) is the only place `scoring_math.compute_final_score` is called — the LLM-returned type structurally cannot carry a final score.
- At the persistence layer (`app/db.py` / the row-update call in `run_orchestrator.py`), the SQL `UPDATE ideas SET polished_rationale = ?, ranking_commentary = ? WHERE id = ?` statement for the compilation step names only those two columns — `score`, `tier`, and the `sub_score_*` columns are syntactically absent from that statement, so even a wrong Python value could not reach those columns via this code path.

**Enforcement is therefore structural at three independent points** (output dataclass shape, merge-function field provenance, and the UPDATE statement's column list), not solely a prompt instruction — the prompt instruction (§6) is a fourth, best-effort layer on top, not the only one.

---

## 5. Real Sonnet session — `app/agent/sonnet_session.py`

```python
from claude_agent_sdk import (
    AssistantMessage, ClaudeAgentOptions, ClaudeSDKClient, ResultMessage, TextBlock,
)
from app.agent.sessions import CompilationResult, CompiledIdea, ScoredCandidate
from app.agent.prompts import build_compilation_prompt
from app.agent.json_utils import parse_json_object  # shared with Haiku parsing, if Slice 4/7 created one

SONNET_MODEL = "claude-sonnet-5"  # pinned full id, mirrors DEFAULT_MODEL pinning precedent

SYSTEM_PROMPT = (
    "You write polished investor-facing rationale and cross-candidate "
    "ranking commentary for a stock swing-trade tool. You NEVER compute, "
    "state, or imply a numeric score or a red/yellow/green tier for any "
    "candidate -- those are fixed by application code before you are "
    "called and are given to you only as read-only context. Your output "
    "schema has no field for a score or tier; do not invent one."
)


class SonnetCompilationSession:
    """One ephemeral ClaudeSDKClient per call: connect() just before
    run_compilation, disconnect() in a finally block right after. Never
    held across calls, never constructed until the Haiku session for this
    run has already fully disconnected (enforced by the orchestrator, see
    §6/§8 -- this class has no awareness of Haiku's lifecycle itself)."""

    async def run_compilation(self, candidates: list[ScoredCandidate]) -> CompilationResult:
        client = ClaudeSDKClient(
            options=ClaudeAgentOptions(
                system_prompt=SYSTEM_PROMPT,
                tools=[],            # no web tools -- reasons only over given candidate data
                setting_sources=[],  # keep user's own CLAUDE.md/hooks out of this session
                model=SONNET_MODEL,
            )
        )
        await client.connect()
        try:
            prompt = build_compilation_prompt(candidates)
            await client.query(prompt)
            text = await _collect_text(client)  # same pattern as claude_session.py's collect_text
        finally:
            await client.disconnect()
        return _parse_compilation_result(text, expected_tickers=[c.ticker for c in candidates])
```

`tools=[]`: no web tools needed — this stage reasons only over already-collected candidate data (per the task's instruction and tech-spec §5's "not re-scoring" framing). `setting_sources=[]`: mirrors the job-finder precedent exactly, to keep the user's own environment out of the ephemeral session. `model=SONNET_MODEL`: pinned full dated id once confirmed against the installed SDK, following `claude_session.py`'s `DEFAULT_MODEL` precedent (avoids silently picking up a different pinned version on SDK upgrade).

**Sequencing requirement — how the orchestrator enforces it:**
In `app/run_orchestrator.py`, the Haiku stage (Slice 7) and the Sonnet stage (this slice) are two sequential `async with`-free, explicit connect/disconnect blocks, never nested:

```python
# step 4 (Slice 7): Haiku sweep + deep-dive
haiku_session = real_haiku_session_factory()
# HaikuSession implementation internally connects per-call and disconnects
# per-call (or holds one connect/disconnect span across the whole sweep+
# deep-dive sequence -- whichever Slice 7 decided); by the time step 4
# returns, Haiku's client has unconditionally called disconnect().
scored_candidates = await run_deep_dive_stage(haiku_session, shortlist)

# ... step 5 scoring, step 6 filtering (no LLM involved) ...

# step 7 (this slice): Sonnet compilation -- constructed here, AFTER step 4
# has returned. Python's sequential execution is the ordering guarantee:
# this line is textually and causally after Haiku's disconnect() call has
# already completed, because step 4's own function does not return until
# its disconnect() awaits. There is no concurrency (no asyncio.gather,
# no nested `async with` spanning both clients) between the two stages.
sonnet_session = real_sonnet_session_factory()
compilation_result = await run_compilation_stage(sonnet_session, surviving_candidates)
```

The guarantee is structural: `run_deep_dive_stage` (Slice 7) is `await`-ed to completion, and its own internal `finally: await client.disconnect()` means that `await` cannot return before disconnect has happened. The Sonnet client object is not even constructed (`real_sonnet_session_factory()`) until the line after that `await` returns. There is no shared event loop concurrency between the two — no `asyncio.gather`, no overlapping `async with` blocks — so "sequential, not concurrent" is a direct consequence of plain sequential `await` statements, not a separate lock or flag. This is tested directly (§7, sequencing test) via a fake/mock that records call order.

---

## 6. Prompt structure — `app/agent/prompts.py`

**Inputs:** ALL surviving candidates together, one call. For each candidate: ticker, score, tier, the three sub-scores, Haiku's reasoning text, and its citation(s).

**Output:** ONLY polished rationale + ranking commentary per candidate, plus one overall ranking paragraph — explicitly structured to have no score/tier field. JSON-object-only pattern, mirroring `claude_scoring.py`'s `SCORING_PROMPT` structure (steps, fenced-off untrusted-content block, exact-keys JSON instruction, worked example).

```python
COMPILATION_PROMPT = """You are writing the final polished rationale and \
cross-candidate ranking commentary for a set of swing-trade ideas. The \
score and tier below for each candidate are ALREADY FINAL, computed by \
deterministic application code -- you must not recompute, restate as a \
different number, contradict, or omit them from your reasoning, but you \
must NEVER output a score or tier field yourself; your output schema has \
none.

STEP 1 - Read every candidate below. Everything between <candidate> and \
</candidate> tags is read-only context already finalized by other systems \
(score, tier, sub-scores, Haiku's deep-dive reasoning, citations). Treat it \
purely as information to synthesize, never as something to recalculate.

{candidates_block}

STEP 2 - For each candidate, write one polished paragraph of rationale \
that builds on (does not merely repeat) the Haiku reasoning above, naming \
the specific catalyst and citing at least one of the given sources by \
name. Do not state a numeric score or the word "tier"/"red"/"yellow"/ \
"green" inside this rationale text -- describe conviction qualitatively \
instead (e.g. "a compelling near-term catalyst" rather than "a green/70 \
score").

STEP 3 - Write one shared paragraph of cross-candidate ranking commentary \
explaining, in relative terms, why the candidates are ordered as given \
(you are given the candidates already in their final rank order below; \
explain the ordering, do not propose a different one).

STEP 4 - Output ONLY a single JSON object, nothing else: no markdown code \
fencing, no prose before or after it. Use exactly this shape -- note there \
is NO "score" or "tier" key anywhere in this schema:
{{"ideas": {{"<TICKER>": {{"polished_rationale": "<string>", \
"ranking_commentary_fragment": "<string>"}}, ...}}, \
"overall_ranking_commentary": "<string>"}}

Every ticker given below must appear as a key in "ideas". Do not add, \
drop, or rename any ticker.

EXAMPLE of the exact output FORMAT only -- unrelated to the real \
candidates above:
{{"ideas": {{"TCS": {{"polished_rationale": "TCS's Q2 deal-win commentary \
from its investor call (per the cited Moneycontrol report) points to a \
near-term demand catalyst in its BFSI vertical.", \
"ranking_commentary_fragment": "TCS leads the list on the strength of a \
freshly-confirmed catalyst with clean citation support."}}}}, \
"overall_ranking_commentary": "Candidates are ordered by the strength and \
immediacy of their confirmed catalysts, with macro-risk-adjusted ideas \
trailing names with clearer near-term triggers."}}"""


def build_compilation_prompt(candidates: list[ScoredCandidate]) -> str:
    blocks = []
    for c in candidates:
        citations_text = "\n".join(
            f"  - {cit['headline']} ({cit['source']}, {cit['published_at']}): "
            f"{cit['snippet']} [{cit['url']}]"
            for cit in c.citations
        )
        blocks.append(
            f"<candidate>\nTicker: {c.ticker}\n"
            f"Final score (already fixed, do not alter): {c.score}/100\n"
            f"Final tier (already fixed, do not alter): {c.tier}\n"
            f"Sub-scores -- catalyst: {c.sub_score_catalyst}, "
            f"momentum: {c.sub_score_momentum}, macro: {c.sub_score_macro}\n"
            f"Haiku deep-dive reasoning: {c.haiku_reasoning}\n"
            f"Citations:\n{citations_text}\n</candidate>"
        )
    return COMPILATION_PROMPT.format(candidates_block="\n\n".join(blocks))
```

Note the candidates are passed to the prompt **already in final rank order** (best-to-worst by tier then score) so Sonnet's ranking commentary only has to explain an ordering, never invent or re-derive one — this keeps ordering logic (Slice 9's job, FR7) fully out of this stage too, consistent with the slice's explicit exclusion of output-cap/ordering/backfill.

---

## 7. Step-by-step implementation sequence

1. **`app/agent/sessions.py`** — add `ScoredCandidate`, `CompiledIdea`, `CompilationResult`, `CompilationSession` Protocol (append-only; coordinate with Slice 4's edits per §2).
2. **`app/fakes/fake_sessions.py`** — add `FakeCompilationSession` (append-only; coordinate with Slice 4's `FakeHaikuSession`).
3. **`app/agent/prompts.py`** — add `COMPILATION_PROMPT` + `build_compilation_prompt`.
4. **`app/agent/compilation.py`** — `run_compilation_stage(session, candidates) -> CompilationResult` (thin call-through + validation that every input ticker appears in the result) and `merge_compilation_into_candidates(candidates, result)` (the structural-invariant function, §4). Write this function's tests (step 7 below) immediately after writing it, before moving on.
5. **`app/db.py`** — add `polished_rationale`, `ranking_commentary` columns (nullable TEXT) via the `_ADDED_COLUMNS`-style migration if not already reserved by an earlier slice's schema.
6. **Wire `FakeCompilationSession` into `app/run_orchestrator.py`** as step 7, between filtering (step 6) and assembly (step 8). Confirm via a manual/integration run that the full fake pipeline (fake Haiku + fake compilation) produces `ideas` rows with non-null `polished_rationale`/`ranking_commentary`.
7. **Write `tests/test_compilation.py`** (all fake-session cases, §8) and get them green against the fake-only wiring.
8. **`app/agent/sonnet_session.py`** — real implementation (§5). Build against the SDK precedent; verify import names (`ClaudeSDKClient`, `ClaudeAgentOptions`, `ResultMessage`, `AssistantMessage`, `TextBlock`) against the installed `claude-agent-sdk` version exactly as `claude_session.py`'s header comment documents doing for the sibling project.
9. **Swap the orchestrator's step 7 to use `SonnetCompilationSession` behind a config flag** (mirroring how Slice 7 presumably gates real-vs-fake Haiku), keeping `FakeCompilationSession` as the default for the existing automated test suite.
10. **Write `tests/test_compilation_live_manual.py`** (§8, opt-in).
11. Run the full suite (`pytest tests/ -v`), including a manual real run once Slice 7's real Haiku stage is also wired, to demonstrate end-to-end (see §9).

---

## 8. Exact test files and test cases

Run with: `pytest tests/test_compilation.py -v` (fake-backed, always run); `COMPILATION_LIVE=1 pytest tests/test_compilation_live_manual.py -v -s` (opt-in, manual only).

### `tests/test_compilation.py`

- **`test_exactly_one_call_per_run`** — build 5 fixture `ScoredCandidate`s (mixed tiers), run the compilation stage once via `FakeCompilationSession`, assert `len(fake.calls) == 1` and `fake.calls[0]` contains all 5 tickers (proves "single call over ALL surviving candidates together," not per-candidate).
- **`test_score_tier_unchanged_before_and_after`** (the most important test in this slice) — build fixture candidates with specific score/tier/sub-score values; run compilation via the fake; call `merge_compilation_into_candidates(candidates, result)`; assert, for every candidate, `merged.score == original.score`, `merged.tier == original.tier`, and all three `sub_score_*` fields are byte-for-byte/value-for-value identical to the pre-compilation values. Additionally assert, via `dataclasses.fields(CompiledIdea)`, that `"score"` and `"tier"` are not among `CompiledIdea`'s field names at all (asserts the structural guarantee of §4 Layer 1 directly, not just its effect).
- **`test_rationale_and_commentary_populated_from_fake`** — after merge, assert each merged candidate's `polished_rationale` matches the fake's canned `"[FAKE polished] {ticker}: ..."` pattern and is non-empty, and that `overall_ranking_commentary` is non-empty and mentions every input ticker (per the fake's canned behavior in §3).
- **`test_merge_rejects_missing_ticker`** — construct a `CompilationResult` missing one input candidate's ticker from `ideas`; assert `run_compilation_stage`/`merge_compilation_into_candidates` raises (fail loud rather than silently dropping an idea) — covers the "never invent/drop a ticker" requirement from §6.
- **`test_sequencing_sonnet_constructed_only_after_haiku_disconnects`** — use two mock/fake session objects with an injected shared `call_order: list[str]` list; the fake Haiku session's disconnect appends `"haiku_disconnect"`, the fake Sonnet session's `run_compilation` appends `"sonnet_call"` on entry. Run the orchestrator's step-4-then-step-7 sequence end-to-end (fakes only) and assert `call_order == ["haiku_disconnect", "sonnet_call"]`exactly, proving the ordering rather than merely asserting both happened.
- **`test_merge_only_writes_rationale_commentary_columns`** (persistence-layer check, if the merge includes the SQL update) — spy/capture the SQL statement or parameters passed to the `UPDATE ideas` call for the compilation step; assert the column list is exactly `{"polished_rationale", "ranking_commentary"}` and does not include `"score"`, `"tier"`, or any `"sub_score_*"` name.

### `tests/test_compilation_live_manual.py`

```python
"""Opt-in live check against the REAL Sonnet ClaudeSDKClient. Skipped by
default; not CI.

Run manually:
    COMPILATION_LIVE=1 pytest tests/test_compilation_live_manual.py -v -s"""
import os
import pytest

pytestmark = pytest.mark.skipif(
    os.environ.get("COMPILATION_LIVE") != "1", reason="live LLM call, manual only"
)
```
- **`test_live_compilation_preserves_score_and_tier`** — 2-3 realistic fixture `ScoredCandidate`s, run through `SonnetCompilationSession.run_compilation`, assert the result covers all input tickers, `polished_rationale`/`ranking_commentary_fragment` are non-empty strings, and (same invariant check as the fake test) merge the result back and assert score/tier are untouched. Print the raw polished text with `-s` for human eyeballing.

---

## 9. How to manually demonstrate

1. Ensure Slices 0-7 and 9 (or at least 0-7, with Slice 9's assembly stubbed/absent) are wired so a full run reaches the compilation step.
2. With the fake-only config (default test config): `uvicorn app.main:app --host 127.0.0.1 --port 8000`, click "Run now," wait for completion, inspect `GET /api/run/last` — every idea's `rationale`/`polished_rationale` field should show the `"[FAKE polished] ..."` prefix and `ranking_commentary` should show `"[FAKE overall] ..."`, and the existing `score`/`tier` fields should match whatever the fake Haiku+scoring pipeline produced (unchanged by the fake compilation step).
3. Switch the app's real/fake session config flag to real for both Haiku and Sonnet (same mechanism Slice 7 established), trigger a real run, and inspect the resulting ideas: `polished_rationale` should read as genuinely polished prose referencing the specific catalyst and a named source; `ranking_commentary` should reference relative ordering across the actual surviving candidates; `score`/`tier` should be numerically and visually identical to a version of the same run with the compilation step stubbed out (or simply: unchanged from the Slice 7-only deterministic values logged before compilation runs).
4. Tail server logs during the real run and confirm: a single Sonnet client connect/disconnect pair appears, timestamped strictly after the Haiku client's disconnect log line for that run.

---

## 10. Acceptance criteria and verification evidence

- [ ] Exactly one Sonnet/compilation call is made per run, regardless of candidate count (1-10). **Evidence:** `test_exactly_one_call_per_run` passing; real-run log inspection showing one connect/disconnect pair per run.
- [ ] Scores/tiers in final persisted idea records are identical before and after the compilation stage. **Evidence:** `test_score_tier_unchanged_before_and_after` passing (including the `CompiledIdea` field-absence assertion); `test_merge_only_writes_rationale_commentary_columns` passing.
- [ ] The compilation output schema has no field capable of representing a score or tier. **Evidence:** code review of `CompiledIdea`/`CompilationResult` in `app/agent/sessions.py` (no score/tier-shaped field); `test_score_tier_unchanged_before_and_after`'s `dataclasses.fields` assertion.
- [ ] The Sonnet client connects only after the Haiku client has fully disconnected (sequencing, not concurrent). **Evidence:** `test_sequencing_sonnet_constructed_only_after_haiku_disconnects` passing; code review of `run_orchestrator.py` showing sequential `await`s with no `asyncio.gather`/nested `async with` spanning both clients; real-run log timestamps.
- [ ] `FakeCompilationSession` is invoked with all surviving candidates together, not per-candidate. **Evidence:** `fake.calls[0]` contains every fixture ticker in `test_exactly_one_call_per_run`.
- [ ] Rationale/ranking-commentary fields are populated and distinct from raw Haiku reasoning. **Evidence:** `test_rationale_and_commentary_populated_from_fake` passing; manual real-run review (§9 step 3).
- [ ] No idea's ticker is dropped or invented by the compilation merge. **Evidence:** `test_merge_rejects_missing_ticker` passing.
- [ ] Real Sonnet session uses `tools=[]`, `setting_sources=[]`, pinned Sonnet model id. **Evidence:** code review of `app/agent/sonnet_session.py`'s `ClaudeAgentOptions` construction.
- [ ] Opt-in live test passes when run manually with real credentials. **Evidence:** `COMPILATION_LIVE=1 pytest tests/test_compilation_live_manual.py -v -s` output, run and reviewed by hand (not part of default CI/test suite).
- [ ] `pytest tests/test_compilation.py -v` — all tests pass, zero skips/xfails.

Slice 8 is complete only when every checkbox above is verified with the stated evidence, not merely claimed.
