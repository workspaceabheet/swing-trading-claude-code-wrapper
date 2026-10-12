import datetime as dt
import json
import sqlite3

import pytest

from app.db import db_session, get_connection
from app.run_orchestrator import RunOrchestrator
from app.sources.aggregator import SourcingAggregator
from app.sources.base import NormalizedItem, SourceFetchError


class StubAdapter:
    def __init__(self, name, items=None, exc: Exception | None = None):
        self.name = name
        self._items = items or []
        self._exc = exc

    async def fetch(self):
        if self._exc is not None:
            raise self._exc
        return self._items


def _item(source, n=0):
    return NormalizedItem(
        source=source,
        headline=f"{source} headline {n}",
        url=f"https://example.com/{source}/{n}",
        published_at=dt.datetime.now(dt.timezone.utc),
        snippet=f"snippet {n}",
    )


def _insert_running_run(conn) -> int:
    cur = conn.execute(
        "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
        (dt.datetime.now(dt.timezone.utc).isoformat(),),
    )
    return cur.lastrowid


async def test_run_persists_merged_multi_source_items(data_dir):
    with db_session() as conn:
        run_id = _insert_running_run(conn)

    adapters = [
        StubAdapter("stub_a", items=[_item("stub_a", 1), _item("stub_a", 2)]),
        StubAdapter("stub_b", items=[_item("stub_b", 1)]),
    ]
    orchestrator = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters))
    await orchestrator.execute_run(run_id)

    with db_session() as conn:
        rows = conn.execute(
            "SELECT source FROM sweep_items WHERE run_id = ?", (run_id,)
        ).fetchall()
    sources = [row["source"] for row in rows]
    assert sources.count("stub_a") == 2
    assert sources.count("stub_b") == 1

    with db_session() as conn:
        run_row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
    assert run_row["status"] == "complete"


async def test_run_records_failed_sources_on_run_row(data_dir):
    with db_session() as conn:
        run_id = _insert_running_run(conn)

    adapters = [
        StubAdapter("stub_ok", items=[_item("stub_ok", 1)]),
        StubAdapter("stub_broken", exc=SourceFetchError("down")),
    ]
    orchestrator = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters))
    await orchestrator.execute_run(run_id)

    with db_session() as conn:
        run_row = conn.execute(
            "SELECT failed_sources FROM runs WHERE id = ?", (run_id,)
        ).fetchone()
    assert json.loads(run_row["failed_sources"]) == ["stub_broken"]


async def test_run_completes_with_zero_sources_available(data_dir):
    with db_session() as conn:
        run_id = _insert_running_run(conn)

    adapters = [
        StubAdapter("stub_a", exc=SourceFetchError("down a")),
        StubAdapter("stub_b", exc=SourceFetchError("down b")),
    ]
    orchestrator = RunOrchestrator(aggregator=SourcingAggregator(adapters=adapters))
    await orchestrator.execute_run(run_id)

    with db_session() as conn:
        run_row = conn.execute("SELECT status FROM runs WHERE id = ?", (run_id,)).fetchone()
        sweep_rows = conn.execute(
            "SELECT * FROM sweep_items WHERE run_id = ?", (run_id,)
        ).fetchall()
        idea_rows = conn.execute(
            "SELECT * FROM ideas WHERE run_id = ?", (run_id,)
        ).fetchall()

    assert run_row["status"] == "complete"
    assert len(sweep_rows) == 0
    # Zero sweep items means zero Bhavcopy close prices, so every ticker's
    # entry price is unresolvable -- every idea is correctly dropped before
    # assembly (a buy price is a hard requirement per tech-spec §4 FR6; see
    # run_orchestrator._resolve_entry_price). The run still completes
    # successfully with an empty ideas list, which is the point of this test.
    assert len(idea_rows) == 0


def test_sweep_items_never_contain_full_body(data_dir):
    """Retention-guarantee check at the DB layer: even if the Python-level
    NormalizedItem guard were ever bypassed, the sweep_items.snippet CHECK
    constraint fires for an oversized value inserted directly via SQL."""
    conn = get_connection()
    run_id = _insert_running_run(conn)
    conn.commit()

    oversized_snippet = "x" * 1000
    with pytest.raises(sqlite3.IntegrityError):
        conn.execute(
            "INSERT INTO sweep_items (run_id, source, headline, url, published_at, "
            "snippet, ticker, fetched_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                "stub_adapter",
                "headline",
                "https://example.com/x",
                dt.datetime.now(dt.timezone.utc).isoformat(),
                oversized_snippet,
                None,
                dt.datetime.now(dt.timezone.utc).isoformat(),
            ),
        )
    conn.close()
