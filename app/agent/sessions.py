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


@dataclass(frozen=False)
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
    # Price/duration estimate fields (tech-spec §4 FR6, §8). Haiku supplies
    # expected_move_pct and hold_days; entry/target are NEVER set by Haiku --
    # entry is resolved deterministically from the Bhavcopy close price by
    # app code (run_orchestrator._resolve_entry_price), and target is
    # computed deterministically from entry * (1 + expected_move_pct/100)
    # (same "LLM gives a signal, app code computes the real number"
    # philosophy as compute_score). Defaulted to 0.0/0 only so existing
    # test fixtures that don't care about these fields keep constructing
    # DeepDiveResult without them -- the real pipeline always supplies
    # expected_move_pct/hold_days via parse_deep_dive_response.
    expected_move_pct: float = 0.0  # Haiku's estimated % price move over the hold period
    hold_days: int = 0              # Haiku's estimated hold-duration in days
    # Raw negative-filter signal fields the Slice 6 filter stage will consume.
    # Haiku reports these as flags/values; Slice 6 decides thresholds/action.
    daily_volume: int | None = None
    avg_20day_volume: int | None = None  # For relative volume check (Slice 6)
    institutional_ownership_pct: float | None = None  # FII% + DII% combined (Slice 6)
    promotional_chatter_flag: bool = False
    catalyst_mentioned_date: str | None = None  # ISO date, for stale-news check (Slice 6)
    nse_announcement_date: str | None = None  # ISO date, for stale-news corroboration (Slice 6)
    # Slice 5: computed score and tier (set by compute_score after deep-dive)
    score: int | None = None  # 0-100, set by Slice 5's compute_score
    tier: str | None = None   # "red" | "yellow" | "green", set by Slice 5
    # Slice 6: negative filtering results
    excluded: bool = False
    exclusion_reason: str | None = None


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


@dataclass(frozen=True)
class FinalCandidate:
    """Input to assemble() (Slice 9). Produced by merging ScoredCandidate with
    compilation output and filtering results. Contains all data needed to produce
    the final ranked, cap'd, and backfilled idea list."""
    ticker: str
    score: int                      # 0-100, immutable from Slice 5
    tier: str                       # "green" | "yellow" | "red", immutable from Slice 5
    sub_score_catalyst: int
    sub_score_momentum: int
    sub_score_macro: int
    citations: list[Citation]       # list of citations from deep-dive
    polished_rationale: str          # Sonnet-polished rationale from Slice 8
    ranking_commentary_fragment: str # Optional per-idea commentary from Slice 8
    # Price/duration targets from deep-dive
    entry: float = 0.0
    target: float = 0.0
    hold_days: int = 0


@dataclass(frozen=True)
class Idea:
    """Output of assemble() (Slice 9). Persisted to the ideas table."""
    ticker: str
    entry: float
    target: float
    hold_days: int
    tier: str                       # "green" | "yellow" | "red"
    score: int                      # 0-100
    sub_score_catalyst: int
    sub_score_momentum: int
    sub_score_macro: int
    polished_rationale: str         # From Slice 8 compilation
    citation_url: str               # First citation URL (non-empty required)
    citation_source: str | None     # First citation source
    citation_headline: str | None   # First citation headline
    low_confidence: bool            # True only for backfilled red-tier ideas
    backfill_reason: str | None     # "red_tier_backfill" if low_confidence else None
    rank: int                       # 1..N in final order
    ranking_commentary: str | None = None  # Per-idea ranking commentary from Slice 8
