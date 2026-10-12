from fastapi.testclient import TestClient

from app.db import get_connection
from app.main import create_app

BASE_URL = "http://127.0.0.1:8000"


def test_stale_running_row_reconciled_to_error_on_startup(data_dir):
    conn = get_connection()
    conn.execute(
        "INSERT INTO runs (started_at, status) VALUES ('2026-01-01T00:00:00+00:00', 'running')"
    )
    conn.commit()
    conn.close()

    with TestClient(create_app(), base_url=BASE_URL):
        pass  # lifespan startup (and shutdown) runs around this block

    conn = get_connection()
    row = conn.execute("SELECT status, finished_at FROM runs").fetchone()
    conn.close()

    assert row["status"] == "error"
    assert row["finished_at"] is not None


def test_completed_row_not_touched_by_reconciliation(data_dir):
    conn = get_connection()
    conn.execute(
        "INSERT INTO runs (started_at, finished_at, status) VALUES "
        "('2026-01-01T00:00:00+00:00', '2026-01-01T00:00:01+00:00', 'complete')"
    )
    conn.commit()
    conn.close()

    with TestClient(create_app(), base_url=BASE_URL):
        pass

    conn = get_connection()
    row = conn.execute("SELECT status, finished_at FROM runs").fetchone()
    conn.close()

    assert row["status"] == "complete"
    assert row["finished_at"] == "2026-01-01T00:00:01+00:00"
