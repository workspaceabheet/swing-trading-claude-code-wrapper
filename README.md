# Swing Trade Ideas

A local, single-user swing-trading research assistant for NSE/BSE equities. It runs a
three-stage AI pipeline — a broad news sweep, per-stock deep-dive analysis, and a final
compilation pass — over free Indian market data sources, and surfaces at most 10 ranked,
cited trade ideas per run with a buy price, target price, hold-duration estimate, and a
deterministic red/yellow/green confidence tier.

**This is a personal research aid, not investment advice.** It never places, modifies, or
cancels any brokerage order — it only displays suggestions for you to review manually.

## How it works

1. **Sourcing** — fetches current data from four free sources: Moneycontrol RSS, NSE
   Bhavcopy (official EOD price/volume CSV), Screener.in (fundamentals), and Trading
   Economics (macro calendar). Only headline/source/date/URL/snippet is ever retained —
   full article bodies are never stored.
2. **Quick-sweep check** — before doing anything expensive, the run's sourced data is
   hashed and compared against the previous run. If nothing material changed, the run
   completes immediately and reuses the prior results instead of re-running the LLM
   stages.
3. **Sweep (Haiku)** — a Claude Haiku call with web search/fetch tools enabled reviews
   the sourced data and shortlists candidate tickers worth a deeper look.
4. **Deep-dive (Haiku, parallelized)** — one Haiku call per shortlisted ticker, scoring
   catalyst strength, sector momentum, and macro risk as independent sub-scores with
   written reasoning, plus negative-filter signals (pump-and-dump indicators, stale-news
   cross-checks). Calls run concurrently (bounded by a semaphore) for speed.
5. **Deterministic scoring** — application code (never an LLM) computes the final 0-100
   score and red/yellow/green tier from Haiku's sub-scores, using a fixed weighted
   formula. This is the single source of truth for the tier; no LLM call can change it.
6. **Negative filtering** — candidates matching pump-and-dump or stale-news patterns are
   excluded before ranking, with the reason recorded for audit.
7. **Compilation (Sonnet)** — one Sonnet call per run, over all surviving candidates
   together, writes polished per-idea rationale and cross-candidate ranking commentary.
   Sonnet never computes or overrides a score or tier — it only writes narrative text
   around the already-final numbers.
8. **Assembly** — the final list is capped at 10 ideas, ordered green → yellow → red.
   Yellow/green ideas fill the list first; red-tier ideas only backfill the list when
   fewer than 10 yellow/green ideas exist, and are always visibly labeled low-confidence.
   Any idea without a citation is dropped, no matter its score.

## Running it

Requires Python 3.13+ and an active `claude login` session (the Claude Agent SDK rides
on your existing Claude Code authentication — no API key needed).

```bash
python3 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
```

Start the server:

```bash
uvicorn app.main:app --host 127.0.0.1 --port 8000
```

Open `http://127.0.0.1:8000/` and click **Run now**. By default the engine uses fake
(canned) data for safety — set these environment variables to use the real Claude Agent
SDK for genuine analysis:

```bash
SWINGTRADE_HAIKU_SESSION=real SWINGTRADE_COMPILATION_SESSION=real uvicorn app.main:app --host 127.0.0.1 --port 8000
```

A real run typically costs well under $1 and takes 1-3 minutes (dominated by the
parallelized Haiku deep-dive calls). Per-stage cost is logged and shown in the UI —
nothing blocks or warns on cost, it's visibility only.

The app binds to `127.0.0.1` only and has no login/auth layer — it's designed to be a
single-user local tool, not to be exposed to a network.

## Tests

```bash
pytest tests/ -v
```

Runs in about a second. A few tests are marked `live` and skipped by default since they
make real paid API calls — run them explicitly with:

```bash
SWINGTRADE_RUN_LIVE_HAIKU_TEST=1 pytest tests/test_haiku_session_live.py -v
COMPILATION_LIVE=1 pytest tests/test_compilation_live_manual.py -v -s
```

## Project structure

```
app/
  main.py              FastAPI app, lifespan, routing
  run_orchestrator.py  Pipeline orchestration (sourcing -> scoring -> assembly)
  sources/             One adapter per data source
  agent/               Claude Agent SDK sessions, prompts, parsing
  scoring.py           Pure deterministic scoring formula
  negative_filters.py  Pump-and-dump / stale-news exclusion rules
  assembly.py          Final output cap/ordering/backfill logic
  db.py                SQLite schema and queries
  templates/, static/  Jinja2 templates and frontend assets
tests/                 pytest suite (252+ tests, sub-second runtime)
.sessions/             Planning artifacts: research, spec, vertical-slice plan,
                       detailed per-slice plans, and the independent validation report
```

See `.sessions/swingtrade-20261011-130148/` for the full research → spec → plan →
validation trail this project was built from.

## Scope

In scope: free data sources only, India (NSE/BSE) equities, personal local use.
Out of scope (v1): any brokerage automation (including Zerodha Kite), paid APIs, trade
execution of any kind, multi-user access, and live/intraday pricing.
