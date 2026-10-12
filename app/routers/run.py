import asyncio
import json
from datetime import datetime, timezone

from fastapi import APIRouter, HTTPException
from fastapi.responses import JSONResponse

from app.db import db_session, get_sweep_items
from app.history_store import list_runs, get_run, get_ideas_for_run
from app.run_lock import run_lock
from app.run_orchestrator import DISCLAIMER, run_orchestrator

router = APIRouter()

# Keeps references to in-flight background run tasks so they aren't garbage
# collected mid-run (asyncio only holds a weak reference once a task's
# creator drops its own reference); discarded via the done-callback once
# finished.
_background_tasks: set[asyncio.Task] = set()


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


@router.post("/run", status_code=202)
async def start_run():
    """202 + run_id if the lock was free (schedules the run as a detached
    asyncio task so the response returns immediately); 409 JSON if a run is
    already in progress -- no DB row is inserted for a rejected attempt."""
    if not run_lock.try_acquire():
        return JSONResponse(
            status_code=409, content={"error": "run already in progress"}
        )
    with db_session() as conn:
        cur = conn.execute(
            "INSERT INTO runs (started_at, status) VALUES (?, 'running')",
            (_now_iso(),),
        )
        run_id = cur.lastrowid
    task = asyncio.create_task(run_orchestrator.execute_run(run_id))
    _background_tasks.add(task)
    task.add_done_callback(_background_tasks.discard)
    return {"run_id": run_id}


@router.get("/run/status")
async def run_status():
    return {"in_progress": run_lock.in_progress}


@router.get("/run/last")
async def run_last():
    """Most-recently-started run (any status), by id DESC -- lets the
    frontend poll this one endpoint during an in-progress run too.
    {"has_run": false} if `runs` is empty."""
    with db_session() as conn:
        run_row = conn.execute(
            "SELECT id, started_at, finished_at, status, quick_sweep_skipped, "
            "source_run_id, cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd, "
            "total_cost_usd, failed_sources FROM runs ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if run_row is None:
            return {"has_run": False}

        ideas = []
        quick_sweep_message = None

        if run_row["status"] != "running":
            # If quick_sweep_skipped, fetch ideas from source_run_id instead
            ideas_run_id = run_row["source_run_id"] if run_row["quick_sweep_skipped"] else run_row["id"]

            idea_rows = conn.execute(
                "SELECT ticker, entry, target, hold_days, tier, score, "
                "sub_score_catalyst, sub_score_momentum, sub_score_macro, "
                "rationale, citation_url, low_confidence FROM ideas "
                "WHERE run_id = ? AND excluded = 0 ORDER BY rank ASC",
                (ideas_run_id,),
            ).fetchall()
            ideas = [
                {
                    "ticker": row["ticker"],
                    "entry": row["entry"],
                    "target": row["target"],
                    "hold_days": row["hold_days"],
                    "tier": row["tier"],
                    "score": row["score"],
                    "sub_score_catalyst": row["sub_score_catalyst"],
                    "sub_score_momentum": row["sub_score_momentum"],
                    "sub_score_macro": row["sub_score_macro"],
                    "rationale": row["rationale"],
                    "citation_url": row["citation_url"],
                    "low_confidence": bool(row["low_confidence"]),
                }
                for row in idea_rows
            ]

            # If skipped, build the skip message
            if run_row["quick_sweep_skipped"] and run_row["source_run_id"]:
                source_run = conn.execute(
                    "SELECT id, finished_at FROM runs WHERE id = ?",
                    (run_row["source_run_id"],),
                ).fetchone()
                if source_run:
                    quick_sweep_message = (
                        f"No material change detected since the last run — showing results from "
                        f"run #{source_run['id']} (completed {source_run['finished_at']})."
                    )

        sweep_rows = get_sweep_items(conn, run_row["id"])
        sources = [
            {
                "source": row["source"],
                "headline": row["headline"],
                "url": row["url"],
                "published_at": row["published_at"],
                "snippet": row["snippet"],
                "ticker": row["ticker"],
                "close": row["close"],
                "prev_close": row["prev_close"],
                "volume": row["volume"],
                "pe_ratio": row["pe_ratio"],
                "market_cap_cr": row["market_cap_cr"],
                "indicator_name": row["indicator_name"],
                "indicator_value": row["indicator_value"],
            }
            for row in sweep_rows
        ]

    failed_sources = json.loads(run_row["failed_sources"] or "[]")

    return {
        "has_run": True,
        "run_id": run_row["id"],
        "status": run_row["status"],
        "started_at": run_row["started_at"],
        "finished_at": run_row["finished_at"],
        "quick_sweep_skipped": bool(run_row["quick_sweep_skipped"]),
        "source_run_id": run_row["source_run_id"],
        "quick_sweep_message": quick_sweep_message,
        "cost_sweep_usd": run_row["cost_sweep_usd"],
        "cost_deep_dive_usd": run_row["cost_deep_dive_usd"],
        "cost_compilation_usd": run_row["cost_compilation_usd"],
        "total_cost_usd": run_row["total_cost_usd"],
        "ideas": ideas,
        "sources": sources,
        "failed_sources": failed_sources,
        "disclaimer": DISCLAIMER,
    }


@router.get("/runs")
async def runs_list(limit: int = 50, offset: int = 0):
    """List past run summaries in reverse-chronological order (by id DESC).

    Query params:
    - limit: max 200 (default 50)
    - offset: pagination offset (default 0)

    Response: {"runs": [...], "limit": int, "offset": int, "total_count": int}
    """
    # Clamp limit to valid range [1, 200]
    limit = max(1, min(limit, 200))
    offset = max(0, offset)

    with db_session() as conn:
        runs, total_count = list_runs(conn, limit, offset)

    return {
        "runs": runs,
        "limit": limit,
        "offset": offset,
        "total_count": total_count,
    }


@router.get("/run/{run_id}")
async def run_detail(run_id: int):
    """Fetch one specific past run's full idea list + metadata.

    Returns the same response shape as GET /api/run/last, with ideas ordered
    by rank ASC. Handles quick_sweep_skipped resolution (ideas come from
    source_run_id if the run was skipped).

    Returns 404 if run_id does not exist.
    """
    with db_session() as conn:
        run_row = conn.execute(
            "SELECT id, started_at, finished_at, status, quick_sweep_skipped, "
            "source_run_id, total_cost_usd FROM runs WHERE id = ?",
            (run_id,),
        ).fetchone()

        if run_row is None:
            raise HTTPException(status_code=404, detail="run not found")

        ideas = []

        if run_row["status"] != "running":
            # If quick_sweep_skipped, fetch ideas from source_run_id instead
            ideas_run_id = run_row["source_run_id"] if run_row["quick_sweep_skipped"] else run_row["id"]
            ideas = get_ideas_for_run(conn, ideas_run_id)

    return {
        "has_run": True,
        "run_id": run_row["id"],
        "status": run_row["status"],
        "started_at": run_row["started_at"],
        "finished_at": run_row["finished_at"],
        "quick_sweep_skipped": bool(run_row["quick_sweep_skipped"]),
        "total_cost_usd": run_row["total_cost_usd"],
        "ideas": ideas,
        "disclaimer": DISCLAIMER,
    }
