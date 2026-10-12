"""Integration tests for quick-sweep orchestrator wiring (Slice 3, FR2/FR12)."""

import datetime as dt
from unittest.mock import AsyncMock, patch
import json

import pytest

from app.db import db_session, get_connection
from app.run_orchestrator import RunOrchestrator
from app.sources.aggregator import SourcingAggregator
from app.sources.base import NormalizedItem, SourceFetchError


class StubAdapter:
    """Test adapter that returns a fixed set of items or raises an exception."""

    def __init__(self, name, items=None, exc: Exception | None = None):
        self.name = name
        self._items = items or []
        self._exc = exc

    async def fetch(self):
        if self._exc is not None:
            raise self._exc
        return self._items


def _item(
    source: str,
    headline: str = "test headline",
    ticker: str | None = None,
    published_at: dt.datetime | None = None,
    n: int = 0,
) -> NormalizedItem:
    """Helper to create a NormalizedItem with defaults for testing."""
    return NormalizedItem(
        source=source,
        headline=headline or f"{source} headline {n}",
        url=f"https://example.com/{source}/{n}",
        published_at=published_at or dt.datetime.now(dt.timezone.utc),
        snippet=f"snippet {n}",
        ticker=ticker,
    )


def _insert_running_run(conn) -> int:
    """Helper to insert a test run in 'running' status."""
    cur = conn.execute(
        "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
        (dt.datetime.now(dt.timezone.utc).isoformat(),),
    )
    return cur.lastrowid


async def test_identical_snapshot_second_run_skips_llm_stage(data_dir):
    """Second run with identical sweep dataset skips LLM stage (call count assertion).

    - Run 1: fixture sweep dataset, LLM stage called (mocked), returns fake idea
    - Run 2: IDENTICAL fixture sweep dataset, LLM stage NOT called (mock call count stays 1)
    """
    # Create run 1 with a fixture sweep dataset
    with db_session() as conn:
        run_id_1 = _insert_running_run(conn)

    items_run_1 = [
        _item("src_a", headline="headline A", ticker="ABC", n=1),
        _item("src_b", headline="headline B", ticker="XYZ", n=2),
    ]

    adapters = [
        StubAdapter("src_a", items=[items_run_1[0]]),
        StubAdapter("src_b", items=[items_run_1[1]]),
    ]
    orchestrator = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters))

    # Mock _run_llm_stages to track calls
    with patch.object(orchestrator, "_run_llm_stages", new_callable=AsyncMock) as mock_llm:
        await orchestrator.execute_run(run_id_1)
        # Should have been called once for run 1
        assert mock_llm.call_count == 1

        # Create run 2 with IDENTICAL sweep items
        with db_session() as conn:
            run_id_2 = _insert_running_run(conn)

        # Use the exact same items for run 2
        items_run_2 = [
            _item("src_a", headline="headline A", ticker="ABC", n=1),
            _item("src_b", headline="headline B", ticker="XYZ", n=2),
        ]

        adapters_2 = [
            StubAdapter("src_a", items=[items_run_2[0]]),
            StubAdapter("src_b", items=[items_run_2[1]]),
        ]
        orchestrator_2 = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters_2))

        with patch.object(orchestrator_2, "_run_llm_stages", new_callable=AsyncMock) as mock_llm_2:
            await orchestrator_2.execute_run(run_id_2)
            # Run 2 should NOT have called LLM stage (identical snapshot)
            assert mock_llm_2.call_count == 0

    # Verify run 2 is marked skipped with source_run_id pointing to run 1
    with db_session() as conn:
        run_2 = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id_2,)).fetchone()
        assert run_2["quick_sweep_skipped"] == 1
        assert run_2["source_run_id"] == run_id_1
        assert run_2["status"] == "complete"


async def test_materially_different_snapshot_second_run_proceeds(data_dir):
    """Second run with materially different sweep dataset proceeds to LLM stage.

    - Run 1: fixture sweep dataset, LLM stage called (mocked)
    - Run 2: different fixture (one new headline), LLM stage IS called
    """
    # Create run 1
    with db_session() as conn:
        run_id_1 = _insert_running_run(conn)

    items_run_1 = [
        _item("src_a", headline="headline A", ticker="ABC", n=1),
    ]

    adapters = [
        StubAdapter("src_a", items=[items_run_1[0]]),
    ]
    orchestrator = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters))

    with patch.object(orchestrator, "_run_llm_stages", new_callable=AsyncMock) as mock_llm:
        await orchestrator.execute_run(run_id_1)
        assert mock_llm.call_count == 1

        # Create run 2 with a NEW item (materially different)
        with db_session() as conn:
            run_id_2 = _insert_running_run(conn)

        items_run_2 = [
            _item("src_a", headline="headline A", ticker="ABC", n=1),
            _item("src_b", headline="headline B (NEW)", ticker="XYZ", n=2),  # NEW
        ]

        adapters_2 = [
            StubAdapter("src_a", items=[items_run_2[0]]),
            StubAdapter("src_b", items=[items_run_2[1]]),
        ]
        orchestrator_2 = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters_2))

        with patch.object(orchestrator_2, "_run_llm_stages", new_callable=AsyncMock) as mock_llm_2:
            await orchestrator_2.execute_run(run_id_2)
            # Run 2 SHOULD call LLM stage (material change detected)
            assert mock_llm_2.call_count == 1

    # Verify run 2 is NOT marked skipped
    with db_session() as conn:
        run_2 = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id_2,)).fetchone()
        assert run_2["quick_sweep_skipped"] == 0
        assert run_2["source_run_id"] is None


