import time

from app.run_lock import run_lock
from app.run_orchestrator import FAKE_IDEA


def test_get_root_returns_html(client):
    res = client.get("/")
    assert res.status_code == 200
    assert "text/html" in res.headers["content-type"]


def test_run_last_with_no_runs_returns_has_run_false(client):
    res = client.get("/api/run/last")
    assert res.status_code == 200
    assert res.json() == {"has_run": False}


def test_post_run_returns_run_id_and_202(client):
    res = client.post("/api/run")
    assert res.status_code == 202
    body = res.json()
    assert isinstance(body["run_id"], int)


def test_post_run_then_poll_until_complete_returns_fake_idea(client):
    res = client.post("/api/run")
    assert res.status_code == 202

    deadline = time.monotonic() + 5
    in_progress = True
    while time.monotonic() < deadline:
        status = client.get("/api/run/status").json()
        in_progress = status["in_progress"]
        if not in_progress:
            break
        time.sleep(0.1)
    assert in_progress is False, "run did not complete within 5 seconds"

    last = client.get("/api/run/last").json()
    assert last["status"] == "complete"
    # Slice 4: now get 3 ideas from FakeHaikuSession's default shortlist
    # (RELIANCE, TATAMOTORS, INFY)
    assert len(last["ideas"]) == 3

    # Verify the fake-session-driven data is present
    tickers = {idea["ticker"] for idea in last["ideas"]}
    assert tickers == {"RELIANCE", "TATAMOTORS", "INFY"}

    # Verify sub-scores and computed tier are populated (from FakeHaikuSession via Slice 5)
    for idea in last["ideas"]:
        assert idea["sub_score_catalyst"] is not None
        assert idea["sub_score_momentum"] is not None
        assert idea["sub_score_macro"] is not None
        assert idea["score"] is not None  # Real computed score from Slice 5
        assert idea["tier"] in {"red", "yellow", "green"}  # Real computed tier from Slice 5
        assert idea["rationale"] is not None  # Concatenated reasoning
        assert idea["citation_url"] is not None  # From FakeHaikuSession citations

    # Slice 9: INFY (red-tier) is backfilled (< 10 green/yellow, so red needed to fill)
    # so it will have low_confidence=True. Green and yellow ideas have low_confidence=False.
    ideas_by_tier = {idea["tier"]: idea for idea in last["ideas"]}
    green_idea = ideas_by_tier.get("green")
    yellow_idea = ideas_by_tier.get("yellow")
    red_idea = ideas_by_tier.get("red")

    if green_idea:
        assert green_idea["low_confidence"] == False
    if yellow_idea:
        assert yellow_idea["low_confidence"] == False
    if red_idea:
        assert red_idea["low_confidence"] == True  # Backfilled

    assert last["disclaimer"]
    assert "not investment advice" in last["disclaimer"].lower()


def test_second_run_while_in_progress_returns_409(client):
    run_lock.try_acquire()

    res = client.post("/api/run")
    assert res.status_code == 409
    assert res.json() == {"error": "run already in progress"}

    last = client.get("/api/run/last").json()
    assert last["has_run"] is False


def test_run_status_reflects_lock_state(client):
    res = client.get("/api/run/status")
    assert res.json() == {"in_progress": False}

    run_lock.try_acquire()
    res = client.get("/api/run/status")
    assert res.json() == {"in_progress": True}
