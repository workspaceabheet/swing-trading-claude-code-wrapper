import json
import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from pathlib import Path

from app.config import DB_PATH
from app.sources.base import NormalizedItem

SCHEMA_SQL = """
CREATE TABLE IF NOT EXISTS runs (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    started_at      TEXT NOT NULL,              -- ISO 8601 UTC
    finished_at     TEXT,                        -- NULL while running
    status          TEXT NOT NULL,               -- 'running' | 'complete' | 'error'
    quick_sweep_skipped   INTEGER NOT NULL DEFAULT 0,  -- placeholder bool (0/1); real logic lands in Slice 3 (FR2)
    cost_sweep_usd        REAL NOT NULL DEFAULT 0.0,   -- placeholder; real value lands in Slice 11 (FR13)
    cost_deep_dive_usd    REAL NOT NULL DEFAULT 0.0,   -- placeholder; Slice 11
    cost_compilation_usd  REAL NOT NULL DEFAULT 0.0,   -- placeholder; Slice 11
    total_cost_usd        REAL NOT NULL DEFAULT 0.0    -- placeholder; Slice 11
);

CREATE TABLE IF NOT EXISTS ideas (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    ticker          TEXT NOT NULL,
    entry           REAL NOT NULL,               -- buy/entry reference price
    target          REAL NOT NULL,               -- target price
    hold_days       INTEGER NOT NULL,            -- hold-duration estimate in days
    tier            TEXT NOT NULL,               -- 'green' | 'yellow' | 'red'
    score           INTEGER,                     -- placeholder; real 0-100 deterministic score lands in Slice 5 (FR6). NULL in Slice 0.
    sub_score_catalyst   INTEGER,                -- placeholder; Slice 5/4
    sub_score_momentum   INTEGER,                -- placeholder; Slice 5/4
    sub_score_macro      INTEGER,                -- placeholder; Slice 5/4
    rationale       TEXT NOT NULL,               -- written rationale text (Sonnet-polished in later slices; hardcoded in Slice 0)
    citation_url    TEXT NOT NULL,               -- at least one citation URL; hardcoded in Slice 0
    citation_source TEXT,                        -- placeholder for citation source name (Slice 1+); NULL in Slice 0
    citation_headline TEXT,                      -- placeholder for citation headline (Slice 1+); NULL in Slice 0
    low_confidence  INTEGER NOT NULL DEFAULT 0,  -- bool (0/1): red-tier backfill label, per FR7. Always 0 in Slice 0 (fake idea is green).
    rank            INTEGER NOT NULL DEFAULT 1   -- ordering position within the run's idea list (1 = best); trivial with one idea in Slice 0, real ordering logic lands in Slice 9 (FR7)
);

-- Slice 1: retention-safe raw sourcing items (news/filings headlines etc.)
-- picked up during a run's sweep. Deliberately NO body/content/full_text/html
-- column exists anywhere in this table -- the schema itself cannot hold a
-- full article even if application code tried to pass one in. `snippet`'s
-- CHECK is a DB-level defense-in-depth backstop independent of the Python-
-- level NormalizedItem.__post_init__ guard (app/sources/base.py); 300 =
-- SNIPPET_MAX_CHARS (280) + headroom for the "..." suffix and encoding
-- variance -- keep the two constants in sync.
CREATE TABLE IF NOT EXISTS sweep_items (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id          INTEGER NOT NULL REFERENCES runs(id),
    source          TEXT NOT NULL,              -- adapter name, e.g. 'moneycontrol_rss'
    headline        TEXT NOT NULL,
    url             TEXT NOT NULL,
    published_at    TEXT NOT NULL,               -- ISO 8601 UTC
    snippet         TEXT NOT NULL CHECK (length(snippet) <= 300),  -- hard DB-level cap; see note above
    ticker          TEXT,                        -- NULL when adapter can't associate a symbol
    fetched_at      TEXT NOT NULL,               -- ISO 8601 UTC; when THIS run's fetch happened (distinct from published_at)
    -- New in Slice 2 (all nullable; only populated by the adapter that owns
    -- the field): Bhavcopy OHLC/volume, Screener.in fundamentals, Trading
    -- Economics indicator fields. Every one is a short bounded scalar or a
    -- length-capped string -- none can hold article-body-length text; the
    -- table still has no body/content/full_text/html column of any kind.
    close           REAL,
    prev_close      REAL,
    volume          INTEGER,
    pe_ratio        REAL,
    market_cap_cr   REAL,
    indicator_name  TEXT,
    indicator_value TEXT CHECK (indicator_value IS NULL OR length(indicator_value) <= 64)
);

CREATE INDEX IF NOT EXISTS idx_sweep_items_run_id ON sweep_items (run_id);

CREATE TABLE IF NOT EXISTS candidates (
    id                          INTEGER PRIMARY KEY AUTOINCREMENT,
    run_id                      INTEGER NOT NULL REFERENCES runs(id),
    ticker                      TEXT NOT NULL,
    sweep_reason                TEXT NOT NULL,     -- ShortlistCandidate.reason
    catalyst_subscore           INTEGER NOT NULL,  -- 0-40
    catalyst_reasoning          TEXT NOT NULL,
    sector_momentum_subscore    INTEGER NOT NULL,  -- 0-35
    sector_momentum_reasoning   TEXT NOT NULL,
    macro_subscore              INTEGER NOT NULL,  -- 0-25
    macro_reasoning             TEXT NOT NULL,
    citations_json              TEXT NOT NULL,     -- JSON list of
                                                    -- {source,headline,url,published_at}
    daily_volume                INTEGER,
    has_institutional_ownership INTEGER,           -- bool 0/1, nullable
    promotional_chatter_flag    INTEGER NOT NULL DEFAULT 0,  -- bool 0/1
    catalyst_announcement_date  TEXT,              -- ISO date, nullable
    created_at                  TEXT NOT NULL       -- ISO-8601 UTC
);
"""

