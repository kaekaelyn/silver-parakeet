import json
from datetime import UTC, datetime

from fastapi.testclient import TestClient

from wingman import db


def _insert_scored_job(client: TestClient, title: str, score: int, **fields) -> int:
    settings = client.app.state.settings
    with db.session(settings.db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO jobs (title, company, url, dedupe_hash, description, posted_at)
               VALUES (?, ?, ?, ?, ?, ?)""",
            (
                title,
                fields.get("company", "Acme"),
                fields.get("url", f"https://example.com/{title}"),
                f"hash-{title}",
                fields.get("description", ""),
                datetime.now(UTC).isoformat(),
            ),
        )
        job_id = cursor.lastrowid
        conn.execute(
            """INSERT INTO scores (job_id, scorer, score, rationale_json)
               VALUES (?, 'heuristic', ?, ?)""",
            (job_id, score, json.dumps({"chips": ["+python"], "criteria": "Test"})),
        )
        conn.commit()
    return job_id


def test_inbox_ranks_by_score(client: TestClient) -> None:
    _insert_scored_job(client, "Low Job", 30)
    _insert_scored_job(client, "High Job", 90)
    page = client.get("/").text
    assert page.index("High Job") < page.index("Low Job")
    assert "+python" in page


def test_threshold_hides_low_scores(client: TestClient) -> None:
    _insert_scored_job(client, "Low Job", 30)
    _insert_scored_job(client, "High Job", 90)
    client.post("/settings/threshold", data={"threshold": "50"})
    page = client.get("/").text
    assert "High Job" in page
    assert "Low Job" not in page


def test_hide_and_interested_actions(client: TestClient) -> None:
    job_id = _insert_scored_job(client, "Target Job", 80)
    client.post(f"/jobs/{job_id}/state", data={"state": "interested", "next_url": "/"})
    assert "Target Job" in client.get("/?show=interested").text
    client.post(f"/jobs/{job_id}/state", data={"state": "hidden", "next_url": "/"})
    assert "Target Job" not in client.get("/").text
    # Only one applications row was created for that job.
    with db.session(client.app.state.settings.db_path) as conn:
        rows = conn.execute(
            "SELECT count(*) AS n FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
    assert rows["n"] == 1


def test_job_detail_page(client: TestClient) -> None:
    job_id = _insert_scored_job(
        client, "Detail Job", 75, description="Line one.\nLine two about Python."
    )
    page = client.get(f"/jobs/{job_id}")
    assert page.status_code == 200
    assert "Detail Job" in page.text
    assert "Line two about Python" in page.text
    assert client.get("/jobs/99999").status_code == 404


def test_criteria_editor_saves_and_rescored(client: TestClient) -> None:
    _insert_scored_job(client, "Python Backend Engineer", 25, description="python backend")
    response = client.post(
        "/criteria/save",
        data={
            "criteria_id": "0",
            "name": "Backend",
            "query": "python AND backend",
            "nice_to_have": "fastapi, postgres",
            "exclude": "crypto",
            "salary_floor": "",
            "freshness_days": "",
        },
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/criteria").text
    assert "Backend" in page and "python AND backend" in page
    # The job was rescored against the new profile.
    with db.session(client.app.state.settings.db_path) as conn:
        row = conn.execute("SELECT rationale_json FROM scores").fetchone()
    assert "Backend" in row["rationale_json"]


def test_criteria_invalid_query_shows_error(client: TestClient) -> None:
    response = client.post(
        "/criteria/save",
        data={"criteria_id": "0", "name": "Broken", "query": "python AND ("},
    )
    assert response.status_code == 422
    assert "Couldn't save" in response.text
    assert "Broken" not in client.get("/criteria").text.split("Add a profile")[0]


def test_default_criteria_seeded(client: TestClient) -> None:
    assert "All jobs" in client.get("/criteria").text


def test_next_url_open_redirect_blocked(client: TestClient) -> None:
    job_id = _insert_scored_job(client, "Redirect Job", 70)
    for evil in ("https://evil.example", "//evil.example"):
        for state in ("interested", "bogus"):
            response = client.post(
                f"/jobs/{job_id}/state",
                data={"state": state, "next_url": evil},
                follow_redirects=False,
            )
            assert response.status_code == 303
            assert response.headers["location"] == "/"


def test_double_interested_creates_one_row(client: TestClient) -> None:
    job_id = _insert_scored_job(client, "Race Job", 70)
    client.post(f"/jobs/{job_id}/state", data={"state": "interested", "next_url": "/"})
    client.post(f"/jobs/{job_id}/state", data={"state": "interested", "next_url": "/"})
    with db.session(client.app.state.settings.db_path) as conn:
        n = conn.execute(
            "SELECT count(*) AS n FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()["n"]
    assert n == 1


def test_unscored_job_still_visible_in_inbox(client: TestClient) -> None:
    settings = client.app.state.settings
    with db.session(settings.db_path) as conn:
        conn.execute(
            "INSERT INTO jobs (title, url, dedupe_hash) "
            "VALUES ('Unscored Job', 'https://x.example/u', 'u')"
        )
        conn.commit()
    assert "Unscored Job" in client.get("/").text
