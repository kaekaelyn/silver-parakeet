"""M7d: Tier 3 prep pack on unsupported-ATS jobs."""

import json
import sqlite3

import pytest
from fastapi.testclient import TestClient

from wingman import ai, db, prep, vault


class _TailorProvider(ai.AIProvider):
    name = "fake"
    label = "Fake"
    binary = None

    def __init__(self, response) -> None:
        self.response = response
        self.calls = 0

    def complete(self, system, prompt, json_schema=None):
        self.calls += 1
        return self.response


def _insert_job(client: TestClient, url: str = "https://jobs.example.com/1", **fields) -> int:
    with db.session(client.app.state.settings.db_path) as conn:
        cursor = conn.execute(
            """INSERT INTO jobs (title, company, url, dedupe_hash, description, ats_kind)
               VALUES ('Staff Engineer', 'Meridian', ?, ?, 'Python and SQL role', ?)""",
            (url, f"hash-{url}", fields.get("ats_kind")),
        )
        conn.commit()
        return cursor.lastrowid


def _use_fake_provider(
    client: TestClient, monkeypatch: pytest.MonkeyPatch, response
) -> _TailorProvider:
    provider = _TailorProvider(response)
    monkeypatch.setitem(ai.PROVIDERS, "fake", provider)
    with db.session(client.app.state.settings.db_path) as conn:
        ai.set_provider_name(conn, "fake")
    return provider


def test_pack_renders_for_unsupported_kinds(client: TestClient) -> None:
    with db.session(client.app.state.settings.db_path) as conn:
        vault.set_profile_values(conn, {"contact.email": "andy@example.com"})
    for url, kind in (("https://jobs.example.com/1", None), ("https://x.example/2", "taleo")):
        page = client.get(f"/jobs/{_insert_job(client, url, ats_kind=kind)}").text
        assert "Prep pack" in page
        assert "andy@example.com" in page
        assert "Decline to self-identify" in page  # seeded canned answers included
        assert "copy-btn" in page


def test_pack_absent_for_supported_kind(client: TestClient) -> None:
    job_id = _insert_job(client, "https://boards.greenhouse.io/meridian/jobs/1")
    page = client.get(f"/jobs/{job_id}").text
    assert "Prep pack" not in page
    assert "copy-btn" not in page


def test_pack_includes_saved_cover_letter(client: TestClient) -> None:
    job_id = _insert_job(client)
    client.post(f"/jobs/{job_id}/cover-letter")
    page = client.get(f"/jobs/{job_id}").text
    assert "prep-letter" in page  # the letter block, with its copy button


def test_tailoring_hidden_without_provider(client: TestClient) -> None:
    page = client.get(f"/jobs/{_insert_job(client)}").text
    assert "Resume tailoring" not in page


def test_tailoring_generated_once_and_cached(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _use_fake_provider(
        client, monkeypatch, {"suggestions": ["Emphasize Python", "Lead with SQL work"]}
    )
    job_id = _insert_job(client)
    assert "Suggest what to emphasize" in client.get(f"/jobs/{job_id}").text
    response = client.post(f"/jobs/{job_id}/tailoring", follow_redirects=False)
    assert response.status_code == 303
    page = client.get(f"/jobs/{job_id}").text
    assert "Emphasize Python" in page and "Lead with SQL work" in page
    # A second request never re-calls the provider: docs_json caches it.
    client.post(f"/jobs/{job_id}/tailoring")
    assert provider.calls == 1
    with db.session(client.app.state.settings.db_path) as conn:
        docs = json.loads(
            conn.execute(
                "SELECT docs_json FROM applications WHERE job_id = ?", (job_id,)
            ).fetchone()["docs_json"]
        )
    assert docs["tailoring"] == ["Emphasize Python", "Lead with SQL work"]


def test_tailoring_degradation_shows_pack_and_records_event(
    client: TestClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    provider = _use_fake_provider(client, monkeypatch, {"unexpected": "shape"})
    job_id = _insert_job(client)
    response = client.post(f"/jobs/{job_id}/tailoring", follow_redirects=False)
    assert response.status_code == 303
    page = client.get(f"/jobs/{job_id}").text
    assert "Prep pack" in page  # pack still renders, just without suggestions
    assert "Suggest what to emphasize" in page  # retry stays available
    assert provider.calls == 1
    with db.session(client.app.state.settings.db_path) as conn:
        errors = conn.execute("SELECT count(*) AS n FROM events WHERE kind = 'ai.error'").fetchone()
    assert errors["n"] == 1
    assert client.get("/health").json()["status"] == "ok"


def test_tailoring_missing_job_404s(client: TestClient) -> None:
    assert client.post("/jobs/99999/tailoring").status_code == 404


def _job_row(conn: sqlite3.Connection) -> sqlite3.Row:
    cursor = conn.execute(
        """INSERT INTO jobs (title, company, url, dedupe_hash, description)
           VALUES ('Staff Engineer', 'Meridian', 'https://x.example/1', 'h1', 'desc')"""
    )
    conn.commit()
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()


def test_save_tailoring_preserves_other_docs(conn: sqlite3.Connection) -> None:
    job = _job_row(conn)
    conn.execute(
        "INSERT INTO applications (job_id, state, docs_json) VALUES (?, 'applied', ?)",
        (job["id"], '{"cover_letter": "Dear team..."}'),
    )
    conn.commit()
    prep.save_tailoring(conn, job["id"], ["Bullet one"])
    assert prep.saved_tailoring(conn, job["id"]) == ["Bullet one"]
    docs = json.loads(
        conn.execute(
            "SELECT docs_json FROM applications WHERE job_id = ?", (job["id"],)
        ).fetchone()["docs_json"]
    )
    assert docs["cover_letter"] == "Dear team..."
    state = conn.execute(
        "SELECT state FROM applications WHERE job_id = ?", (job["id"],)
    ).fetchone()["state"]
    assert state == "applied"  # the cache write never regresses pipeline state


def test_generate_without_provider_is_silent(conn: sqlite3.Connection) -> None:
    assert prep.generate_tailoring(conn, _job_row(conn)) is None
    assert conn.execute("SELECT count(*) AS n FROM events").fetchone()["n"] == 0


def test_generate_trims_and_cleans_suggestions(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    response = {"suggestions": [" one ", 7, "", "two", "three", "four", "five", "six"]}
    monkeypatch.setitem(ai.PROVIDERS, "fake", _TailorProvider(response))
    ai.set_provider_name(conn, "fake")
    assert prep.generate_tailoring(conn, _job_row(conn)) == [
        "one",
        "two",
        "three",
        "four",
        "five",
    ]
