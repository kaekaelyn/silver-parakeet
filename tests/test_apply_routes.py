from fastapi.testclient import TestClient

from wingman.apply import engine
from wingman.routes import apply as apply_routes


def _seed_job(client: TestClient, url: str = "https://boards.greenhouse.io/hooli/jobs/1") -> int:
    from wingman import db

    settings = client.app.state.settings
    with db.session(settings.db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO jobs (title, url, dedupe_hash) VALUES ('Engineer', ?, 'h1')", (url,)
        )
        conn.commit()
        return cursor.lastrowid


def test_apply_page_renders(client: TestClient) -> None:
    response = client.get("/apply")
    assert response.status_code == 200
    assert "Auto-submit" in response.text
    assert "Daily auto-submit cap" in response.text


def test_apply_settings_saved_from_ui(client: TestClient) -> None:
    response = client.post(
        "/apply/settings",
        data={"daily_cap": "3", "cooldown_days": "10", "auto_greenhouse": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    from wingman import db

    with db.session(client.app.state.settings.db_path) as conn:
        saved = engine.get_apply_settings(conn)
    assert saved["auto"] == {"greenhouse": True, "lever": False}
    assert saved["daily_cap"] == 3 and saved["cooldown_days"] == 10


def test_job_detail_shows_apply_card(client: TestClient) -> None:
    job_id = _seed_job(client)
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "Apply with Wingman" in response.text
    assert "greenhouse" in response.text


def test_job_detail_unsupported_ats(client: TestClient) -> None:
    job_id = _seed_job(client, url="https://example.com/careers/1")
    response = client.get(f"/jobs/{job_id}")
    assert "Apply with Wingman" not in response.text
    assert "No supported ATS detected" in response.text


def test_apply_start_calls_engine(client: TestClient, monkeypatch) -> None:
    calls: list[int] = []
    monkeypatch.setattr(
        apply_routes.engine, "start_assisted", lambda _s, job_id: calls.append(job_id)
    )
    job_id = _seed_job(client)
    response = client.post(f"/jobs/{job_id}/apply", follow_redirects=False)
    assert response.status_code == 303
    assert calls == [job_id]


def test_apply_unknown_job_404(client: TestClient) -> None:
    assert client.post("/jobs/9999/apply", follow_redirects=False).status_code == 404
    assert client.post("/jobs/9999/apply-auto", follow_redirects=False).status_code == 404
