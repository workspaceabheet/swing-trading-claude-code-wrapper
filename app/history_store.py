"""Read-only query functions for browsing run history.

Mirrors the sibling project's results_store.py pattern: DB-query logic
separated from the router layer, allowing handlers to own only HTTP concerns.
"""


def list_runs(conn, limit: int, offset: int) -> tuple[list[dict], int]:
    """Returns (rows, total_count). rows ordered by id DESC."""
    total_count = conn.execute("SELECT COUNT(*) FROM runs").fetchone()[0]
    rows = conn.execute(
        "SELECT id, status, started_at, finished_at, quick_sweep_skipped, "
        "total_cost_usd FROM runs ORDER BY id DESC LIMIT ? OFFSET ?",
        (limit, offset),
    ).fetchall()
    return [
        {
            "run_id": r["id"],
            "status": r["status"],
            "started_at": r["started_at"],
            "finished_at": r["finished_at"],
            "quick_sweep_skipped": bool(r["quick_sweep_skipped"]),
            "total_cost_usd": r["total_cost_usd"],
        }
        for r in rows
    ], total_count


def get_run(conn, run_id: int) -> dict | None:
    """Returns the run's own fields (no ideas) or None if run_id doesn't exist."""
    row = conn.execute(
        "SELECT id, status, started_at, finished_at, quick_sweep_skipped, "
        "cost_sweep_usd, cost_deep_dive_usd, cost_compilation_usd, "
        "total_cost_usd FROM runs WHERE id = ?",
        (run_id,),
    ).fetchone()
    if row is None:
        return None
    return {
        "run_id": row["id"],
        "status": row["status"],
        "started_at": row["started_at"],
        "finished_at": row["finished_at"],
        "quick_sweep_skipped": bool(row["quick_sweep_skipped"]),
        "cost_sweep_usd": row["cost_sweep_usd"],
        "cost_deep_dive_usd": row["cost_deep_dive_usd"],
        "cost_compilation_usd": row["cost_compilation_usd"],
        "total_cost_usd": row["total_cost_usd"],
    }


def get_ideas_for_run(conn, run_id: int) -> list[dict]:
    """Ordered by rank ASC. Returns [] if the run has no ideas (e.g. still
    running, errored before assembly, or quick-sweep-skipped with no new
    ideas to show)."""
    rows = conn.execute(
        "SELECT ticker, entry, target, hold_days, tier, score, rationale, "
        "citation_url, low_confidence FROM ideas WHERE run_id = ? AND excluded = 0 ORDER BY rank ASC",
        (run_id,),
    ).fetchall()
    return [
        {
            "ticker": r["ticker"],
            "entry": r["entry"],
            "target": r["target"],
            "hold_days": r["hold_days"],
            "tier": r["tier"],
            "score": r["score"],
            "rationale": r["rationale"],
            "citation_url": r["citation_url"],
            "low_confidence": bool(r["low_confidence"]),
        }
        for r in rows
    ]
