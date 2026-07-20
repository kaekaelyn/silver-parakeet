from fastapi.testclient import TestClient

from wingman.apply import engine
from wingman.routes import apply as apply_routes


def _seed_job(
    client: TestClient,
    url: str = "https://boards.greenhouse.io/hooli/jobs/1",
    ats_kind: str | None = None,
) -> int:
    from wingman import db

    settings = client.app.state.settings
    with db.session(settings.db_path) as conn:
        cursor = conn.execute(
            "INSERT INTO jobs (title, url, dedupe_hash, ats_kind) VALUES ('Engineer', ?, ?, ?)",
            (url, f"h-{url}", ats_kind),
        )
        conn.commit()
        return cursor.lastrowid


def _record_wingman_application(client: TestClient, kind: str) -> int:
    """A recorded (applied) Wingman application on a job of the given ATS."""
    from wingman import db

    job_id = _seed_job(client, url=f"https://example.com/{kind}/success", ats_kind=kind)
    with db.session(client.app.state.settings.db_path) as conn:
        conn.execute(
            """INSERT INTO applications (job_id, state, applied_at, method)
               VALUES (?, 'applied', datetime('now'), 'wingman-assisted')""",
            (job_id,),
        )
        conn.commit()
    return job_id


def test_apply_page_renders(client: TestClient) -> None:
    response = client.get("/apply")
    assert response.status_code == 200
    assert "Auto-submit" in response.text
    assert "Daily auto-submit cap" in response.text


def test_apply_page_lists_every_supported_ats(client: TestClient) -> None:
    from wingman.apply import ats

    response = client.get("/apply")
    for kind in ats.SUPPORTED:
        assert f'name="auto_{kind}"' in response.text
    assert "detection only" not in response.text


def test_apply_settings_saved_from_ui(client: TestClient) -> None:
    response = client.post(
        "/apply/settings",
        data={"daily_cap": "3", "cooldown_days": "10", "auto_greenhouse": "on", "auto_ashby": "on"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    from wingman import db

    with db.session(client.app.state.settings.db_path) as conn:
        saved = engine.get_apply_settings(conn)
    assert saved["auto"] == {
        "greenhouse": True,
        "lever": False,
        "ashby": True,
        "workable": False,
    }
    assert saved["daily_cap"] == 3 and saved["cooldown_days"] == 10


def test_apply_settings_key_off_ats_supported(client: TestClient, monkeypatch) -> None:
    """A future filler only has to extend ats.SUPPORTED — UI and save follow."""
    monkeypatch.setattr(
        "wingman.apply.ats.SUPPORTED", ("greenhouse", "lever", "ashby", "workable", "faketrack")
    )
    assert 'name="auto_faketrack"' in client.get("/apply").text
    client.post(
        "/apply/settings",
        data={"daily_cap": "5", "cooldown_days": "7", "auto_faketrack": "on"},
        follow_redirects=False,
    )
    from wingman import db

    with db.session(client.app.state.settings.db_path) as conn:
        saved = engine.get_apply_settings(conn)
    assert saved["auto"]["faketrack"] is True


def test_job_detail_shows_apply_card(client: TestClient) -> None:
    job_id = _seed_job(client)
    response = client.get(f"/jobs/{job_id}")
    assert response.status_code == 200
    assert "Apply with Wingman" in response.text
    assert "greenhouse" in response.text


def test_first_live_run_reminders_shown_for_every_kind(client: TestClient) -> None:
    from wingman.apply import ats
    from wingman.routes.apply import ATS_LABELS

    response = client.get("/apply")
    assert "Before trusting Wingman on a new job board" in response.text
    for kind in ats.SUPPORTED:
        assert ATS_LABELS[kind] in response.text
        assert "(not tried for real yet)" in response.text
    # No successes recorded anywhere: no dismiss button yet.
    assert "Yes, it worked" not in response.text


def test_reminder_dismissable_only_after_wingman_success(client: TestClient) -> None:
    from wingman import db

    # Without a recorded success the dismiss request is refused server-side.
    assert client.post("/apply/verified/ashby", follow_redirects=False).status_code == 303
    with db.session(client.app.state.settings.db_path) as conn:
        assert engine.live_verification(conn)["ashby"]["verified"] is False

    _record_wingman_application(client, "ashby")
    page = client.get("/apply").text
    assert "Yes, it worked" in page  # the button appeared

    assert client.post("/apply/verified/ashby", follow_redirects=False).status_code == 303
    with db.session(client.app.state.settings.db_path) as conn:
        status = engine.live_verification(conn)
    assert status["ashby"]["verified"] is True
    assert status["workable"]["verified"] is False  # others untouched
    page = client.get("/apply").text
    assert "Before trusting Wingman on a new job board" in page  # card stays for the rest
    assert "Yes, it worked" not in page  # ashby's button is gone with it


def test_reminder_card_disappears_when_all_verified(client: TestClient) -> None:
    from wingman.apply import ats

    for kind in ats.SUPPORTED:
        _record_wingman_application(client, kind)
        client.post(f"/apply/verified/{kind}", follow_redirects=False)
    page = client.get("/apply").text
    assert "Before trusting Wingman on a new job board" not in page
    assert "(not tried for real yet)" not in page


def test_reminder_dismiss_unknown_kind_404(client: TestClient) -> None:
    assert client.post("/apply/verified/taleo", follow_redirects=False).status_code == 404


def test_job_detail_first_live_run_note(client: TestClient) -> None:
    job_id = _seed_job(client)  # greenhouse URL
    assert "hasn't been tried on a real greenhouse form" in client.get(f"/jobs/{job_id}").text

    _record_wingman_application(client, "greenhouse")
    client.post("/apply/verified/greenhouse", follow_redirects=False)
    assert "hasn't been tried on a real" not in client.get(f"/jobs/{job_id}").text


def test_job_detail_shows_apply_card_for_new_ats(client: TestClient) -> None:
    for url, kind in (
        ("https://jobs.ashbyhq.com/aviato/1234", "ashby"),
        ("https://apply.workable.com/raviga/j/ABCD/", "workable"),
    ):
        job_id = _seed_job(client, url=url)
        response = client.get(f"/jobs/{job_id}")
        assert "Apply with Wingman" in response.text
        assert kind in response.text


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