# Columns added to existing tables after their first release -- CREATE TABLE
# IF NOT EXISTS never alters an existing table, so init_db adds any that are
# missing (sibling-project pattern, reached for here because Slice 0/1 runs
# data may already exist locally by the time Slice 2 lands).
_ADDED_COLUMNS: dict[str, list[tuple[str, str]]] = {
    "runs": [
        ("failed_sources", "TEXT"),  # JSON-encoded list[str] of adapter names that failed this run; NULL/'[]' if none
        ("quick_sweep_hash", "TEXT"),  # SHA-256 hash of normalized sweep items (Slice 3); NULL if run errored before sourcing
        ("source_run_id", "INTEGER REFERENCES runs(id)"),  # When quick_sweep_skipped=1, the run whose ideas are displayed (Slice 3)
    ],
    "ideas": [
        ("excluded", "INTEGER NOT NULL DEFAULT 0"),  # bool 0/1: whether this candidate was excluded by Slice 6 negative filters
        ("exclusion_reason", "TEXT"),  # nullable string explaining why excluded=1 (audit trail); NULL iff excluded=0
        ("polished_rationale", "TEXT"),  # Sonnet-polished rationale text (Slice 8); NULL until compilation runs
        ("ranking_commentary", "TEXT"),  # Per-idea ranking commentary fragment (Slice 8); NULL until compilation runs
        ("backfill_reason", "TEXT"),  # Slice 9: "red_tier_backfill" when low_confidence=1, else NULL
    ],
    "candidates": [
        ("avg_20day_volume", "INTEGER"),  # 20-day average volume (Slice 6 relative volume check)
        ("institutional_ownership_pct", "REAL"),  # FII% + DII% combined percentage (Slice 6)
        ("catalyst_mentioned_date", "TEXT"),  # ISO date of the catalyst news (Slice 6)
        ("nse_announcement_date", "TEXT"),  # ISO date of NSE announcement, for corroboration (Slice 6)
    ],
}

# Paths whose schema has already been initialised in this process.
_initialized_paths: set[str] = set()


def init_db(conn: sqlite3.Connection) -> None:
    """Executes SCHEMA_SQL, then adds any _ADDED_COLUMNS missing from an
    older database; idempotent."""
    conn.executescript(SCHEMA_SQL)
    for table, columns in _ADDED_COLUMNS.items():
        existing = {row[1] for row in conn.execute(f"PRAGMA table_info({table})")}
        for name, decl in columns:
            if name not in existing:
                conn.execute(f"ALTER TABLE {table} ADD COLUMN {name} {decl}")
    conn.commit()


