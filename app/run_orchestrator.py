import asyncio
import logging
from datetime import datetime, timezone, date

from app.agent.sweep import run_sweep_stage
from app.agent.deep_dive import run_deep_dive_stage
from app.agent.compilation import run_compilation_stage, extract_compilation_commentary
from app.agent.sessions import DeepDiveContext, ScoredCandidate, Citation, FinalCandidate
from app.assembly import assemble
from app.db import (
    db_session, insert_sweep_items, set_failed_sources, get_sweep_items,
    get_prior_comparable_run, insert_candidate, insert_idea_placeholder, insert_assembled_ideas
)
from app.quick_sweep import compute_hash, compare_to_prior, format_skip_message
from app.run_lock import run_lock
from app.scoring import compute_score
from app.negative_filters import evaluate_negative_filters
from app.sources.aggregator import SourcingAggregator
from app.sources.base import NormalizedItem

log = logging.getLogger(__name__)

# Hardcoded fake idea (Slice 0 only) -- proves the end-to-end pipeline wiring
# (UI -> API -> run-lock -> background task -> SQLite -> polling -> UI) works
# before any real data sourcing or LLM analysis is introduced. Replaced by
# real sourcing/scoring starting Slice 1+.
FAKE_IDEA = {
    "ticker": "RELIANCE",
    "entry": 2850.00,
    "target": 2990.00,
    "hold_days": 7,
    "tier": "green",
    "score": None,
    "sub_score_catalyst": None,
    "sub_score_momentum": None,
    "sub_score_macro": None,
    "rationale": (
        "Fake Slice-0 idea: placeholder rationale text used only to prove the "
        "end-to-end pipeline wiring (UI -> API -> run-lock -> background task "
        "-> SQLite -> polling -> UI) works before any real data sourcing or "
        "LLM analysis is introduced. This is not a real trade recommendation."
    ),
    "citation_url": "https://example.com/fake-citation",
    "citation_source": None,
    "citation_headline": None,
    "low_confidence": 0,
    "rank": 1,
}

DISCLAIMER = (
    "For personal informational use only. Not investment advice. Not a "
    "registered investment adviser. No trades are placed automatically -- "
    "review and decide manually."
)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _resolve_entry_price(context: DeepDiveContext | None) -> float | None:
    """Resolve the entry (buy) reference price for one ticker, deterministically.

    Per tech-spec §4 FR6/§8, every idea must include a buy price -- this is
    NEVER estimated by the LLM (Haiku has no live price access and must not
    invent one). Instead, the real NSE Bhavcopy adapter already stamped a
    `close` price onto the NormalizedItem(s) it produced for this exact
    ticker (see app/sources/nse_bhavcopy.py), and `_build_deep_dive_contexts`
    already grouped those items into this ticker's DeepDiveContext. This
    just looks that value back up.

    Returns None (never a fabricated price) if no Bhavcopy item for this
    specific ticker exists in the context -- e.g. the ticker isn't on the
    watchlist, or the Bhavcopy adapter failed/returned nothing this run.
    Callers must drop the idea rather than substitute 0.0 or any other
    placeholder, since a buy price is a hard requirement per the spec.
    """
    if context is None:
        return None
    for item in context.items:
        if item.ticker == context.ticker and item.close is not None:
            return item.close
    return None


def _compute_target_price(entry: float, expected_move_pct: float) -> float:
    """Deterministically compute the target price from a resolved entry
    price and Haiku's expected_move_pct signal. Mirrors compute_score being
    the sole source of truth for the final score/tier: Haiku estimates the
    move, application code computes the actual number, rounded to 2 decimal
    places (standard INR price precision)."""
    return round(entry * (1 + expected_move_pct / 100), 2)


