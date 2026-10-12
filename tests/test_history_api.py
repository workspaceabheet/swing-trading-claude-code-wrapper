"""Integration tests for history browsing endpoints (Slice 10)."""
import pytest
from datetime import datetime, timezone


@pytest.mark.usefixtures("client", "data_dir")
class TestRunsListAPI:
    """Tests for GET /api/runs endpoint."""

    def test_runs_list_empty_db_returns_empty_array(self, client, data_dir):
        """Fresh DB, GET /api/runs returns 200 with empty runs array."""
        response = client.get("/api/runs")
        assert response.status_code == 200
        data = response.json()
        assert data["runs"] == []
        assert data["limit"] == 50
        assert data["offset"] == 0
        assert data["total_count"] == 0

    def test_runs_list_default_limit_is_50(self, client, data_dir):
        """Default limit is 50 when no limit query param is passed."""
        # Insert a few dummy runs
        from app.db import db_session
        with db_session() as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO runs (started_at, status) VALUES (?, ?)",
                    (f"2026-10-{10+i:02d}T09:00:00+00:00", "complete"),
                )

        response = client.get("/api/runs")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 50

    def test_runs_list_reverse_chronological_order(self, client, data_dir):
        """Insert 3 runs, assert they are returned in id DESC order."""
        from app.db import db_session
        with db_session() as conn:
            conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, ?)",
                ("2026-10-10T09:00:00+00:00", "complete"),
            )
            run_a_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, ?)",
                ("2026-10-11T09:00:00+00:00", "complete"),
            )
            run_b_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]
            conn.execute(
                "INSERT INTO runs (started_at, status) VALUES (?, ?)",
                ("2026-10-12T09:00:00+00:00", "complete"),
            )
            run_c_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        response = client.get("/api/runs")
        assert response.status_code == 200
        data = response.json()
        assert len(data["runs"]) == 3
        # Most recent first (run C)
        assert data["runs"][0]["run_id"] == run_c_id
        assert data["runs"][1]["run_id"] == run_b_id
        assert data["runs"][2]["run_id"] == run_a_id

    def test_runs_list_content_matches_seeded_fields(self, client, data_dir):
        """Fields match exactly, including bool round-tripping."""
        from app.db import db_session
        from datetime import datetime, timezone

        started = datetime(2026, 10, 12, 9, 0, 0, tzinfo=timezone.utc).isoformat()
        finished = datetime(2026, 10, 12, 9, 0, 47, tzinfo=timezone.utc).isoformat()

        with db_session() as conn:
            conn.execute(
                "INSERT INTO runs "
                "(started_at, finished_at, status, quick_sweep_skipped, total_cost_usd) "
                "VALUES (?, ?, ?, ?, ?)",
                (started, finished, "complete", 1, 1.23),
            )
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        response = client.get("/api/runs")
        assert response.status_code == 200
        data = response.json()
        assert len(data["runs"]) == 1
        run = data["runs"][0]
        assert run["run_id"] == run_id
        assert run["status"] == "complete"
        assert run["started_at"] == started
        assert run["finished_at"] == finished
        assert run["quick_sweep_skipped"] is True  # JSON bool, not int
        assert run["total_cost_usd"] == 1.23

    def test_runs_list_respects_limit_and_offset(self, client, data_dir):
        """limit and offset params are respected."""
        from app.db import db_session
        with db_session() as conn:
            for i in range(5):
                conn.execute(
                    "INSERT INTO runs (started_at, status) VALUES (?, ?)",
                    (f"2026-10-{10+i:02d}T09:00:00+00:00", "complete"),
                )

        response = client.get("/api/runs?limit=2&offset=1")
        assert response.status_code == 200
        data = response.json()
        assert len(data["runs"]) == 2
        assert data["limit"] == 2
        assert data["offset"] == 1
        assert data["total_count"] == 5
        # With offset=1, we skip the most recent run and get the 2nd and 3rd most recent

    def test_runs_list_limit_clamped_to_max(self, client, data_dir):
        """limit > 200 is clamped to 200."""
        from app.db import db_session
        with db_session() as conn:
            for i in range(3):
                conn.execute(
                    "INSERT INTO runs (started_at, status) VALUES (?, ?)",
                    (f"2026-10-{10+i:02d}T09:00:00+00:00", "complete"),
                )

        response = client.get("/api/runs?limit=9999")
        assert response.status_code == 200
        data = response.json()
        assert data["limit"] == 200  # Clamped
        assert len(data["runs"]) == 3  # Still returns all 3 (limit >= actual count)