def get_connection() -> sqlite3.Connection:
    """Opens a connection to DB_PATH (check_same_thread=False, Row factory).
    Runs init_db once per process per database path."""
    db_path = Path(DB_PATH)
    db_path.parent.mkdir(parents=True, exist_ok=True)
    # check_same_thread=False is required: FastAPI/Uvicorn may service requests
    # on different threads.
    conn = sqlite3.connect(db_path, check_same_thread=False)
    conn.row_factory = sqlite3.Row
    key = str(db_path.resolve())
    if key not in _initialized_paths:
        init_db(conn)
        _initialized_paths.add(key)
    return conn


@contextmanager
def db_session():
    """Yields a connection; commits on clean exit, rolls back on exception."""
    conn = get_connection()
    try:
        yield conn
        conn.commit()
    except Exception:
        conn.rollback()
        raise
    finally:
        conn.close()


def insert_sweep_items(
    conn: sqlite3.Connection, run_id: int, items: list[NormalizedItem]
) -> None:
    """Bulk-inserts this run's fetched sourcing items. `fetched_at` is set
    once for the whole batch (when THIS run's fetch happened, distinct from
    each item's own `published_at`). No-op for an empty list."""
    if not items:
        return
    fetched_at = datetime.now(timezone.utc).isoformat()
    conn.executemany(
        "INSERT INTO sweep_items (run_id, source, headline, url, published_at, "
        "snippet, ticker, fetched_at, close, prev_close, volume, pe_ratio, "
        "market_cap_cr, indicator_name, indicator_value) VALUES "
        "(?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        [
            (
                run_id,
                item.source,
                item.headline,
                item.url,
                item.published_at.isoformat(),
                item.snippet,
                item.ticker,
                fetched_at,
                item.close,
                item.prev_close,
                item.volume,
                item.pe_ratio,
                item.market_cap_cr,
                item.indicator_name,
                item.indicator_value,
            )
            for item in items
        ],
    )


def get_sweep_items(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    return conn.execute(
        "SELECT * FROM sweep_items WHERE run_id = ? ORDER BY published_at DESC",
        (run_id,),
    ).fetchall()


def set_failed_sources(conn: sqlite3.Connection, run_id: int, failed: list[str]) -> None:
    """Writes the JSON-encoded list of adapter names that failed this run
    onto the runs row (NULL/absent sourcing step leaves this at the column
    default of NULL, which the API layer treats the same as [])."""
    conn.execute(
        "UPDATE runs SET failed_sources = ? WHERE id = ?",
        (json.dumps(sorted(failed)), run_id),
    )


def get_prior_comparable_run(
    conn: sqlite3.Connection, current_run_id: int
) -> sqlite3.Row | None:
    """Fetch the immediately prior non-error completed run for diff comparison.

    Returns a Row with columns: id, quick_sweep_hash, status, finished_at, ideas_owner_run_id.
    ideas_owner_run_id is COALESCE(source_run_id, id) — the run whose ideas
    should be displayed (chains back through consecutive skips to the original
    run that actually produced the ideas).

    Returns None if no such prior run exists.
    """
    return conn.execute(
        """
        SELECT id, quick_sweep_hash, status, finished_at,
               COALESCE(source_run_id, id) AS ideas_owner_run_id
        FROM runs
        WHERE id < ? AND status != 'error'
        ORDER BY id DESC
        LIMIT 1
        """,
        (current_run_id,),
    ).fetchone()


def insert_candidate(
    conn: sqlite3.Connection, run_id: int, result
) -> int:
    """Persists a DeepDiveResult to the candidates table.

    Args:
        conn: SQLite connection.
        run_id: The run_id to associate with this candidate.
        result: A DeepDiveResult from the deep-dive stage.

    Returns:
        The inserted candidate row's id.
    """
    created_at = datetime.now(timezone.utc).isoformat()
    citations_json = json.dumps([
        {
            "source": c.source,
            "headline": c.headline,
            "url": c.url,
            "published_at": c.published_at,
        }
        for c in result.citations
    ])

    cursor = conn.execute(
        "INSERT INTO candidates ("
        "run_id, ticker, sweep_reason, catalyst_subscore, catalyst_reasoning, "
        "sector_momentum_subscore, sector_momentum_reasoning, macro_subscore, "
        "macro_reasoning, citations_json, daily_volume, avg_20day_volume, "
        "institutional_ownership_pct, promotional_chatter_flag, catalyst_mentioned_date, "
        "nse_announcement_date, created_at) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            result.ticker,
            "",  # sweep_reason will be added separately via insert_idea_placeholder
            result.catalyst_subscore,
            result.catalyst_reasoning,
            result.sector_momentum_subscore,
            result.sector_momentum_reasoning,
            result.macro_subscore,
            result.macro_reasoning,
            citations_json,
            result.daily_volume,
            result.avg_20day_volume,
            result.institutional_ownership_pct,
            1 if result.promotional_chatter_flag else 0,
            result.catalyst_mentioned_date,
            result.nse_announcement_date,
            created_at,
        ),
    )
    return cursor.lastrowid


