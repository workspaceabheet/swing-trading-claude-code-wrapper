"""Hardening test: disclaimer appears on every results-rendering surface.

Per spec §4 (FR9) and §7 (HC4), every run's output shall carry a visible
disclaimer. This test verifies the exact disclaimer string appears in every
API response and is referenced in every template that renders ideas.
"""
import time

import pytest
from app.run_orchestrator import DISCLAIMER, run_orchestrator
from app.db import db_session, get_connection
from app.fakes.fake_sessions import FakeHaikuSession, FakeCompilationSession


EXPECTED_DISCLAIMER = (
    "For personal informational use only. Not investment advice. Not a "
    "registered investment adviser. No trades are placed automatically -- "
    "review and decide manually."
)


def test_disclaimer_constant_matches_expected_value():
    """Assert the exported DISCLAIMER constant has the expected exact text."""
    assert DISCLAIMER == EXPECTED_DISCLAIMER, (
        "DISCLAIMER constant does not match expected value; "
        "per spec §9 AC-FR9, exact disclaimer text must be present"
    )


def test_run_last_includes_disclaimer_in_json(client):
    """Assert GET /api/run/last includes 'disclaimer' field in JSON response."""
    # Trigger a run so there's something to fetch
    response = client.post("/api/run")
    assert response.status_code == 202, f"Failed to start run: {response.text}"
    run_id = response.json()["run_id"]

    # Poll until the run is done (for a fake session, this is instant)
    for _ in range(100):
        status = client.get("/api/run/status").json()
        if not status["in_progress"]:
            break
        time.sleep(0.01)

    # Fetch the latest run
    response = client.get("/api/run/last")
    assert response.status_code == 200
    data = response.json()
    assert "has_run" in data
    assert data["has_run"] is True
    assert "disclaimer" in data, (
        "GET /api/run/last response missing 'disclaimer' field; "
        "per spec §9 AC-FR9, every run's output must include the disclaimer"
    )
    assert data["disclaimer"] == EXPECTED_DISCLAIMER, (
        f"GET /api/run/last 'disclaimer' field does not match expected value; "
        f"got: {data['disclaimer']}"
    )


def test_run_detail_includes_disclaimer_in_json(client):
    """Assert GET /api/run/{id} includes 'disclaimer' field in JSON response."""
    # Trigger a run
    response = client.post("/api/run")
    assert response.status_code == 202
    run_id = response.json()["run_id"]

    # Poll until done
    for _ in range(100):
        status = client.get("/api/run/status").json()
        if not status["in_progress"]:
            break
        time.sleep(0.01)

    # Fetch the run detail
    response = client.get(f"/api/run/{run_id}")
    assert response.status_code == 200
    data = response.json()
    assert "disclaimer" in data, (
        "GET /api/run/{id} response missing 'disclaimer' field; "
        "per spec §9 AC-FR9, every run's output must include the disclaimer"
    )
    assert data["disclaimer"] == EXPECTED_DISCLAIMER, (
        f"GET /api/run/{{id}} 'disclaimer' field does not match expected value"
    )


def test_index_html_has_disclaimer_placeholder(client):
    """Assert index.html template has a placeholder for the disclaimer."""
    response = client.get("/")
    assert response.status_code == 200
    # The template should have a footer element with id="disclaimer"
    # that will be populated by JavaScript from the API response
    assert 'id="disclaimer"' in response.text, (
        "index.html template missing disclaimer placeholder (id='disclaimer'); "
        "per spec §9 AC-FR9, disclaimer must appear on the latest-run view"
    )
    assert 'class="disclaimer"' in response.text, (
        "index.html template missing disclaimer styling class"
    )


def test_history_html_has_disclaimer_placeholder(client):
    """Assert history.html template has a placeholder for the disclaimer."""
    response = client.get("/history")
    assert response.status_code == 200
    # The template should have a footer element with id="history-disclaimer"
    # for the history detail view
    assert 'id="history-disclaimer"' in response.text, (
        "history.html template missing disclaimer placeholder; "
        "per spec §9 AC-FR9, disclaimer must appear on the history-detail view"
    )
    assert 'class="disclaimer"' in response.text, (
        "history.html template missing disclaimer styling class"
    )


def test_quick_sweep_skipped_run_includes_disclaimer(client):
    """Assert disclaimer appears even in a quick-sweep-skipped run response."""
    # First run
    response = client.post("/api/run")
    assert response.status_code == 202
    run_id_1 = response.json()["run_id"]

    # Poll until done
    for _ in range(100):
        status = client.get("/api/run/status").json()
        if not status["in_progress"]:
            break
        time.sleep(0.01)

    # Second run (should be skipped, showing prior output)
    response = client.post("/api/run")
    assert response.status_code == 202
    run_id_2 = response.json()["run_id"]

    # Poll until done
    for _ in range(100):
        status = client.get("/api/run/status").json()
        if not status["in_progress"]:
            break
        time.sleep(0.01)

    # Fetch the skipped run
    response = client.get(f"/api/run/{run_id_2}")
    assert response.status_code == 200
    data = response.json()
    # Even if quick_sweep_skipped is True, disclaimer must still be present
    assert "disclaimer" in data, (
        "Quick-sweep-skipped run missing 'disclaimer' field; "
        "per spec §9 AC-FR9, disclaimer appears on every output including skipped runs"
    )
    assert data["disclaimer"] == EXPECTED_DISCLAIMER, (
        "Quick-sweep-skipped run 'disclaimer' field does not match expected value"
    )