@pytest.mark.usefixtures("client", "data_dir")
class TestRunDetailAPI:
    """Tests for GET /api/run/{run_id} endpoint."""

    def test_run_detail_returns_full_record_for_existing_run(self, client, data_dir):
        """Fetch a run's full idea list; ideas ordered by rank."""
        from app.db import db_session

        with db_session() as conn:
            conn.execute(
                "INSERT INTO runs (started_at, finished_at, status) VALUES (?, ?, ?)",
                ("2026-10-12T09:00:00+00:00", "2026-10-12T09:00:01+00:00", "complete"),
            )
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Insert 2 ideas with different ranks
            conn.execute(
                "INSERT INTO ideas "
                "(run_id, ticker, entry, target, hold_days, tier, score, rationale, "
                "citation_url, low_confidence, rank, excluded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, "TCS", 3500.0, 3600.0, 7, "green", 75,
                 "Strong fundamentals", "https://example.com/tcs", 0, 1, 0),
            )
            conn.execute(
                "INSERT INTO ideas "
                "(run_id, ticker, entry, target, hold_days, tier, score, rationale, "
                "citation_url, low_confidence, rank, excluded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, "INFY", 2800.0, 2900.0, 5, "yellow", 60,
                 "Moderate outlook", "https://example.com/infy", 0, 2, 0),
            )

        response = client.get(f"/api/run/{run_id}")
        assert response.status_code == 200
        data = response.json()

        assert data["has_run"] is True
        assert data["run_id"] == run_id
        assert data["status"] == "complete"
        assert data["started_at"] == "2026-10-12T09:00:00+00:00"
        assert data["finished_at"] == "2026-10-12T09:00:01+00:00"
        assert data["quick_sweep_skipped"] is False
        assert data["disclaimer"] is not None

        assert len(data["ideas"]) == 2
        # Ordered by rank ASC
        assert data["ideas"][0]["ticker"] == "TCS"
        assert data["ideas"][0]["entry"] == 3500.0
        assert data["ideas"][0]["target"] == 3600.0
        assert data["ideas"][0]["hold_days"] == 7
        assert data["ideas"][0]["tier"] == "green"
        assert data["ideas"][0]["low_confidence"] is False

        assert data["ideas"][1]["ticker"] == "INFY"
        assert data["ideas"][1]["entry"] == 2800.0
        # rank field is not included in API response

    def test_run_detail_404_for_nonexistent_run(self, client, data_dir):
        """GET /api/run/999999 returns 404."""
        response = client.get("/api/run/999999")
        assert response.status_code == 404
        data = response.json()
        assert "error" in data or "detail" in data

    def test_run_detail_excludes_excluded_ideas(self, client, data_dir):
        """Ideas with excluded=1 are not included in the response."""
        from app.db import db_session

        with db_session() as conn:
            conn.execute(
                "INSERT INTO runs (started_at, finished_at, status) VALUES (?, ?, ?)",
                ("2026-10-12T09:00:00+00:00", "2026-10-12T09:00:01+00:00", "complete"),
            )
            run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            # Insert 1 normal idea and 1 excluded idea
            conn.execute(
                "INSERT INTO ideas "
                "(run_id, ticker, entry, target, hold_days, tier, score, rationale, "
                "citation_url, low_confidence, rank, excluded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, "TCS", 3500.0, 3600.0, 7, "green", 75,
                 "Strong", "https://example.com/tcs", 0, 1, 0),
            )
            conn.execute(
                "INSERT INTO ideas "
                "(run_id, ticker, entry, target, hold_days, tier, score, rationale, "
                "citation_url, low_confidence, rank, excluded, exclusion_reason) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_id, "PUMP", 1000.0, 1100.0, 5, "red", 20,
                 "Excluded", "https://example.com/pump", 0, 2, 1, "pump_and_dump"),
            )

        response = client.get(f"/api/run/{run_id}")
        assert response.status_code == 200
        data = response.json()

        assert len(data["ideas"]) == 1
        assert data["ideas"][0]["ticker"] == "TCS"

    def test_run_detail_with_quick_sweep_skip_resolves_ideas(self, client, data_dir):
        """When a run is quick-sweep-skipped, ideas come from source_run_id."""
        from app.db import db_session

        with db_session() as conn:
            # Create source run with 1 idea
            conn.execute(
                "INSERT INTO runs (started_at, finished_at, status) VALUES (?, ?, ?)",
                ("2026-10-10T09:00:00+00:00", "2026-10-10T09:00:01+00:00", "complete"),
            )
            source_run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                "INSERT INTO ideas "
                "(run_id, ticker, entry, target, hold_days, tier, score, rationale, "
                "citation_url, low_confidence, rank, excluded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (source_run_id, "TCS", 3500.0, 3600.0, 7, "green", 75,
                 "Strong", "https://example.com/tcs", 0, 1, 0),
            )

            # Create skipped run pointing to source_run_id
            conn.execute(
                "INSERT INTO runs "
                "(started_at, finished_at, status, quick_sweep_skipped, source_run_id) "
                "VALUES (?, ?, ?, ?, ?)",
                ("2026-10-12T09:00:00+00:00", "2026-10-12T09:00:01+00:00",
                 "complete", 1, source_run_id),
            )
            skipped_run_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

        response = client.get(f"/api/run/{skipped_run_id}")
        assert response.status_code == 200
        data = response.json()

        assert data["run_id"] == skipped_run_id
        assert data["quick_sweep_skipped"] is True
        # Ideas should come from source_run, not skipped run's own ideas (none)
        assert len(data["ideas"]) == 1
        assert data["ideas"][0]["ticker"] == "TCS"