async def test_first_ever_run_always_proceeds(data_dir):
    """First-ever run (no prior run) always proceeds to LLM stage."""
    # Create first and only run
    with db_session() as conn:
        run_id = _insert_running_run(conn)

    items = [
        _item("src_a", headline="headline A", ticker="ABC", n=1),
    ]

    adapters = [
        StubAdapter("src_a", items=[items[0]]),
    ]
    orchestrator = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters))

    with patch.object(orchestrator, "_run_llm_stages", new_callable=AsyncMock) as mock_llm:
        await orchestrator.execute_run(run_id)
        # First run always proceeds
        assert mock_llm.call_count == 1

    # Verify run is not marked skipped
    with db_session() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert run["quick_sweep_skipped"] == 0
        assert run["source_run_id"] is None


async def test_skip_persists_identical_hash(data_dir):
    """Skipped run's hash matches the prior run's hash (proving hash is persisted)."""
    # Run 1
    with db_session() as conn:
        run_id_1 = _insert_running_run(conn)

    items_1 = [
        _item("src_a", headline="headline A", ticker="ABC", n=1),
    ]

    adapters_1 = [StubAdapter("src_a", items=[items_1[0]])]
    orchestrator_1 = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters_1))

    with patch.object(orchestrator_1, "_run_llm_stages", new_callable=AsyncMock):
        await orchestrator_1.execute_run(run_id_1)

    # Get run 1's hash
    with db_session() as conn:
        run_1 = conn.execute("SELECT quick_sweep_hash FROM runs WHERE id = ?", (run_id_1,)).fetchone()
        hash_1 = run_1["quick_sweep_hash"]

    # Run 2 with identical items
    with db_session() as conn:
        run_id_2 = _insert_running_run(conn)

    items_2 = [
        _item("src_a", headline="headline A", ticker="ABC", n=1),
    ]

    adapters_2 = [StubAdapter("src_a", items=[items_2[0]])]
    orchestrator_2 = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters_2))

    with patch.object(orchestrator_2, "_run_llm_stages", new_callable=AsyncMock):
        await orchestrator_2.execute_run(run_id_2)

    # Get run 2's hash
    with db_session() as conn:
        run_2 = conn.execute("SELECT quick_sweep_hash FROM runs WHERE id = ?", (run_id_2,)).fetchone()
        hash_2 = run_2["quick_sweep_hash"]

    # Hashes should be identical
    assert hash_1 == hash_2


async def test_errored_prior_run_excluded_from_comparison(data_dir):
    """Errored run is skipped in prior-run lookup; correct run is used."""
    # Create items for run 0
    items_run_0 = [
        _item("src_a", headline="headline A", ticker="ABC", n=1),
    ]

    # Run 0 to compute its hash
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            (dt.datetime.now(dt.timezone.utc).isoformat(),),
        )
        run_id_0 = cur.lastrowid

    adapters_0 = [StubAdapter("src_a", items=[items_run_0[0]])]
    orchestrator_0 = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters_0))

    with patch.object(orchestrator_0, "_run_llm_stages", new_callable=AsyncMock):
        await orchestrator_0.execute_run(run_id_0)

    # Get run 0's hash
    with db_session() as conn:
        run_0 = conn.execute("SELECT quick_sweep_hash FROM runs WHERE id = ?", (run_id_0,)).fetchone()
        hash_0 = run_0["quick_sweep_hash"]

    # Insert run 1 (errored, should be skipped)
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status, quick_sweep_hash) VALUES (?, ?, ?)",
            (dt.datetime.now(dt.timezone.utc).isoformat(), "error", None),
        )
        run_id_1 = cur.lastrowid

    # Insert run 2 (will be run normally)
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            (dt.datetime.now(dt.timezone.utc).isoformat(),),
        )
        run_id_2 = cur.lastrowid

    # Run 2 with items identical to run 0
    items_run_2 = [
        _item("src_a", headline="headline A", ticker="ABC", n=1),
    ]

    adapters_2 = [StubAdapter("src_a", items=[items_run_2[0]])]
    orchestrator_2 = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters_2))

    with patch.object(orchestrator_2, "_run_llm_stages", new_callable=AsyncMock):
        await orchestrator_2.execute_run(run_id_2)

    # Run 2 should skip and reference run 0 (not run 1, which is errored)
    with db_session() as conn:
        run_2 = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id_2,)).fetchone()
        assert run_2["quick_sweep_skipped"] == 1
        assert run_2["source_run_id"] == run_id_0  # References run 0, not 1
        # Hashes should match (run 0 and 2 have identical items)
        assert run_2["quick_sweep_hash"] == hash_0


