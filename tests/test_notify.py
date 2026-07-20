"""ntfy notifier: settings, digest once-per-day, reminder pushes, degradation."""

import sqlite3
from datetime import datetime

import httpx
from fastapi.testclient import TestClient

from wingman import notify


def _capture_client(status_code: int = 200) -> tuple[httpx.Client, list[httpx.Request]]:
    seen: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        seen.append(request)
        return httpx.Response(status_code)

    return httpx.Client(transport=httpx.MockTransport(handler)), seen


def _configure(conn: sqlite3.Connection, topic: str = "andy-secret", hour: int = 0) -> None:
    notify.set_notify_settings(conn, topic, "https://ntfy.example", hour)


def _seed_scored_job(conn: sqlite3.Connection, title: str, score: int) -> int:
    cursor = conn.execute(
        "INSERT INTO jobs (title, company, url, dedupe_hash) VALUES (?, 'Hooli', ?, ?)",
        (title, f"https://x.example/{title}", f"h-{title}"),
    )
    conn.execute(
        "INSERT INTO scores (job_id, scorer, score) VALUES (?, 'heuristic', ?)",
        (cursor.lastrowid, score),
    )
    conn.commit()
    return cursor.lastrowid


def test_settings_roundtrip_and_defaults(conn: sqlite3.Connection) -> None:
    assert notify.get_notify_settings(conn) == {
        "topic": "",
        "server": notify.DEFAULT_SERVER,
        "digest_hour": notify.DEFAULT_DIGEST_HOUR,
    }
    notify.set_notify_settings(conn, " topic-1 ", "https://ntfy.example/", 25)
    settings = notify.get_notify_settings(conn)
    assert settings["topic"] == "topic-1"
    assert settings["server"] == "https://ntfy.example"
    assert settings["digest_hour"] == 23  # clamped


def test_push_without_topic_is_quiet_noop(conn: sqlite3.Connection) -> None:
    client, seen = _capture_client()
    assert notify.send_push(conn, "T", "body", client) is False
    assert seen == []
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "notify.error" not in kinds  # unconfigured is not an error


def test_push_posts_to_topic(conn: sqlite3.Connection) -> None:
    _configure(conn)
    client, seen = _capture_client()
    assert notify.send_push(conn, "Hello", "body text", client, tags="bell") is True
    assert str(seen[0].url) == "https://ntfy.example/andy-secret"
    assert seen[0].headers["title"] == "Hello"
    assert seen[0].headers["tags"] == "bell"
    assert seen[0].content == b"body text"
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "notify.sent" in kinds


def test_push_failure_records_one_event(conn: sqlite3.Connection) -> None:
    _configure(conn)
    client, _seen = _capture_client(status_code=500)
    assert notify.send_push(conn, "T", "body", client) is False
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert kinds.count("notify.error") == 1


def test_digest_counts_and_top_matches(conn: sqlite3.Connection) -> None:
    _seed_scored_job(conn, "Platform Engineer", 95)
    _seed_scored_job(conn, "Backend Engineer", 70)
    conn.execute(
        "INSERT INTO reminders (job_id, due_at, message) VALUES (NULL, '2020-01-01 09:00:00', 'x')"
    )
    conn.commit()
    title, message = notify.digest_content(conn)
    assert "2 new matches (1 ≥ 90), 1 follow-up due." in message
    assert "Platform Engineer at Hooli (95)" in message
    assert title


def test_digest_sends_once_per_day_after_hour(conn: sqlite3.Connection) -> None:
    _configure(conn, hour=8)
    client, seen = _capture_client()

    early = datetime(2026, 7, 20, 6, 30)
    assert notify.send_daily_digest(conn, client, now=early) is False
    assert seen == []

    morning = datetime(2026, 7, 20, 8, 5)
    assert notify.send_daily_digest(conn, client, now=morning) is True
    assert notify.send_daily_digest(conn, client, now=morning) is False  # once per day
    assert len(seen) == 1

    next_day = datetime(2026, 7, 21, 9, 0)
    assert notify.send_daily_digest(conn, client, now=next_day) is True
    assert len(seen) == 2


def test_digest_failure_retries_next_tick(conn: sqlite3.Connection) -> None:
    _configure(conn, hour=0)
    bad_client, _ = _capture_client(status_code=500)
    now = datetime(2026, 7, 20, 9, 0)
    assert notify.send_daily_digest(conn, bad_client, now=now) is False
    good_client, seen = _capture_client()
    assert notify.send_daily_digest(conn, good_client, now=now) is True
    assert len(seen) == 1


def test_due_reminders_pushed_exactly_once(conn: sqlite3.Connection) -> None:
    _configure(conn)
    job_id = _seed_scored_job(conn, "Engineer", 80)
    conn.execute(
        "INSERT INTO reminders (job_id, due_at, message) VALUES (?, '2020-01-01 09:00:00', ?)",
        (job_id, "Follow up?"),
    )
    conn.execute(
        "INSERT INTO reminders (job_id, due_at, message) VALUES (NULL, '2999-01-01 09:00:00', ?)",
        ("future",),
    )
    conn.commit()
    client, seen = _capture_client()

    assert notify.send_due_reminder_pushes(conn, client) == 1
    assert b"Follow up?" in seen[0].content and b"Engineer at Hooli" in seen[0].content
    assert notify.send_due_reminder_pushes(conn, client) == 0  # notified_at set
    assert len(seen) == 1


def test_reminder_push_failure_keeps_it_pending(conn: sqlite3.Connection) -> None:
    _configure(conn)
    conn.execute(
        "INSERT INTO reminders (job_id, due_at, message) VALUES (NULL, '2020-01-01 09:00:00', 'x')"
    )
    conn.commit()
    bad_client, _ = _capture_client(status_code=500)
    assert notify.send_due_reminder_pushes(conn, bad_client) == 0
    row = conn.execute("SELECT notified_at FROM reminders").fetchone()
    assert row["notified_at"] is None
    good_client, _ = _capture_client()
    assert notify.send_due_reminder_pushes(conn, good_client) == 1


def test_notify_page_and_settings_form(client: TestClient) -> None:
    page = client.get("/notify")
    assert page.status_code == 200
    assert "ntfy topic" in page.text
    response = client.post(
        "/notify/settings",
        data={"topic": "my-topic", "server": "", "digest_hour": "7"},
        follow_redirects=False,
    )
    assert response.status_code == 303
    page = client.get("/notify").text
    assert "my-topic" in page
    assert notify.DEFAULT_SERVER in page