def insert_idea_placeholder(
    conn: sqlite3.Connection, run_id: int, result, candidate_id: int, sweep_reason: str = "", rank: int = 1
) -> None:
    """Mirrors a DeepDiveResult into the ideas table with real score/tier from Slice 5.

    Slice 5 (scoring) sets result.score and result.tier via compute_score().
    Slice 6 (negative filtering) sets result.excluded and result.exclusion_reason.
    This function persists those real computed values, never a placeholder.

    Args:
        conn: SQLite connection.
        run_id: The run_id to associate with this idea.
        result: A DeepDiveResult from the deep-dive stage, with score/tier
                already set by Slice 5's compute_score function, and excluded/
                exclusion_reason set by Slice 6's evaluate_negative_filters.
        candidate_id: The candidate row's id (for traceability).
        sweep_reason: The ShortlistCandidate.reason for this ticker.
        rank: The ordering position within the run's idea list (1 = best).
    """
    # Concatenate the three reasoning strings
    rationale = f"{result.catalyst_reasoning}\n{result.sector_momentum_reasoning}\n{result.macro_reasoning}"

    # Use first citation for citation fields
    first_citation = result.citations[0] if result.citations else None
    citation_url = first_citation.url if first_citation else ""
    citation_source = first_citation.source if first_citation else None
    citation_headline = first_citation.headline if first_citation else None

    conn.execute(
        "INSERT INTO ideas ("
        "run_id, ticker, entry, target, hold_days, tier, score, "
        "sub_score_catalyst, sub_score_momentum, sub_score_macro, rationale, "
        "citation_url, citation_source, citation_headline, low_confidence, rank, "
        "excluded, exclusion_reason, backfill_reason) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            run_id,
            result.ticker,
            0.0,  # entry placeholder
            0.0,  # target placeholder
            0,    # hold_days placeholder
            result.tier,  # real computed tier from Slice 5 (never "unscored")
            result.score,  # real computed score from Slice 5
            result.catalyst_subscore,
            result.sector_momentum_subscore,
            result.macro_subscore,
            rationale,
            citation_url,
            citation_source,
            citation_headline,
            0,    # low_confidence
            rank,
            1 if result.excluded else 0,  # Slice 6 exclusion status
            result.exclusion_reason,  # Slice 6 exclusion reason (None iff excluded=False)
            None,  # backfill_reason (will be set by Slice 9 assembly)
        ),
    )


def insert_assembled_ideas(
    conn: sqlite3.Connection, run_id: int, ideas: list
) -> None:
    """Persist a list of Idea objects from Slice 9 assembly to the ideas table.

    Args:
        conn: SQLite connection.
        run_id: The run_id to associate with these ideas.
        ideas: List of Idea objects from assemble().
    """
    for idea in ideas:
        conn.execute(
            "INSERT INTO ideas ("
            "run_id, ticker, entry, target, hold_days, tier, score, "
            "sub_score_catalyst, sub_score_momentum, sub_score_macro, "
            "rationale, citation_url, citation_source, citation_headline, "
            "low_confidence, rank, polished_rationale, ranking_commentary, backfill_reason) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                run_id,
                idea.ticker,
                idea.entry,
                idea.target,
                idea.hold_days,
                idea.tier,
                idea.score,
                idea.sub_score_catalyst,
                idea.sub_score_momentum,
                idea.sub_score_macro,
                idea.polished_rationale,  # Use polished_rationale for rationale field
                idea.citation_url,
                idea.citation_source,
                idea.citation_headline,
                1 if idea.low_confidence else 0,
                idea.rank,
                idea.polished_rationale,  # Also store in polished_rationale column
                idea.ranking_commentary,  # Per-idea commentary from Slice 8
                idea.backfill_reason,
            ),
        )


def get_candidates_for_run(conn: sqlite3.Connection, run_id: int) -> list[sqlite3.Row]:
    """Fetches all candidates for a given run."""
    return conn.execute(
        "SELECT * FROM candidates WHERE run_id = ? ORDER BY id",
        (run_id,),
    ).fetchall()
