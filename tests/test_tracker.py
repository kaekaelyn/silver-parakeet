import sqlite3

import pytest

from wingman import tracker


def _job(conn: sqlite3.Connection, title: str = "Engineer") -> int:
    cursor = conn.execute(
        "INSERT INTO jobs (title, url, dedupe_hash) VALUES (?, ?, ?)",
        (title, f"https://x.example/{title}", f"h-{title}"),
    )
    conn.commit()
    return cursor.lastrowid


def test_pipeline_transitions(conn: sqlite3.Connection) -> None:
    job_id = _job(conn)
    for state in ("interested", "applied", "interviewing", "offer"):
        tracker.set_state(conn, job_id, state)
        row = conn.execute("SELECT state FROM applications WHERE job_id = ?", (job_id,)).fetchone()
        assert row["state"] == state
    # Still exactly one application row after four transitions.
    assert conn.execute("SELECT count(*) AS n FROM applications").fetchone()["n"] == 1


def test_applied_sets_timestamp_and_creates_reminder(conn: sqlite3.Connection) -> None:
    job_id = _job(conn)
    tracker.set_state(conn, job_id, "applied")
    app_row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    assert app_row["applied_at"] is not None
    reminder = conn.execute("SELECT * FROM reminders WHERE job_id = ?", (job_id,)).fetchone()
    assert reminder is not None
    assert reminder["done"] == 0
    assert "Follow up" in reminder["message"]
    # Re-applying does not duplicate the reminder or reset applied_at.
    tracker.set_state(conn, job_id, "applied")
    assert conn.execute("SELECT count(*) AS n FROM reminders").fetchone()["n"] == 1


def test_unknown_state_rejected(conn: sqlite3.Connection) -> None:
    job_id = _job(conn)
    with pytest.raises(ValueError):
        tracker.set_state(conn, job_id, "yolo")


def test_notes_roundtrip_without_prior_application(conn: sqlite3.Connection) -> None:
    job_id = _job(conn)
    tracker.save_notes(conn, job_id, "  Referral via Sam.  ")
    row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    assert row["notes"] == "Referral via Sam."
    assert row["state"] == "interested"
    # Saving notes on an applied job must not regress its state.
    tracker.set_state(conn, job_id, "applied")
    tracker.save_notes(conn, job_id, "Phone screen booked.")
    row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    assert row["state"] == "applied"
    assert row["notes"] == "Phone screen booked."


def test_manual_reminder_and_due_query(conn: sqlite3.Connection) -> None:
    job_id = _job(conn)
    tracker.add_reminder(conn, job_id, "2000-01-01", "Way overdue")
    tracker.add_reminder(conn, job_id, "2099-01-01", "Far future")
    due = tracker.due_reminders(conn)
    assert [r["message"] for r in due] == ["Way overdue"]
    upcoming = tracker.upcoming_reminders(conn)
    assert [r["message"] for r in upcoming] == ["Far future"]
    tracker.complete_reminder(conn, due[0]["id"])
    assert tracker.due_reminders(conn) == []


def test_pipeline_board_groups_by_state(conn: sqlite3.Connection) -> None:
    a, b = _job(conn, "A"), _job(conn, "B")
    tracker.set_state(conn, a, "applied")
    tracker.set_state(conn, b, "interested")
    board = tracker.pipeline_board(conn)
    assert [j["title"] for j in board["applied"]] == ["A"]
    assert [j["title"] for j in board["interested"]] == ["B"]


def test_manual_reminder_does_not_suppress_follow_up(conn: sqlite3.Connection) -> None:
    job_id = _job(conn)
    tracker.add_reminder(conn, job_id, "2099-01-01", "prep for phone screen")
    tracker.set_state(conn, job_id, "applied")
    messages = [r["message"] for r in conn.execute("SELECT message FROM reminders")]
    assert tracker.FOLLOW_UP_MESSAGE in messages
    assert "prep for phone screen" in messages


def test_inbox_reset_preserves_application_history(conn: sqlite3.Connection) -> None:
    job_id = _job(conn)
    tracker.set_state(conn, job_id, "applied")
    tracker.save_notes(conn, job_id, "precious notes")
    tracker.set_state(conn, job_id, "inbox")
    row = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    assert row is not None, "history must survive an inbox reset"
    assert row["state"] == "interested"
    assert row["applied_at"] is not None
    assert row["notes"] == "precious notes"
    # A job with no history is fully cleared.
    clean = _job(conn, "Clean")
    tracker.set_state(conn, clean, "interested")
    tracker.set_state(conn, clean, "inbox")
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM applications WHERE job_id = ?", (clean,)
        ).fetchone()["n"]
        == 0
    )


def test_invalid_reminder_date_rejected(conn: sqlite3.Connection) -> None:
    job_id = _job(conn)
    with pytest.raises(ValueError, match="invalid reminder date"):
        tracker.add_reminder(conn, job_id, "next tuesday", "nope")
    assert conn.execute("SELECT count(*) AS n FROM reminders").fetchone()["n"] == 0


def test_state_change_bumps_updated_at(conn: sqlite3.Connection) -> None:
    job_id = _job(conn)
    tracker.set_state(conn, job_id, "interested")
    row = conn.execute("SELECT updated_at FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    assert row["updated_at"] is not None
