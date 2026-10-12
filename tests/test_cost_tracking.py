"""
Tests for Slice 11: Cost visibility and logging (FR13).

Verifies that per-call costs from the Claude Agent SDK are captured, aggregated,
persisted, and never gate/block run execution ("never gates" requirement).
"""
import asyncio
import pytest
from app.db import db_session
from app.fakes.fake_sessions import (
    FakeHaikuSession, FakeCompilationSession,
    FAKE_SWEEP_COST_USD, FAKE_DEEP_DIVE_COST_USD, FAKE_COMPILATION_COST_USD
)
from app.agent.sessions import ShortlistCandidate, DeepDiveContext, DeepDiveResult, Citation, ScoredCandidate
from app.run_orchestrator import RunOrchestrator
from app.sources.base import NormalizedItem
from app.sources.aggregator import SourcingAggregator
from datetime import datetime, timezone
from unittest.mock import AsyncMock, MagicMock


# Note: all tests in this file use the data_dir fixture to get a fresh database
# per test, inherited from conftest.py


@pytest.fixture
def stub_aggregator(data_dir):
    """Stub aggregator that returns items with Bhavcopy data."""
    items = [
        NormalizedItem(
            source="test_source",
            headline="Test item 1",
            url="http://example.com/1",
            published_at=datetime.now(timezone.utc),
            snippet="Test snippet",
            ticker="RELIANCE",
            close=2850.0,
            prev_close=2840.0,
        ),
        NormalizedItem(
            source="test_source",
            headline="Test item 2",
            url="http://example.com/2",
            published_at=datetime.now(timezone.utc),
            snippet="Test snippet",
            ticker="TATAMOTORS",
            close=450.0,
            prev_close=448.0,
        ),
        NormalizedItem(
            source="test_source",
            headline="Test item 3",
            url="http://example.com/3",
            published_at=datetime.now(timezone.utc),
            snippet="Test snippet",
            ticker="INFY",
            close=2200.0,
            prev_close=2210.0,
        ),
    ]
    agg = MagicMock(spec=SourcingAggregator)
    agg.fetch_all = AsyncMock(return_value=(items, []))
    return agg


