import datetime as dt

import pytest
from fastapi.testclient import TestClient

from app import db, run_orchestrator as run_orchestrator_module
from app.main import create_app
from app.run_lock import run_lock
from app.sources.aggregator import SourcingAggregator
from app.sources.base import NormalizedItem

BASE_URL = "http://127.0.0.1:8000"


class _StubBhavcopyAdapter:
    """Returns canned Bhavcopy-style items (ticker + close), instantly and
    offline, for the default FakeHaikuSession shortlist (RELIANCE,
    TATAMOTORS, INFY). Used by the `client` fixture so entry-price
    resolution (run_orchestrator._resolve_entry_price) succeeds in
    API-level tests without a real network call -- without this, every
    idea would be dropped for lacking a buy price."""

    name = "stub_bhavcopy"

    async def fetch(self):
        return [
            NormalizedItem(
                source="nse_bhavcopy",
                headline=f"{ticker} EOD",
                url=f"https://example.com/nse_bhavcopy/{ticker}",
                published_at=dt.datetime.now(dt.timezone.utc),
                snippet=f"{ticker} EOD price",
                ticker=ticker,
                close=close,
            )
            for ticker, close in [
                ("RELIANCE", 2900.0), ("TATAMOTORS", 950.0), ("INFY", 1550.0),
            ]
        ]


@pytest.fixture(autouse=True)
def reset_run_lock():
    """run_lock is a module-level singleton shared across the whole process
    -- reset it before and after every test so state doesn't leak between
    tests that exercise it directly or via the API."""
    run_lock.release()
    yield
    run_lock.release()


@pytest.fixture
def data_dir(tmp_path, monkeypatch):
    """Point every on-disk path at an isolated temp dir and reset per-process
    init-once state so each test starts from a fresh schema."""
    d = tmp_path / "data"
    monkeypatch.setattr(db, "DB_PATH", d / "app.db")
    monkeypatch.setattr(db, "_initialized_paths", set())
    return d


@pytest.fixture
def client(data_dir, monkeypatch):
    """The module-level `run_orchestrator` singleton (imported by
    app/routers/run.py) defaults to a real SourcingAggregator with real,
    live-networked adapters -- fine for the app in production, but API-level
    tests must stay fast/deterministic/offline. Give the singleton a no-op
    aggregator (zero adapters -> fetch_all() returns ([], []) instantly) for
    the duration of each test; test_run_orchestrator_sourcing.py and the
    per-adapter test files construct their own RunOrchestrator/aggregator
    directly and are unaffected by this."""
    monkeypatch.setattr(
        run_orchestrator_module.run_orchestrator,
        "aggregator",
        SourcingAggregator(adapters=[_StubBhavcopyAdapter()]),
    )
    with TestClient(create_app(), base_url=BASE_URL) as c:
        yield c
