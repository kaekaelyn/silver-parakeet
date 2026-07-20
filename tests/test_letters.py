import sqlite3

import pytest

from wingman import ai, letters, vault


class _LetterProvider(ai.AIProvider):
    name = "fake"
    label = "Fake"
    binary = None

    def __init__(self, response) -> None:
        self.response = response

    def complete(self, system, prompt, json_schema=None):
        return self.response


def _job(conn: sqlite3.Connection) -> sqlite3.Row:
    cursor = conn.execute(
        """INSERT INTO jobs (title, company, url, dedupe_hash, description)
           VALUES ('Platform Engineer', 'Meridian', 'https://x.example/1', 'h1', 'desc')"""
    )
    conn.commit()
    return conn.execute("SELECT * FROM jobs WHERE id = ?", (cursor.lastrowid,)).fetchone()


def test_template_fallback_fills_placeholders(conn: sqlite3.Connection) -> None:
    vault.set_profile_values(
        conn,
        {
            vault.COVER_LETTER_KEY: "Dear {company}, I want the {title} job. — {name}",
            "contact.name": "Andy",
        },
    )
    job = _job(conn)
    letter, used_ai = letters.generate_cover_letter(conn, job)
    assert not used_ai
    assert letter == "Dear Meridian, I want the Platform Engineer job. — Andy"


def test_default_template_when_vault_empty(conn: sqlite3.Connection) -> None:
    letter, used_ai = letters.generate_cover_letter(conn, _job(conn))
    assert not used_ai
    assert "Meridian" in letter and "Platform Engineer" in letter


def test_ai_letter_used_when_provider_works(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ai.PROVIDERS, "fake", _LetterProvider({"letter": "Custom AI letter."}))
    ai.set_provider_name(conn, "fake")
    letter, used_ai = letters.generate_cover_letter(conn, _job(conn))
    assert used_ai
    assert letter == "Custom AI letter."


def test_letters_toggle_off_uses_template(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ai.PROVIDERS, "fake", _LetterProvider({"letter": "Custom AI letter."}))
    ai.set_provider_name(conn, "fake")
    ai.set_feature_enabled(conn, "letters", False)
    letter, used_ai = letters.generate_cover_letter(conn, _job(conn))
    assert not used_ai
    assert "Meridian" in letter  # template path, provider never consulted
    n = conn.execute("SELECT count(*) AS n FROM events WHERE kind LIKE 'ai.%'").fetchone()["n"]
    assert n == 0  # off is a choice, not an error


def test_ai_garbage_falls_back_with_event(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setitem(ai.PROVIDERS, "fake", _LetterProvider({"unexpected": "shape"}))
    ai.set_provider_name(conn, "fake")
    job = _job(conn)
    letter, used_ai = letters.generate_cover_letter(conn, job)
    assert not used_ai
    assert "Meridian" in letter  # template fallback still produced a letter
    events = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "ai.error" in events


def test_save_letter_preserves_other_docs(conn: sqlite3.Connection) -> None:
    job = _job(conn)
    conn.execute(
        "INSERT INTO applications (job_id, state, docs_json) VALUES (?, 'applied', ?)",
        (job["id"], '{"resume": "/path/resume.pdf"}'),
    )
    conn.commit()
    letters.save_letter(conn, job["id"], "Dear team...")
    assert letters.saved_letter(conn, job["id"]) == "Dear team..."
    import json

    docs = json.loads(
        conn.execute(
            "SELECT docs_json FROM applications WHERE job_id = ?", (job["id"],)
        ).fetchone()["docs_json"]
    )
    assert docs["resume"] == "/path/resume.pdf"
    # State was not regressed by the letter save.
    state = conn.execute(
        "SELECT state FROM applications WHERE job_id = ?", (job["id"],)
    ).fetchone()["state"]
    assert state == "applied"