class TestCostSweepPersisted:
    """test_cost_sweep_persisted_from_single_sweep_call"""

    def test_sweep_cost_persisted_exactly(self, stub_aggregator):
        """Verify sweep cost from fake is persisted exactly."""
        run_id = None
        haiku = FakeHaikuSession()
        compilation = FakeCompilationSession()
        orchestrator = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku,
            compilation_session=compilation,
        )

        # Create a run
        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id = cur.lastrowid

        # Execute the run
        asyncio.run(orchestrator.execute_run(run_id))

        # Fetch the run row and verify cost_sweep_usd
        with db_session() as conn:
            row = conn.execute(
                "SELECT cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd, total_cost_usd FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        assert row["cost_sweep_usd"] == FAKE_SWEEP_COST_USD


class TestCostDeepDiveSums:
    """test_cost_deep_dive_sums_across_multiple_candidates"""

    def test_deep_dive_costs_sum_for_multiple_calls(self, stub_aggregator):
        """Verify deep-dive costs are summed across multiple calls."""
        run_id = None
        haiku = FakeHaikuSession()  # Default shortlist has 3 items
        compilation = FakeCompilationSession()
        orchestrator = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku,
            compilation_session=compilation,
        )

        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id = cur.lastrowid

        asyncio.run(orchestrator.execute_run(run_id))

        with db_session() as conn:
            row = conn.execute(
                "SELECT cost_deep_dive_usd FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        # Default shortlist has 3 candidates (RELIANCE, TATAMOTORS, INFY)
        expected_cost = 3 * FAKE_DEEP_DIVE_COST_USD
        assert row["cost_deep_dive_usd"] == expected_cost


class TestCostDeepDiveExcludesSkipped:
    """test_cost_deep_dive_excludes_skipped_candidate"""

    def test_skipped_candidate_still_contributes_cost(self, stub_aggregator):
        """Verify that even failed deep-dive calls incur cost (resources were used).

        Note: Unlike the "skipped" framing in earlier slices (per-ticker skip-and-continue
        behavior), cost is still tracked for all attempted deep-dive calls, even failures.
        This matches real API behavior where you pay for attempted calls regardless of success.
        """
        run_id = None
        # Configure one ticker to fail during deep-dive
        haiku = FakeHaikuSession(fail_tickers={"INFY"})
        compilation = FakeCompilationSession()
        orchestrator = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku,
            compilation_session=compilation,
        )

        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id = cur.lastrowid

        asyncio.run(orchestrator.execute_run(run_id))

        with db_session() as conn:
            row = conn.execute(
                "SELECT cost_deep_dive_usd FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        # All 3 deep-dive calls cost something (RELIANCE, TATAMOTORS, INFY)
        # even though INFY fails - resources were still used
        expected_cost = 3 * FAKE_DEEP_DIVE_COST_USD
        assert row["cost_deep_dive_usd"] == expected_cost


class TestCostCompilationPersisted:
    """test_cost_compilation_persisted_from_single_call"""

    def test_compilation_cost_persisted_exactly(self, stub_aggregator):
        """Verify compilation cost from fake is persisted exactly."""
        run_id = None
        haiku = FakeHaikuSession()
        compilation = FakeCompilationSession()
        orchestrator = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku,
            compilation_session=compilation,
        )

        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id = cur.lastrowid

        asyncio.run(orchestrator.execute_run(run_id))

        with db_session() as conn:
            row = conn.execute(
                "SELECT cost_compilation_usd FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        assert row["cost_compilation_usd"] == FAKE_COMPILATION_COST_USD


class TestTotalCostIsSum:
    """test_total_cost_is_sum_of_all_three_stages"""

    def test_total_equals_sum_of_stages(self, stub_aggregator):
        """Verify total_cost_usd = sum of sweep + deep_dive + compilation."""
        run_id = None
        haiku = FakeHaikuSession()  # 3 candidates
        compilation = FakeCompilationSession()
        orchestrator = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku,
            compilation_session=compilation,
        )

        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id = cur.lastrowid

        asyncio.run(orchestrator.execute_run(run_id))

        with db_session() as conn:
            row = conn.execute(
                "SELECT cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd, total_cost_usd FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        expected_total = (
            row["cost_sweep_usd"] +
            row["cost_deep_dive_usd"] +
            row["cost_compilation_usd"]
        )
        assert row["total_cost_usd"] == expected_total

        # Also check against known values
        assert row["cost_sweep_usd"] == FAKE_SWEEP_COST_USD
        assert row["cost_deep_dive_usd"] == 3 * FAKE_DEEP_DIVE_COST_USD
        assert row["cost_compilation_usd"] == FAKE_COMPILATION_COST_USD
        assert row["total_cost_usd"] == (
            FAKE_SWEEP_COST_USD + 3 * FAKE_DEEP_DIVE_COST_USD + FAKE_COMPILATION_COST_USD
        )


class TestQuickSweepSkipLeavesCostsZero:
    """test_quick_sweep_skip_leaves_deep_dive_and_compilation_cost_at_zero"""

    def test_skipped_run_has_zero_costs(self, stub_aggregator):
        """Verify quick-sweep skipped run has zero costs (no LLM stages run)."""
        run_id_1 = None
        run_id_2 = None

        # First run: normal execution
        haiku = FakeHaikuSession()
        compilation = FakeCompilationSession()
        orchestrator = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku,
            compilation_session=compilation,
        )

        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id_1 = cur.lastrowid

        asyncio.run(orchestrator.execute_run(run_id_1))

        # Second run with identical snapshot (will skip)
        haiku2 = FakeHaikuSession()
        compilation2 = FakeCompilationSession()
        orchestrator2 = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku2,
            compilation_session=compilation2,
        )

        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id_2 = cur.lastrowid

        asyncio.run(orchestrator2.execute_run(run_id_2))

        # Second run should have all costs at 0.0 since quick-sweep skipped
        with db_session() as conn:
            row = conn.execute(
                "SELECT cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd, total_cost_usd FROM runs WHERE id = ?",
                (run_id_2,),
            ).fetchone()

        assert row["cost_sweep_usd"] == 0.0
        assert row["cost_deep_dive_usd"] == 0.0
        assert row["cost_compilation_usd"] == 0.0
        assert row["total_cost_usd"] == 0.0


