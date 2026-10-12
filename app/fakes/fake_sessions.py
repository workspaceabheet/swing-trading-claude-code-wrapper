from app.agent.sessions import (
    Citation, DeepDiveContext, DeepDiveResult, ShortlistCandidate,
    ScoredCandidate, CompiledIdea, CompilationResult,
)

# Stubbed cost values for testing (per Slice 11 plan)
FAKE_SWEEP_COST_USD = 0.001
FAKE_DEEP_DIVE_COST_USD = 0.0005
FAKE_COMPILATION_COST_USD = 0.01

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
        expected_move_pct=8.5, hold_days=9,
        daily_volume=5_200_000, avg_20day_volume=5_100_000,
        institutional_ownership_pct=25.5,
        promotional_chatter_flag=False,
        catalyst_mentioned_date="2026-10-10",
        nse_announcement_date="2026-10-09",
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
        expected_move_pct=4.0, hold_days=7,
        daily_volume=8_900_000, avg_20day_volume=8_800_000,
        institutional_ownership_pct=18.5,
        promotional_chatter_flag=False,
        catalyst_mentioned_date="2026-10-08",  # Fresh (within 5-day window)
        nse_announcement_date="2026-10-07",  # With corroborating announcement
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
        expected_move_pct=-2.5, hold_days=5,
        daily_volume=500_000, avg_20day_volume=500_000,
        institutional_ownership_pct=10.0,  # Above 5% threshold, healthy
        promotional_chatter_flag=False,  # Clean signals
        catalyst_mentioned_date="2026-10-11",  # Fresh
        nse_announcement_date="2026-10-10",  # With corroborating announcement
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
        sweep_cost_usd: overrides FAKE_SWEEP_COST_USD for testing purposes.
        deep_dive_cost_usd: overrides FAKE_DEEP_DIVE_COST_USD for testing purposes.
    """

    def __init__(
        self,
        shortlist: list[ShortlistCandidate] | None = None,
        deep_dives: dict[str, DeepDiveResult] | None = None,
        fail_tickers: "set[str] | dict[str, Exception] | None" = None,
        sweep_cost_usd: float | None = None,
        deep_dive_cost_usd: float | None = None,
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
        self._sweep_cost_usd = sweep_cost_usd if sweep_cost_usd is not None else FAKE_SWEEP_COST_USD
        self._deep_dive_cost_usd = deep_dive_cost_usd if deep_dive_cost_usd is not None else FAKE_DEEP_DIVE_COST_USD
        self._deep_dive_costs_usd: list[float] = []

    async def run_sweep(self, items: list) -> list[ShortlistCandidate]:
        self.sweep_calls.append(items)
        return list(self.shortlist)

    async def run_deep_dive(self, ticker: str, context: DeepDiveContext) -> DeepDiveResult:
        self.deep_dive_calls.append((ticker, context))
        # Track cost for all deep-dive calls (even failed ones incur cost)
        self._deep_dive_costs_usd.append(self._deep_dive_cost_usd)
        if ticker in self._fail:
            raise self._fail[ticker]
        if ticker not in self.deep_dives:
            raise KeyError(f"FakeHaikuSession has no canned deep-dive for {ticker!r}")
        return self.deep_dives[ticker]

    async def disconnect(self) -> None:
        """Disconnect hook (no-op for fake session, for protocol compatibility)."""
        pass

    def get_accumulated_costs(self) -> dict[str, float]:
        """Return accumulated costs from all calls made by this session.

        Returns:
            dict with keys 'sweep' and 'deep_dive' where:
              - 'sweep': total cost of the sweep call (0.0 if not called)
              - 'deep_dive': sum of all deep-dive call costs (0.0 if none called)
        """
        return {
            'sweep': self._sweep_cost_usd if self.sweep_calls else 0.0,
            'deep_dive': sum(self._deep_dive_costs_usd),
        }


class FakeCompilationSession:
    """Canned, deterministic compilation output. Records every call's
    candidate-ticker list so tests can assert exactly-one-call-per-run and
    inspect exactly what was sent.

    Args:
        cost_usd: overrides FAKE_COMPILATION_COST_USD for testing purposes
            (e.g., testing with an artificially huge cost).
    """

    def __init__(self, cost_usd: float | None = None):
        self.calls: list[list[str]] = []  # one entry per call: tickers passed in, in order
        self._cost_usd = cost_usd if cost_usd is not None else FAKE_COMPILATION_COST_USD

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

    def get_accumulated_costs(self) -> dict[str, float]:
        """Return accumulated costs from all calls made by this session.

        Returns:
            dict with key 'compilation' where:
              - 'compilation': total cost of the compilation call (0.0 if not called)
        """
        return {
            'compilation': self._cost_usd if self.calls else 0.0,
        }