@pytest.mark.usefixtures("client", "data_dir")
class TestHistoryPageRoute:
    """Tests for GET /history route."""

    def test_history_page_route_returns_html(self, client, data_dir):
        """GET /history returns 200 and text/html content type."""
        response = client.get("/history")
        assert response.status_code == 200
        assert "text/html" in response.headers.get("content-type", "")


@pytest.mark.usefixtures("client", "data_dir")
class TestHistoryImmutability:
    """Verify that later runs' data changes don't affect earlier runs' stored records."""

    def test_editing_later_run_does_not_affect_earlier_runs_stored_record(self, client, data_dir):
        """Older run data is immutable; updating newer run data doesn't touch old run."""
        from app.db import db_session

        with db_session() as conn:
            # Create run 1 with idea A
            conn.execute(
                "INSERT INTO runs (started_at, finished_at, status) VALUES (?, ?, ?)",
                ("2026-10-10T09:00:00+00:00", "2026-10-10T09:00:01+00:00", "complete"),
            )
            run_1_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                "INSERT INTO ideas "
                "(run_id, ticker, entry, target, hold_days, tier, score, rationale, "
                "citation_url, low_confidence, rank, excluded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_1_id, "FOO", 1000.0, 1100.0, 7, "green", 75,
                 "original", "https://example.com/foo", 0, 1, 0),
            )

            # Create run 2 with idea B
            conn.execute(
                "INSERT INTO runs (started_at, finished_at, status) VALUES (?, ?, ?)",
                ("2026-10-12T09:00:00+00:00", "2026-10-12T09:00:01+00:00", "complete"),
            )
            run_2_id = conn.execute("SELECT last_insert_rowid()").fetchone()[0]

            conn.execute(
                "INSERT INTO ideas "
                "(run_id, ticker, entry, target, hold_days, tier, score, rationale, "
                "citation_url, low_confidence, rank, excluded) "
                "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (run_2_id, "BAR", 2000.0, 2200.0, 5, "yellow", 60,
                 "idea2", "https://example.com/bar", 0, 1, 0),
            )

        # Fetch run 1's data
        response1 = client.get(f"/api/run/{run_1_id}")
        assert response1.status_code == 200
        data1_before = response1.json()

        # Mutate run 2's idea directly (not normal operation, just for testing immutability)
        from app.db import db_session
        with db_session() as conn:
            conn.execute(
                "UPDATE ideas SET rationale = ?, tier = ? WHERE run_id = ?",
                ("mutated", "red", run_2_id),
            )

        # Fetch run 1's data again
        response1_again = client.get(f"/api/run/{run_1_id}")
        assert response1_again.status_code == 200
        data1_after = response1_again.json()

        # Run 1's data should be byte-for-byte identical
        assert data1_before == data1_after
        assert data1_after["ideas"][0]["rationale"] == "original"
        assert data1_after["ideas"][0]["tier"] == "green"