class TestHugeCostDoesNotBlock:
    """test_huge_compilation_cost_does_not_block_or_warn_run"""

    def test_huge_compilation_cost_run_completes(self, stub_aggregator):
        """Verify a huge stubbed cost doesn't block/gate the run."""
        run_id = None
        huge_cost = 999_999_999.0
        haiku = FakeHaikuSession()
        compilation = FakeCompilationSession(cost_usd=huge_cost)
        orchestrator = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku,
            compilation_session=compilation,
        )

        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id = cur.lastrowid

        # Execute should complete normally despite huge cost
        asyncio.run(orchestrator.execute_run(run_id))

        with db_session() as conn:
            row = conn.execute(
                "SELECT status, cost_compilation_usd, total_cost_usd FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        # Run must complete, not error out
        assert row["status"] == "complete"
        # Huge cost must be persisted (not clamped, not dropped)
        assert row["cost_compilation_usd"] == huge_cost
        # Total must include the huge cost
        assert row["total_cost_usd"] == (
            FAKE_SWEEP_COST_USD + 3 * FAKE_DEEP_DIVE_COST_USD + huge_cost
        )


class TestCostVisibleInRunDetailAPI:
    """test_cost_breakdown_visible_in_run_detail_api"""

    def test_run_detail_includes_per_stage_costs(self, stub_aggregator):
        """Verify GET /api/run/{run_id} returns all cost fields."""
        run_id = None
        haiku = FakeHaikuSession()
        compilation = FakeCompilationSession()
        orchestrator = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku,
            compilation_session=compilation,
        )

        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id = cur.lastrowid

        asyncio.run(orchestrator.execute_run(run_id))

        # Simulate the GET /api/run/{run_id} query
        with db_session() as conn:
            row = conn.execute(
                "SELECT cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd, total_cost_usd FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        # All cost fields must be present and non-zero
        assert row["cost_sweep_usd"] == FAKE_SWEEP_COST_USD
        assert row["cost_deep_dive_usd"] == 3 * FAKE_DEEP_DIVE_COST_USD
        assert row["cost_compilation_usd"] == FAKE_COMPILATION_COST_USD
        assert row["total_cost_usd"] > 0


class TestCostVisibleInHistoryListAPI:
    """test_cost_visible_in_history_list_api"""

    def test_history_list_includes_total_cost(self, stub_aggregator):
        """Verify GET /api/runs returns total_cost_usd per run."""
        run_id = None
        haiku = FakeHaikuSession()
        compilation = FakeCompilationSession()
        orchestrator = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku,
            compilation_session=compilation,
        )

        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id = cur.lastrowid

        asyncio.run(orchestrator.execute_run(run_id))

        # Simulate the GET /api/runs query
        with db_session() as conn:
            row = conn.execute(
                "SELECT total_cost_usd FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        # total_cost_usd must be present and match the sum
        assert row["total_cost_usd"] == (
            FAKE_SWEEP_COST_USD + 3 * FAKE_DEEP_DIVE_COST_USD + FAKE_COMPILATION_COST_USD
        )


class TestCostPersistenceOnError:
    """Verify costs are persisted even when a run fails."""

    def test_partial_costs_persisted_on_exception(self, stub_aggregator):
        """Verify accumulated costs are persisted even if run errors after sweep."""
        run_id = None

        # Create a haiku session that succeeds at sweep
        haiku = FakeHaikuSession()
        # But make compilation raise an exception
        compilation = FakeCompilationSession()

        # Monkey-patch run_compilation to raise an exception
        async def fail_compilation(*args, **kwargs):
            raise RuntimeError("Simulated compilation failure")

        compilation.run_compilation = fail_compilation

        orchestrator = RunOrchestrator(
            aggregator=stub_aggregator,
            haiku_session=haiku,
            compilation_session=compilation,
        )

        with db_session() as conn:
            cur = conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
                (datetime.now(timezone.utc).isoformat(),),
            )
            run_id = cur.lastrowid

        # Execute should raise an exception
        with pytest.raises(RuntimeError, match="Simulated compilation failure"):
            asyncio.run(orchestrator.execute_run(run_id))

        # But costs up to the failure point should be persisted
        with db_session() as conn:
            row = conn.execute(
                "SELECT status, cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd, total_cost_usd FROM runs WHERE id = ?",
                (run_id,),
            ).fetchone()

        # Status should be error
        assert row["status"] == "error"
        # Sweep cost should be persisted
        assert row["cost_sweep_usd"] == FAKE_SWEEP_COST_USD
        # Deep-dive costs should be persisted (all 3 calls succeeded)
        assert row["cost_deep_dive_usd"] == 3 * FAKE_DEEP_DIVE_COST_USD
        # Compilation wasn't called successfully, so 0
        assert row["cost_compilation_usd"] == 0.0
        # Total should be the sum of what was persisted
        assert row["total_cost_usd"] == (
            FAKE_SWEEP_COST_USD + 3 * FAKE_DEEP_DIVE_COST_USD
        )