async def test_skip_response_includes_prior_run_ideas(client):
    """API response for a skipped run includes the prior run's ideas and message."""
    # Create run 1 with a fixture sweep and complete it (don't mock, let real code run)
    with db_session() as conn:
        run_id_1 = _insert_running_run(conn)

    # Includes Bhavcopy-style close prices for the default FakeHaikuSession
    # shortlist (RELIANCE, TATAMOTORS, INFY) so entry-price resolution
    # succeeds and run 1 actually produces ideas -- otherwise every idea
    # would be dropped for lacking a buy price and this test's "ideas from
    # run 1" assertion below would fail. The identical extra items are also
    # added to run 2's set so the quick-sweep hash still matches (only
    # ticker/headline/source/date feed the hash, not `close` -- see
    # app/quick_sweep.py's _normalize_identity_key/_build_identity_tuples).
    bhav_items = [
        NormalizedItem(
            source="nse_bhavcopy",
            headline=f"{t} EOD",
            url=f"https://example.com/nse_bhavcopy/{t}",
            published_at=dt.datetime.now(dt.timezone.utc),
            snippet=f"{t} EOD price",
            ticker=t,
            close=close,
        )
        for t, close in [("RELIANCE", 2900.0), ("TATAMOTORS", 950.0), ("INFY", 1550.0)]
    ]

    items_1 = [
        _item("src_a", headline="headline A", ticker="ABC", n=1),
    ] + bhav_items

    adapters_1 = [
        StubAdapter("src_a", items=[items_1[0]]),
        StubAdapter("nse_bhavcopy", items=bhav_items),
    ]
    orchestrator_1 = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters_1))

    # Run 1 without mocking - this will call _run_llm_stages and insert fake idea
    await orchestrator_1.execute_run(run_id_1)

    # Create run 2 with identical items (will skip)
    with db_session() as conn:
        run_id_2 = _insert_running_run(conn)

    items_2 = [
        _item("src_a", headline="headline A", ticker="ABC", n=1),
    ] + bhav_items

    adapters_2 = [
        StubAdapter("src_a", items=[items_2[0]]),
        StubAdapter("nse_bhavcopy", items=bhav_items),
    ]
    orchestrator_2 = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters_2))

    # Mock for run 2 to verify LLM stage is NOT called
    with patch.object(orchestrator_2, "_run_llm_stages", new_callable=AsyncMock) as mock_llm_2:
        await orchestrator_2.execute_run(run_id_2)
        # Verify LLM stage was NOT called
        assert mock_llm_2.call_count == 0

    # Query the API for the last run
    response = client.get("/api/run/last")
    data = response.json()

    # Should be run 2, but marked as skipped with ideas from run 1
    assert data["has_run"] is True
    assert data["run_id"] == run_id_2
    assert data["quick_sweep_skipped"] is True
    assert data["source_run_id"] == run_id_1
    assert data["quick_sweep_message"] is not None
    assert f"run #{run_id_1}" in data["quick_sweep_message"]
    # Should have ideas from run 1
    assert len(data["ideas"]) > 0


async def test_first_run_without_llm_stage_call(data_dir):
    """First run proceeds through quick-sweep check without skipping."""
    with db_session() as conn:
        run_id = _insert_running_run(conn)

    items = [
        _item("src_a", headline="headline A", ticker="ABC", n=1),
    ]

    adapters = [StubAdapter("src_a", items=[items[0]])]
    orchestrator = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters))

    with patch.object(orchestrator, "_run_llm_stages", new_callable=AsyncMock) as mock_llm:
        await orchestrator.execute_run(run_id)
        # First run should call LLM stage
        assert mock_llm.call_count == 1

    with db_session() as conn:
        run = conn.execute("SELECT * FROM runs WHERE id = ?", (run_id,)).fetchone()
        assert run["quick_sweep_skipped"] == 0
        assert run["quick_sweep_hash"] is not None
