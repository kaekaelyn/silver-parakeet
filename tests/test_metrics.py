"""Metrics: weekly counts and response rates by source and score band."""

import sqlite3

from fastapi.testclient import TestClient

from wingman import metrics


def _application(
    conn: sqlite3.Connection,
    state: str,
    applied_at: str = "datetime('now')",
    source_name: str | None = "Remotive",
    score: int | None = 80,
) -> int:
    source_id = None
    if source_name:
        row = conn.execute("SELECT id FROM sources WHERE name = ?", (source_name,)).fetchone()
        source_id = (
            row["id"]
            if row
            else conn.execute(
                "INSERT INTO sources (kind, name) VALUES ('remotive', ?)", (source_name,)
            ).lastrowid
        )
    job_id = conn.execute(
        "INSERT INTO jobs (source_id, title, url, dedupe_hash) VALUES (?, 'J', ?, ?)",
        (source_id, f"https://x.example/{state}-{applied_at}", f"h{state}{applied_at}"),
    ).lastrowid
    if score is not None:
        conn.execute(
            "INSERT INTO scores (job_id, scorer, score) VALUES (?, 'heuristic', ?)",
            (job_id, score),
        )
    conn.execute(
        f"""INSERT INTO applications (job_id, state, applied_at)
            VALUES (?, ?, {applied_at})""",
        (job_id, state),
    )
    conn.commit()
    return job_id


def test_totals_and_response_definition(conn: sqlite3.Connection) -> None:
    _application(conn, "applied")
    _application(conn, "interviewing")
    _application(conn, "offer")
    _application(conn, "rejected")
    _application(conn, "ghosted")
    overall = metrics.totals(conn)
    # interviewing/offer/rejected are responses; applied and ghosted are not.
    assert overall == {"applied": 5, "responses": 3, "rate": 60}


def test_applications_per_week_groups_by_monday(conn: sqlite3.Connection) -> None:
    _application(conn, "applied")
    _application(conn, "applied", applied_at="datetime('now', '-1 day')")
    _application(conn, "applied", applied_at="datetime('now', '-70 days')")  # outside window
    weekly = metrics.applications_per_week(conn)
    assert sum(row["applied"] for row in weekly) == 2
    for row in weekly:
        # Every week key is a Monday.
        assert (
            conn.execute("SELECT strftime('%w', ?) AS dow", (row["week_start"],)).fetchone()["dow"]
            == "1"
        )


def test_response_rate_by_source(conn: sqlite3.Connection) -> None:
    _application(conn, "interviewing", source_name="Remotive")
    _application(conn, "applied", source_name="Remotive")
    _application(conn, "applied", source_name="RemoteOK")
    rows = {row["name"]: row for row in metrics.response_rate_by_source(conn)}
    assert rows["Remotive"]["applied"] == 2 and rows["Remotive"]["responses"] == 1
    assert rows["Remotive"]["rate"] == 50
    assert rows["RemoteOK"]["rate"] == 0


def test_response_rate_by_band(conn: sqlite3.Connection) -> None:
    _application(conn, "offer", score=95)
    _application(conn, "applied", score=95)
    _application(conn, "applied", score=55)
    bands = {row["name"]: row for row in metrics.response_rate_by_band(conn)}
    assert bands["90–100"]["applied"] == 2 and bands["90–100"]["rate"] == 50
    assert bands["50–69"]["applied"] == 1 and bands["50–69"]["rate"] == 0
    assert bands["below 50"]["applied"] == 0 and bands["below 50"]["rate"] == 0


def test_metrics_page_renders(client: TestClient) -> None:
    page = client.get("/metrics")
    assert page.status_code == 200
    assert "No applications yet" in page.text