class RunOrchestrator:
    """The `runs` row (status='running') is inserted by the route handler
    before this is scheduled. execute_run() runs a real sourcing step via
    the SourcingAggregator (Slice 1: a single Moneycontrol RSS adapter;
    Slice 2+: Moneycontrol + Bhavcopy + Screener.in + Trading Economics,
    merged with per-adapter failure isolation) whose failure is isolated
    and never aborts the run, then -- Slice 4+ -- runs sweep and deep-dive
    stages via a HaikuSession. No RunEvent streaming (no SSE) -- progress
    is inferred purely by polling run status.

    `aggregator` and `haiku_session` are constructor-injected (defaults to
    real SourcingAggregator and FakeHaikuSession respectively) so tests can
    swap in stub implementations without monkeypatching, mirroring the
    sibling's injectable-port style."""

    def __init__(self, aggregator: SourcingAggregator | None = None, haiku_session = None, compilation_session = None):
        self.aggregator = aggregator or SourcingAggregator()
        if haiku_session is None:
            haiku_session = self._build_haiku_session()
        self.haiku_session = haiku_session
        if compilation_session is None:
            compilation_session = self._build_compilation_session()
        self.compilation_session = compilation_session

    def _build_haiku_session(self):
        """Build a HaikuSession: defaults to fake for tests.

        Tests default to fake (they don't override the default and don't
        set env vars). The app wiring must explicitly pass real session
        when desired (based on SWINGTRADE_HAIKU_SESSION env var).
        """
        from app.fakes.fake_sessions import FakeHaikuSession
        return FakeHaikuSession()

    def _build_compilation_session(self):
        """Build a CompilationSession: defaults to fake for tests.

        Tests default to fake (they don't override the default and don't
        set env vars). The app wiring must explicitly pass real session
        when desired (based on SWINGTRADE_COMPILATION_SESSION env var).
        """
        from app.fakes.fake_sessions import FakeCompilationSession
        return FakeCompilationSession()

    async def _run_sourcing_step(self, run_id: int) -> None:
        """Fetches this run's sourcing items from every configured adapter
        (merged, per-adapter-failure-isolated by the aggregator) and
        persists them, along with which adapters (if any) failed. A
        sourcing failure -- even a total one, all adapters down -- is never
        a run failure: it's logged and the run proceeds with whatever
        subset of items is available (possibly zero), exactly the
        resilience behavior the acceptance criteria require."""
        items, failed_sources = await self.aggregator.fetch_all()
        with db_session() as conn:
            insert_sweep_items(conn, run_id, items)
            set_failed_sources(conn, run_id, failed_sources)

    def _build_deep_dive_contexts(
        self, items: list[NormalizedItem], shortlist
    ) -> dict[str, DeepDiveContext]:
        """Build DeepDiveContext for each ticker in the shortlist.

        Groups already-fetched NormalizedItems by ticker. Items with no ticker
        are included for every shortlisted ticker as general market/macro
        background (no ticker-mapping logic exists yet).
        """
        context_by_ticker = {}
        for candidate in shortlist:
            ticker = candidate.ticker
            # Items matching this ticker + items with no ticker
            ticker_items = [
                item for item in items
                if item.ticker == ticker or item.ticker is None
            ]
            context_by_ticker[ticker] = DeepDiveContext(
                ticker=ticker,
                items=ticker_items,
            )
        return context_by_ticker

    async def _run_llm_stages(self, run_id: int) -> None:
        """Slice 4+: Haiku sweep and deep-dive stages.

        Step 3: Call sweep to narrow the full sourced item set to a shortlist.
        Step 4: Call deep-dive once per shortlisted ticker, with per-stock
                failure handling via skip-and-continue.
        Step 4b: Persist each surviving candidate to the candidates table
                 and mirror into ideas with placeholder tier for UI rendering.

        Slice 11: Tracks per-stage costs and persists them to the runs row.
        """
        # Cost accumulators (Slice 11)
        cost_sweep_usd = 0.0
        cost_deep_dive_usd = 0.0
        cost_compilation_usd = 0.0

        try:
            with db_session() as conn:
                sweep_rows = get_sweep_items(conn, run_id)
                items = [
                    NormalizedItem(
                        source=row["source"],
                        headline=row["headline"],
                        url=row["url"],
                        published_at=datetime.fromisoformat(row["published_at"]),
                        snippet=row["snippet"],
                        ticker=row["ticker"],
                        close=row["close"],
                        prev_close=row["prev_close"],
                        volume=row["volume"],
                        pe_ratio=row["pe_ratio"],
                        market_cap_cr=row["market_cap_cr"],
                        indicator_name=row["indicator_name"],
                        indicator_value=row["indicator_value"],
                    )
                    for row in sweep_rows
                ]

            # Step 3: sweep stage -- narrow the full sourced item set to a shortlist.
            shortlist = await run_sweep_stage(self.haiku_session, items)

            # Capture sweep stage cost (Slice 11)
            if hasattr(self.haiku_session, 'get_accumulated_costs'):
                costs = self.haiku_session.get_accumulated_costs()
                cost_sweep_usd = costs.get('sweep', 0.0)

            # Step 4: deep-dive stage -- one call per shortlisted ticker,
            # per-stock failure handling via skip-and-continue (locked decision).
            context_by_ticker = self._build_deep_dive_contexts(items, shortlist)
            deep_dive_results = await run_deep_dive_stage(
                self.haiku_session, shortlist, context_by_ticker
            )

            # Capture deep-dive stage cost (Slice 11)
            if hasattr(self.haiku_session, 'get_accumulated_costs'):
                costs = self.haiku_session.get_accumulated_costs()
                cost_deep_dive_usd = costs.get('deep_dive', 0.0)

            # Step 5: deterministic scoring (Slice 5) -- compute score/tier from
            # the three pre-weighted sub-scores returned by Slice 4's deep-dive.
            # Defense-in-depth: parse_deep_dive_response already validates
            # macro_subscore against the same {15,20,25} set compute_score
            # expects, so this should never raise in practice -- but a single
            # out-of-range value must skip that one candidate, not crash the
            # whole run (same per-ticker skip-and-continue policy as above).
            scored_results = []
            for result in deep_dive_results:
                try:
                    score_result = compute_score(
                        result.catalyst_subscore,
                        result.sector_momentum_subscore,
                        result.macro_subscore,
                    )
                except ValueError:
                    log.warning(
                        "scoring failed for %s; skipping", result.ticker, exc_info=True
                    )
                    continue
                result.score = score_result.score
                result.tier = score_result.tier
                scored_results.append(result)
            deep_dive_results = scored_results

            # Step 6: negative filtering (Slice 6) -- evaluate pump-and-dump and
            # stale-news exclusion criteria. Excluded candidates are still persisted
            # for audit (excluded=1, with reason), but not included in surviving_candidates.
            run_date = date.today()
            surviving_candidates = []
            for result in deep_dive_results:
                try:
                    filter_result = evaluate_negative_filters(result, run_date)
                except Exception:
                    log.warning(
                        "negative-filter evaluation failed for %s; skipping",
                        result.ticker,
                        exc_info=True,
                    )
                    continue
                result.excluded = filter_result.excluded
                result.exclusion_reason = filter_result.exclusion_reason
                if not filter_result.excluded:
                    surviving_candidates.append(result)

            # Step 7: compilation stage (Slice 8) -- convert surviving_candidates to
            # ScoredCandidate objects and call the compilation session for polished
            # rationale and ranking commentary. This runs exactly once over ALL
            # surviving candidates together (not per-candidate).
            compilation_result = None
            if surviving_candidates:
                scored_candidates = [
                    ScoredCandidate(
                        ticker=result.ticker,
                        score=result.score,
                        tier=result.tier,
                        sub_score_catalyst=result.catalyst_subscore,
                        sub_score_momentum=result.sector_momentum_subscore,
                        sub_score_macro=result.macro_subscore,
                        haiku_reasoning=(
                            f"{result.catalyst_reasoning}\n"
                            f"{result.sector_momentum_reasoning}\n"
                            f"{result.macro_reasoning}"
                        ),
                        citations=[
                            {
                                "source": cit.source,
                                "headline": cit.headline,
                                "url": cit.url,
                                "published_at": cit.published_at,
                                "snippet": cit.headline,  # use headline as snippet in compilation
                            }
                            for cit in result.citations
                        ],
                    )
                    for result in surviving_candidates
                ]
                compilation_result = await run_compilation_stage(
                    self.compilation_session, scored_candidates
                )

                # Capture compilation stage cost (Slice 11)
                if hasattr(self.compilation_session, 'get_accumulated_costs'):
                    costs = self.compilation_session.get_accumulated_costs()
                    cost_compilation_usd = costs.get('compilation', 0.0)

            # Step 8: assembly stage (Slice 9) -- build FinalCandidate objects,
            # apply cap/ordering/backfill logic, and return ranked ideas.
            final_ideas = []
            if surviving_candidates and compilation_result:
                # Build FinalCandidate objects from surviving_candidates + compilation
                final_candidates = []
                for result in surviving_candidates:
                    # Entry price: deterministic, resolved from this ticker's
                    # Bhavcopy close price (never estimated by the LLM -- see
                    # _resolve_entry_price). A buy price is a hard requirement
                    # per tech-spec §4 FR6, so a ticker with no resolvable
                    # Bhavcopy price is dropped here, before assembly/ranking,
                    # rather than persisted with a fabricated price -- mirrors
                    # the citation-drop hard constraint in app/assembly.py.
                    context = context_by_ticker.get(result.ticker)
                    entry = _resolve_entry_price(context)
                    if entry is None:
                        log.warning(
                            "no Bhavcopy entry price available for %s; dropping "
                            "idea (buy price is a hard requirement per spec)",
                            result.ticker,
                        )
                        continue

                    # Target price: deterministic, computed from Haiku's
                    # expected_move_pct signal -- mirrors compute_score being
                    # the sole source of truth for the final score.
                    target = _compute_target_price(entry, result.expected_move_pct)

                    polished_rationale, ranking_commentary = extract_compilation_commentary(
                        compilation_result, result.ticker
                    )

                    final_candidate = FinalCandidate(
                        ticker=result.ticker,
                        score=result.score,
                        tier=result.tier,
                        sub_score_catalyst=result.catalyst_subscore,
                        sub_score_momentum=result.sector_momentum_subscore,
                        sub_score_macro=result.macro_subscore,
                        citations=[
                            Citation(
                                source=cit.source,
                                headline=cit.headline,
                                url=cit.url,
                                published_at=cit.published_at,
                            )
                            for cit in result.citations
                        ],
                        polished_rationale=polished_rationale,
                        ranking_commentary_fragment=ranking_commentary,
                        entry=entry,
                        target=target,
                        hold_days=result.hold_days,
                    )
                    final_candidates.append(final_candidate)

                # Apply assembly logic: cap, order, backfill
                final_ideas = assemble(final_candidates)

            # Step 9: persistence -- write candidates (all) and ideas (final assembled + excluded)
            # to their respective tables, and update cost columns (Slice 11).
            total_cost_usd = cost_sweep_usd + cost_deep_dive_usd + cost_compilation_usd
            with db_session() as conn:
                # Persist all candidates (surviving + excluded) to candidates table for audit
                for result in deep_dive_results:
                    insert_candidate(conn, run_id, result)

                # Persist final assembled ideas (capped, ordered, ranked, backfilled)
                if final_ideas:
                    insert_assembled_ideas(conn, run_id, final_ideas)

                # Persist excluded candidates to ideas table for audit trail
                for result in deep_dive_results:
                    if result.excluded:
                        insert_idea_placeholder(conn, run_id, result, 0, "", 0)

                # Persist cost columns (Slice 11)
                conn.execute(
                    "UPDATE runs SET cost_sweep_usd = ?, cost_deep_dive_usd = ?, "
                    "cost_compilation_usd = ?, total_cost_usd = ? WHERE id = ?",
                    (cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd, total_cost_usd, run_id),
                )

            # Return costs for potential re-persistence in execute_run (Slice 11)
            return {
                'sweep': cost_sweep_usd,
                'deep_dive': cost_deep_dive_usd,
                'compilation': cost_compilation_usd,
                'total': total_cost_usd,
            }
        except Exception:
            # On exception, persist accumulated costs before re-raising (Slice 11)
            # This ensures partial costs (e.g., from a failed sweep) are recorded
            total_cost_usd = cost_sweep_usd + cost_deep_dive_usd + cost_compilation_usd
            with db_session() as conn:
                conn.execute(
                    "UPDATE runs SET cost_sweep_usd = ?, cost_deep_dive_usd = ?, "
                    "cost_compilation_usd = ?, total_cost_usd = ? WHERE id = ?",
                    (cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd, total_cost_usd, run_id),
                )
            raise
        finally:
            # Ensure Haiku session is disconnected before Slice 8's Sonnet stage begins
            # (or before the run ends, if compilation is not yet implemented).
            # This is critical for real sessions; safe for fake sessions.
            if hasattr(self.haiku_session, "disconnect"):
                await self.haiku_session.disconnect()

    async def _run_quick_sweep_check(self, run_id: int) -> tuple[bool, str | None]:
        """Quick-sweep change detection (Slice 3): compute hash, compare to prior,
        decide whether to skip or proceed.

        Returns: (should_skip, skip_message_or_none)
        If should_skip is True, the run has been marked complete with
        quick_sweep_skipped=1 and source_run_id set; the LLM stages should
        not be called. If False, proceed normally to LLM stages.
        """
        with db_session() as conn:
            # Fetch this run's sweep items
            sweep_rows = get_sweep_items(conn, run_id)
            items = [
                {
                    "source": row["source"],
                    "headline": row["headline"],
                    "ticker": row["ticker"],
                    "published_at": row["published_at"],
                }
                for row in sweep_rows
            ]

            # Convert to NormalizedItem-like objects for hashing
            from app.sources.base import NormalizedItem

            norm_items = [
                NormalizedItem(
                    source=item["source"],
                    headline=item["headline"],
                    url="",  # Not used for hashing
                    published_at=datetime.fromisoformat(item["published_at"]),
                    snippet="",  # Not used for hashing
                    ticker=item["ticker"],
                )
                for item in items
            ]

            # Compute current hash
            current_hash = compute_hash(norm_items)

            # Look up prior run
            prior_run = get_prior_comparable_run(conn, run_id)

            # Compare
            result = compare_to_prior(current_hash, prior_run["quick_sweep_hash"] if prior_run else None)

            # Persist current hash on this run (always, even if skipping)
            conn.execute(
                "UPDATE runs SET quick_sweep_hash = ? WHERE id = ?",
                (result.current_hash, run_id),
            )

            # If no material change, skip the LLM stages
            if not result.material_change and prior_run:
                ideas_owner_run_id = prior_run["ideas_owner_run_id"]
                skip_message = format_skip_message(ideas_owner_run_id, prior_run["finished_at"])
                # When quick-sweep skips, cost columns remain at their DEFAULT 0.0
                # (no LLM stages were invoked)
                conn.execute(
                    "UPDATE runs SET status = 'complete', finished_at = ?, "
                    "quick_sweep_skipped = 1, source_run_id = ?, "
                    "cost_sweep_usd = 0.0, cost_deep_dive_usd = 0.0, "
                    "cost_compilation_usd = 0.0, total_cost_usd = 0.0 WHERE id = ?",
                    (_now_iso(), ideas_owner_run_id, run_id),
                )
                return True, skip_message
            else:
                # Material change or first-ever run: proceed normally
                conn.execute(
                    "UPDATE runs SET quick_sweep_skipped = 0 WHERE id = ?",
                    (run_id,),
                )
                return False, None

    async def execute_run(self, run_id: int) -> None:
        try:
            await self._run_sourcing_step(run_id)

            # Slice 3: Quick-sweep change detection
            should_skip, skip_message = await self._run_quick_sweep_check(run_id)
            if should_skip:
                # Skip path: run already marked complete with source_run_id set
                return

            # Not skipped: proceed to LLM stages
            await self._run_llm_stages(run_id)

            with db_session() as conn:
                conn.execute(
                    "UPDATE runs SET status = 'complete', finished_at = ? WHERE id = ?",
                    (_now_iso(), run_id),
                )
        except Exception:
            with db_session() as conn:
                conn.execute(
                    "UPDATE runs SET status = 'error', finished_at = ? WHERE id = ?",
                    (_now_iso(), run_id),
                )
            raise
        finally:
            run_lock.release()


def _create_app_orchestrator():
    """Create the orchestrator used by the app.

    Uses config (SWINGTRADE_HAIKU_SESSION, SWINGTRADE_COMPILATION_SESSION env vars)
    to select real or fake sessions. Defaults to fake for safety; explicitly set
    env vars to 'real' to use real sessions.
    """
    from app import config
    from app.agent.haiku_session import RealHaikuSession
    from app.agent.sonnet_session import SonnetCompilationSession
    from app.fakes.fake_sessions import FakeHaikuSession, FakeCompilationSession

    haiku_mode = config.haiku_session_mode()
    haiku_session = RealHaikuSession() if haiku_mode == "real" else FakeHaikuSession()

    compilation_mode = config.compilation_session_mode()
    compilation_session = SonnetCompilationSession() if compilation_mode == "real" else FakeCompilationSession()

    return RunOrchestrator(haiku_session=haiku_session, compilation_session=compilation_session)


run_orchestrator = _create_app_orchestrator()
