# Slice 6 — Detailed Technical Plan: Negative Filtering (Pump-and-Dump + Stale-News, within FR4)

**Session:** swingtrade-20261011-130148
**Stage:** Workflow 2, Stage 3 (Detailed Technical Planning) — Slice 6 only
**Inputs (locked, not reopened):** `tech-spec.md` §4 (FR4), §9 ("Negative filtering (within FR4)" acceptance criterion), §11 (explicitly flags exact thresholds as Workflow 2's job — "Pump-and-dump / stale-news filtering logic is not yet concretely designed... exact volume/institutional-ownership thresholds and the stale-news cross-check mechanics are Workflow 2's job to specify precisely"); `vertical-slice-plan.md` Slice 6 section (lines 294-331, user-approved as its own slice placed after scoring — not reopened here); `plan-detailed/slice-0.md` schema; `plan-detailed/slice-5.md` (scoring runs first, unconditionally, on every candidate — negative filtering is a separate later gate, per that plan's §5).

**This plan makes concrete, numbered decisions on every threshold the spec explicitly left open.** These are defaults recommended by this plan, not re-derivations of the spec — flag to the user for a quick sanity check per the vertical-slice-plan's own note ("this is a good moment for the user to sanity-check the concrete thresholds chosen").

---

## 1. Raw fields required from Slice 4's `DeepDiveResult` (cross-check against Slice 4's agent output shape)

Negative filtering cannot run on sub-scores/reasoning alone — it needs these additional raw fields to exist on whatever object Slice 4's deep-dive stage produces per candidate. This section is the explicit contract Slice 6 depends on; if Slice 4's agent scopes `DeepDiveResult` without these fields, that is a gap to reconcile before Slice 6 is implemented.

| Field | Type | Source | Used by |
|---|---|---|---|
| `daily_volume` | `int` (shares) | NSE Bhavcopy (Slice 2 adapter), looked up for this ticker on the run's reference date | pump-and-dump: volume check |
| `avg_20day_volume` | `int \| None` (shares) | Derived from Bhavcopy history if available; `None` if insufficient history is cached | pump-and-dump: volume check (relative leg) |
| `institutional_ownership_pct` | `float \| None` (0-100, FII% + DII% combined) | Screener.in shareholding pattern table (Slice 2 adapter) | pump-and-dump: institutional-ownership check |
| `promotional_chatter_flag` | `bool` | **Haiku-set**, during the deep-dive call (see §3) | pump-and-dump: chatter check |
| `catalyst_mentioned_date` | `date` | Haiku-reported — the date of the news/event the rationale cites as the catalyst | stale-news check |
| `nse_announcement_date` | `date \| None` | NSE corporate-announcements data for this ticker, if available via the Bhavcopy/announcement feed (Slice 2); `None` if no matching announcement was found | stale-news check |

Slice 4's agent must ensure `DeepDiveResult` (or whatever it names its per-candidate output type) carries all six of these — the first three/sixth are plumbing from Slice 1/2's adapters into the deep-dive call's input context (not something Haiku invents), the fourth and fifth are fields Haiku itself populates as part of its structured deep-dive response.

---

## 2. Decision: pump-and-dump thresholds

### 2a. "Low daily volume" — concrete, decided cutoff

**Decision:** a candidate is flagged `thin_volume = True` if **either**:
- `daily_volume < 100,000` shares (absolute floor), **or**
- `avg_20day_volume` is known **and** `daily_volume < 0.3 * avg_20day_volume` (relative floor — current volume collapsed to under 30% of its own trailing average, which is the more informative signal for pump-and-dump "nobody left to trade it" conditions than an absolute number alone, since the absolute floor alone would misfire on legitimately smaller-cap stocks that trade thin but steadily).

If `avg_20day_volume` is `None` (insufficient cached history, e.g. this is one of the first few runs), the relative leg is simply skipped and the absolute floor alone decides `thin_volume`.

**Rationale for 100,000 shares:** chosen as a round, defensible floor below which a retail swing-trader cannot reliably enter/exit an NSE-listed mid/small-cap position within a 1-2 week hold without materially moving the price themselves — well above the volume floor typically used to screen for institutional-eligible liquidity, but low enough not to exclude genuinely liquid small-caps. This is a tunable constant (`MIN_ABSOLUTE_VOLUME = 100_000` in `negative_filters.py`), explicitly flagged for the user to adjust after reviewing real runs.

### 2b. "No institutional ownership" — concrete signal and threshold

**Decision:** a candidate is flagged `no_institutional_ownership = True` if `institutional_ownership_pct` is **either** `None` (Screener.in shareholding data unavailable/unparseable for this ticker) **or** `< 5.0` (combined FII + DII holding under 5% of total shares outstanding, per Screener.in's shareholding-pattern table).

**Rationale for 5%:** a pure retail/promoter-held float with essentially zero institutional participation is a classic marker research flags for pump-and-dump susceptibility (no institutional holder has done diligence on the stock); 5% is a conservative floor (genuinely institutionally-followed stocks are typically well above this) chosen to catch only the clear "no institutional interest at all" case rather than penalizing stocks with modest-but-real institutional presence.

### 2c. "Promotional-chatter flag" — concrete boolean field Haiku must set, and the rubric behind it

**Decision:** Slice 4's deep-dive prompt (owned by Slice 4/7's agent, but Slice 6 specifies the exact contract it needs) must instruct Haiku to set `promotional_chatter_flag: bool` to `True` when, over the headlines/snippets provided in its context for this ticker, **two or more** of the following hold:
1. The catalyst-supporting source(s) are **not** one of the spec's primary retained sources (Moneycontrol RSS, the optional secondary RSS feed) — i.e., the only "evidence" for the catalyst comes from lower-quality or unattributable chatter rather than a recognized source, OR the primary source's own snippet itself reads as promotional (see point 3).
2. Multiple distinct headlines/snippets for the same ticker, appearing within a short window (same day or adjacent days), make near-identical urgent claims without introducing new substantive information between them (a pattern consistent with coordinated chatter rather than organic reporting of a real development).
3. The headline/snippet text itself contains hype-register language — e.g. words/phrases like "multibagger," "mega rally," "explosive breakout," "don't miss out," "huge upside guaranteed," target-price claims with no cited analyst/report backing them.
4. No credible primary-source corroboration exists at all for the specific catalyst claim (i.e., the claimed news event does not appear in the NSE announcement feed or any Screener.in-derived fundamental change, despite the headline asserting a concrete corporate event).

Haiku must also return a one-sentence `promotional_chatter_reasoning: str` explaining which condition(s) triggered the flag (or why none did), for audit/debugging — not shown to the end user in v1, stored for troubleshooting only (mirrors Slice 6's `exclusion_reason` field's spirit, kept separate because this field exists even when the candidate is not ultimately excluded by the chatter flag alone).

This rubric is written here in `negative_filters.py`'s module docstring and must also be copied verbatim (or paraphrased consistently) into Slice 4/7's `agent/prompts.py` deep-dive prompt template — **flagging explicitly for cross-check against whatever Slice 4's agent is producing in parallel**, since this is the one field in this contract that is Haiku-computed rather than programmatically derived, and prompt wording drift here would silently break Slice 6's filter.

### 2d. Combination rule — exact exclusion condition

**Decision (confirmed, matches vertical-slice-plan's own wording — not changed here):** a candidate is excluded for pump-and-dump reasons only when **all three** signals are present simultaneously:

```
pump_and_dump_excluded = thin_volume AND no_institutional_ownership AND promotional_chatter_flag
```

AND (not OR) is deliberate: any single signal alone is too weak to justify excluding a legitimate idea (small-caps are often thin-volume *and* under-institutionally-held without being pump-and-dump schemes; chatter alone could just be enthusiastic retail commentary on a real catalyst). Requiring all three together is the conjunction that research/common practice associates specifically with coordinated promotional schemes, not merely "this is a small, under-covered stock."

---

## 3. Decision: stale-news cross-check mechanics

**Decision:** define a **staleness window of 5 trading days** (~7 calendar days, accounting for weekends — NSE trading calendar, not pure calendar days, since markets are closed weekends/holidays and "stale" should be measured in trading-relevant time).

A candidate is flagged `stale_news = True` if:

```
days_since_catalyst = trading_days_between(catalyst_mentioned_date, run_date)

stale_news = (
    days_since_catalyst > 5
    AND (
        nse_announcement_date is None
        OR trading_days_between(nse_announcement_date, run_date) > 5
    )
)
```

In words: the catalyst Haiku's rationale is built on is **more than 5 trading days old as of this run**, **and** there is no NSE corporate announcement for this ticker within the last 5 trading days that could corroborate a *fresher* restatement of the same news (i.e., if the NSE announcement feed shows the company itself re-affirmed, expanded on, or issued a related filing within the window, the candidate is treated as still fresh even if the original news article predates the window — the official announcement resets the clock). If no NSE announcement exists at all for this ticker (`None`), only the catalyst article's own date is used.

**Rationale for 5 trading days:** the spec's problem statement frames the tool's hold horizon as "days-to-two-weeks," implying the market has likely already digested news older than about a trading week; 5 trading days is roughly one calendar week of market activity, a defensible cutoff for "this is probably already priced in" without being so short that routine reporting lag (news often trails the actual event by a day or two) false-positives every candidate.

**Helper function:** `trading_days_between(d1: date, d2: date) -> int` — Slice 6 implements this with a simple weekday-count approximation (exclude Saturdays/Sundays; NSE holiday calendar is explicitly **not** modeled in v1, a documented simplification — a holiday-adjacent catalyst might be off by one trading day in either direction, acceptable slack for this tool's "advisory, not precision" purpose). This keeps the implementation dependency-free (no external holiday-calendar package) at the cost of modest imprecision around market holidays, which this plan accepts and documents rather than silently ignoring.

---

## 4. File to create

| Path | Responsibility |
|---|---|
| `app/negative_filters.py` | `evaluate_pump_and_dump(candidate) -> bool`, `evaluate_stale_news(candidate, run_date) -> bool`, `trading_days_between(d1, d2) -> int`, and the combining entry point `evaluate_negative_filters(candidate, run_date) -> FilterResult`. Pure function of its inputs plus the constants defined in this module (`MIN_ABSOLUTE_VOLUME`, `MIN_RELATIVE_VOLUME_RATIO`, `MIN_INSTITUTIONAL_OWNERSHIP_PCT`, `STALENESS_WINDOW_TRADING_DAYS`) — no DB/network access, same purity discipline as `scoring.py`. |

---

## 5. Exact interface

```python
# app/negative_filters.py
from dataclasses import dataclass
from datetime import date, timedelta
from typing import Protocol

MIN_ABSOLUTE_VOLUME = 100_000
MIN_RELATIVE_VOLUME_RATIO = 0.3
MIN_INSTITUTIONAL_OWNERSHIP_PCT = 5.0
STALENESS_WINDOW_TRADING_DAYS = 5


class DeepDiveCandidateLike(Protocol):
    """Structural contract this module needs from Slice 4's DeepDiveResult —
    see slice-6.md §1 for the full field table and provenance of each field."""
    ticker: str
    daily_volume: int
    avg_20day_volume: int | None
    institutional_ownership_pct: float | None
    promotional_chatter_flag: bool
    catalyst_mentioned_date: date
    nse_announcement_date: date | None


@dataclass(frozen=True)
class FilterResult:
    excluded: bool
    exclusion_reason: str | None   # None iff excluded is False


def trading_days_between(d1: date, d2: date) -> int:
    """Weekday-only count of trading days between two dates (NSE holiday
    calendar not modeled in v1 — documented simplification, slice-6.md §3)."""
    if d1 > d2:
        d1, d2 = d2, d1
    days = 0
    current = d1
    while current < d2:
        current += timedelta(days=1)
        if current.weekday() < 5:  # Mon-Fri
            days += 1
    return days


def _is_thin_volume(c: DeepDiveCandidateLike) -> bool:
    if c.daily_volume < MIN_ABSOLUTE_VOLUME:
        return True
    if c.avg_20day_volume is not None and c.daily_volume < (
        MIN_RELATIVE_VOLUME_RATIO * c.avg_20day_volume
    ):
        return True
    return False


def _has_no_institutional_ownership(c: DeepDiveCandidateLike) -> bool:
    return (
        c.institutional_ownership_pct is None
        or c.institutional_ownership_pct < MIN_INSTITUTIONAL_OWNERSHIP_PCT
    )


def evaluate_pump_and_dump(c: DeepDiveCandidateLike) -> bool:
    """True only when ALL THREE signals fire together (slice-6.md §2d)."""
    return (
        _is_thin_volume(c)
        and _has_no_institutional_ownership(c)
        and c.promotional_chatter_flag
    )


def evaluate_stale_news(c: DeepDiveCandidateLike, run_date: date) -> bool:
    """See slice-6.md §3 for the exact window/corroboration semantics."""
    days_since_catalyst = trading_days_between(c.catalyst_mentioned_date, run_date)
    if days_since_catalyst <= STALENESS_WINDOW_TRADING_DAYS:
        return False
    if c.nse_announcement_date is not None:
        days_since_announcement = trading_days_between(c.nse_announcement_date, run_date)
        if days_since_announcement <= STALENESS_WINDOW_TRADING_DAYS:
            return False  # fresh official corroboration resets the clock
    return True


def evaluate_negative_filters(
    c: DeepDiveCandidateLike, run_date: date
) -> FilterResult:
    if evaluate_pump_and_dump(c):
        return FilterResult(
            excluded=True,
            exclusion_reason=(
                f"pump_and_dump: thin_volume={_is_thin_volume(c)}, "
                f"no_institutional_ownership={_has_no_institutional_ownership(c)}, "
                f"promotional_chatter_flag={c.promotional_chatter_flag}"
            ),
        )
    if evaluate_stale_news(c, run_date):
        return FilterResult(
            excluded=True,
            exclusion_reason=(
                f"stale_news: catalyst_mentioned_date={c.catalyst_mentioned_date}, "
                f"nse_announcement_date={c.nse_announcement_date}, "
                f"run_date={run_date}, window={STALENESS_WINDOW_TRADING_DAYS}td"
            ),
        )
    return FilterResult(excluded=False, exclusion_reason=None)
```

Signature summary (per task requirement): `evaluate_negative_filters(candidate, run_date) -> FilterResult` where `FilterResult` carries exactly `excluded: bool` and `exclusion_reason: str | None` — `None` if and only if `excluded` is `False`.

---

## 6. Orchestrator wiring

Inserted immediately after Slice 5's `compute_score` step, before persistence and before Slice 8's Sonnet compilation (which must only ever see surviving, non-excluded candidates):

```python
# app/run_orchestrator.py (excerpt — new step inserted right after Slice 5's
# compute_score loop)
from app.negative_filters import evaluate_negative_filters

surviving_candidates = []
for candidate in deep_dive_results:  # already has .score/.tier set by Slice 5's step
    filter_result = evaluate_negative_filters(candidate, run_date=today)
    candidate.excluded = filter_result.excluded
    candidate.exclusion_reason = filter_result.exclusion_reason
    if not filter_result.excluded:
        surviving_candidates.append(candidate)
    # Excluded candidates are NOT appended to surviving_candidates — they do
    # not proceed to compilation (Slice 8) or output assembly (Slice 9) — but
    # their exclusion is still logged/persisted for audit (see schema note).
```

Full pipeline order (confirmed, not reopened — matches both the tech-spec §5 step numbering and the vertical-slice-plan's locked ordering):

```
... Haiku deep-dive loop (Slice 4)
  -> compute_score per candidate (Slice 5)
  -> evaluate_negative_filters per candidate (Slice 6, this slice) -- removes candidates
  -> Sonnet compilation, over surviving_candidates only (Slice 8)
  -> output assembly / cap / backfill (Slice 9)
  -> persistence
```

**Schema addition:** the `ideas` (or an intermediate `candidates`) table/record gains two columns not present in Slice 0's schema: `excluded INTEGER NOT NULL DEFAULT 0` and `exclusion_reason TEXT` (nullable). Per the task's instruction to reuse Slice 0's existing columns rather than renaming anything, these are net-new additions (Slice 0's schema plan did not anticipate them, since negative filtering wasn't yet designed when Slice 0 was planned) — added via `ALTER TABLE ideas ADD COLUMN excluded INTEGER NOT NULL DEFAULT 0;` and `ALTER TABLE ideas ADD COLUMN exclusion_reason TEXT;` in `db.py`'s existing `_ADDED_COLUMNS`-style migration mechanism (referenced in `slice-0.md` §2 as the mechanism to reach for when a genuinely new column is needed after the fact — this is that case). Excluded candidates are still written to the `ideas` table (with `excluded=1` and their `exclusion_reason`) for debugging/audit per the vertical-slice-plan's instruction ("exclusion reason recorded for debugging/audit, not necessarily shown to the user in v1 UI") — they are simply filtered out of what `GET /api/run/last` returns to the UI (a `WHERE excluded = 0` clause at the query boundary, not a `DELETE`).

---

## 7. Test files and table-driven cases

### `tests/test_negative_filters.py`

Run with: `pytest tests/test_negative_filters.py -v`

A lightweight test double satisfying `DeepDiveCandidateLike` (a `@dataclass` with the six fields) is defined at the top of the test file for use across all cases.

**Pump-and-dump table** (boundary-spanning cases on each of the three signals):

| daily_volume | avg_20day_volume | institutional_ownership_pct | promotional_chatter_flag | expected `evaluate_pump_and_dump` |
|---|---|---|---|---|
| 99_999 | None | 2.0 | True | True (absolute floor breached, no institutional ownership, chatter) |
| 100_000 | None | 2.0 | True | False (exactly at absolute floor — not below it; `<` not `<=`) |
| 150_000 | 600_000 | 2.0 | True | True (relative floor: 150k < 0.3 * 600k = 180k) |
| 200_000 | 600_000 | 2.0 | True | False (200k >= 180k relative floor, and >= 100k absolute floor) |
| 50_000 | None | 10.0 | True | False (institutional ownership above 5% threshold — fails the ownership leg) |
| 50_000 | None | 4.9 | True | True (just under 5% threshold) |
| 50_000 | None | None | True | True (unknown ownership treated as "no institutional ownership") |
| 50_000 | None | 2.0 | False | False (no chatter flag — fails the chatter leg, AND-combination requires all three) |

**Stale-news table** (boundary at exactly 5 trading days, with and without a corroborating NSE announcement):

| catalyst_mentioned_date offset (trading days before run_date) | nse_announcement_date offset | expected `evaluate_stale_news` |
|---|---|---|
| 5 | None | False (exactly at the window edge — not "greater than" 5) |
| 6 | None | True (one trading day past the window, no corroboration) |
| 10 | 3 | False (catalyst stale, but a fresh NSE announcement within window resets the clock) |
| 10 | 8 | True (catalyst stale, and the "corroborating" announcement is also outside the window) |
| 10 | None | True (catalyst stale, no announcement at all) |

**Combination/integration-within-module table** (`evaluate_negative_filters`'s exact `FilterResult` shape):

| scenario | expected `excluded` | expected `exclusion_reason` (substring check) |
|---|---|---|
| pump-and-dump-triggering candidate, fresh news | True | `"pump_and_dump"` |
| clean volume/ownership/chatter, stale news | True | `"stale_news"` |
| clean on both axes | False | `None` |
| pump-and-dump AND stale (both would trigger) | True | `"pump_and_dump"` (pump-and-dump check runs first in `evaluate_negative_filters`; documented precedence, not an arbitrary tie-break — a pump-and-dump candidate is excluded for that reason regardless of staleness) |

Each table above is one `pytest.mark.parametrize`-decorated test function.

### Integration test: `tests/test_run_orchestrator_filtering.py` (or appended to the existing Slice 4/5 orchestrator integration test file)
- `test_fake_run_excludes_pump_and_dump_candidate` — configure `FakeHaikuSession` (per Slice 4's pattern) to return one candidate shaped to trigger `evaluate_pump_and_dump` (thin volume, low institutional ownership, `promotional_chatter_flag=True`) and one clean candidate; run the full fake-driven pipeline; assert the final persisted/returned idea list contains only the clean candidate, and a DB query directly on the `ideas` table shows the excluded candidate's row still exists with `excluded=1` and a non-null `exclusion_reason` containing `"pump_and_dump"`.
- `test_fake_run_excludes_stale_news_candidate` — same pattern, with a candidate whose `catalyst_mentioned_date` is set more than 5 trading days before the fake run's `run_date` and no `nse_announcement_date`; assert exclusion with `"stale_news"` in the reason.
- `test_fake_run_keeps_clean_candidate` — a candidate with no filter-triggering characteristics at all survives to the final output, unaffected by this slice's new step.

Command to run all Slice 6 tests: `pytest tests/test_negative_filters.py tests/test_run_orchestrator_filtering.py -v`

---

## 8. How to manually verify

1. In a dev/test harness, configure `FakeHaikuSession` (per Slice 4's existing fake-session wiring) to return two candidates for the next run:
   - **Candidate A** ("clean"): `daily_volume=500_000`, `avg_20day_volume=500_000`, `institutional_ownership_pct=15.0`, `promotional_chatter_flag=False`, `catalyst_mentioned_date` = today, `nse_announcement_date` = today.
   - **Candidate B** ("pump-and-dump fixture"): `daily_volume=40_000`, `avg_20day_volume=None`, `institutional_ownership_pct=1.0`, `promotional_chatter_flag=True`, dates irrelevant (fresh).
2. Trigger a run via the UI "Run now" button.
3. Confirm only Candidate A's idea card appears in the rendered output.
4. Query the SQLite `ideas` table directly (`sqlite3 ~/.swingtrade/app.db "SELECT ticker, excluded, exclusion_reason FROM ideas ORDER BY id DESC LIMIT 2;"`) and confirm Candidate B's row has `excluded=1` with an `exclusion_reason` string starting with `pump_and_dump:` and mentioning all three triggering conditions, while Candidate A's row has `excluded=0` and `exclusion_reason` is `NULL`.
5. Repeat with a third candidate configured to trigger only the stale-news path (clean volume/ownership/chatter, `catalyst_mentioned_date` 10 trading days ago, no `nse_announcement_date`) and confirm exclusion with a `stale_news:` reason this time.

---

## 9. Acceptance criteria and verification evidence

- [ ] A fixture candidate with low volume (below both the absolute and relative floors) + no institutional ownership (<5% or unknown) + `promotional_chatter_flag=True` is excluded from the final list, with `exclusion_reason` recorded. **Evidence:** `tests/test_negative_filters.py`'s pump-and-dump table passes; `test_fake_run_excludes_pump_and_dump_candidate` passes; manual steps 1-4 above confirmed.
- [ ] A fixture candidate whose `catalyst_mentioned_date` is more than 5 trading days before the run date, with no corroborating NSE announcement within that window, is excluded with a `stale_news` reason. **Evidence:** stale-news table in `tests/test_negative_filters.py` passes; `test_fake_run_excludes_stale_news_candidate` passes; manual step 5 confirmed.
- [ ] A clean candidate (no negative-filter triggers on either axis) is not excluded by this stage. **Evidence:** `test_fake_run_keeps_clean_candidate` passes.
- [ ] Every threshold decided in this plan (100,000 absolute volume floor, 0.3x relative volume ratio, 5% institutional-ownership floor, 5-trading-day staleness window, AND-combination of all three pump-and-dump signals) is implemented exactly as the named constants in `app/negative_filters.py` — no magic numbers duplicated elsewhere. **Evidence:** `grep -n "MIN_ABSOLUTE_VOLUME\|MIN_RELATIVE_VOLUME_RATIO\|MIN_INSTITUTIONAL_OWNERSHIP_PCT\|STALENESS_WINDOW_TRADING_DAYS" app/negative_filters.py` shows each constant defined exactly once.
- [ ] `evaluate_negative_filters` returns exactly `FilterResult(excluded: bool, exclusion_reason: str | None)` with `exclusion_reason is None` iff `excluded is False`. **Evidence:** the combination table in `tests/test_negative_filters.py` asserts this invariant across all four scenario rows.
- [ ] Excluded candidates are persisted (not silently dropped/deleted) with `excluded=1` and a non-null `exclusion_reason`, for audit — only hidden from the user-facing idea list via a query-time filter. **Evidence:** manual step 4's direct SQLite query; `test_fake_run_excludes_pump_and_dump_candidate`'s direct-DB-query assertion.
- [ ] `app/negative_filters.py` has zero imports of any LLM/SDK/network module (pure-module guarantee, consistent with `scoring.py`'s discipline). **Evidence:** `grep -n "^import\|^from" app/negative_filters.py` shows only `dataclasses`/`datetime`/`typing` imports.
- [ ] The user has reviewed and confirmed (or requested adjustment to) the concrete thresholds chosen in §2-§3 of this plan before Slice 6 proceeds to implementation. **Evidence:** explicit user sign-off recorded in session notes (this is the one acceptance item that is a process checkpoint, not a test — per the vertical-slice-plan's own instruction that this slice is "a good moment for the user to sanity-check the concrete thresholds").

Slice 6 is complete only when every checkbox above is verified with the stated evidence, not merely claimed.
