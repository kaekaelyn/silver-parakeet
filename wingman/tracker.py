"""Pipeline state transitions, notes, and follow-up reminders.

Timestamps in the reminders table use SQLite's 'YYYY-MM-DD HH:MM:SS'
format so due-date comparisons against datetime('now') stay consistent.
"""

import json
import logging
import sqlite3

from wingman import db

logger = logging.getLogger(__name__)

PIPELINE_STATES = ("interested", "applied", "interviewing", "offer", "rejected", "ghosted")
FOLLOW_UP_DAYS = 7


def set_state(conn: sqlite3.Connection, job_id: int, state: str) -> None:
    """Apply a state action: pipeline state, 'hidden' flag, or 'inbox' reset."""
    if state == "hidden":
        # Hiding is a job attribute, not a pipeline state.
        conn.execute("UPDATE jobs SET hidden = 1 WHERE id = ?", (job_id,))
    elif state == "inbox":
        conn.execute("UPDATE jobs SET hidden = 0 WHERE id = ?", (job_id,))
        conn.execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
    elif state in PIPELINE_STATES:
        conn.execute(
            """INSERT INTO applications (job_id, state) VALUES (?, ?)
               ON CONFLICT (job_id) DO UPDATE SET state = excluded.state""",
            (job_id, state),
        )
        if state == "applied":
            conn.execute(
                """UPDATE applications SET applied_at = datetime('now'), method = 'manual'
                   WHERE job_id = ? AND applied_at IS NULL""",
                (job_id,),
            )
            _ensure_follow_up_reminder(conn, job_id)
    else:
        raise ValueError(f"unknown state {state!r}")
    conn.commit()
    db.record_event(conn, "job.state", json.dumps({"job_id": job_id, "state": state}))


def _ensure_follow_up_reminder(conn: sqlite3.Connection, job_id: int) -> None:
    exists = conn.execute(
        "SELECT 1 FROM reminders WHERE job_id = ? AND done = 0", (job_id,)
    ).fetchone()
    if not exists:
        conn.execute(
            """INSERT INTO reminders (job_id, due_at, message)
               VALUES (?, datetime('now', ?), 'Follow up on this application?')""",
            (job_id, f"+{FOLLOW_UP_DAYS} days"),
        )


def save_notes(conn: sqlite3.Connection, job_id: int, notes: str) -> None:
    """Notes live on the application row; saving notes creates one if needed."""
    conn.execute(
        """INSERT INTO applications (job_id, state, notes) VALUES (?, 'interested', ?)
           ON CONFLICT (job_id) DO UPDATE SET notes = excluded.notes""",
        (job_id, notes.strip()),
    )
    conn.commit()


def add_reminder(conn: sqlite3.Connection, job_id: int | None, due_date: str, message: str) -> None:
    """Manual reminder; due_date is YYYY-MM-DD (due at 09:00 that day)."""
    conn.execute(
        "INSERT INTO reminders (job_id, due_at, message) VALUES (?, ?, ?)",
        (job_id, f"{due_date} 09:00:00", message.strip() or "Follow up"),
    )
    conn.commit()
    db.record_event(conn, "reminder.created", json.dumps({"job_id": job_id, "due": due_date}))


def complete_reminder(conn: sqlite3.Connection, reminder_id: int) -> None:
    conn.execute("UPDATE reminders SET done = 1 WHERE id = ?", (reminder_id,))
    conn.commit()
    db.record_event(conn, "reminder.done", json.dumps({"id": reminder_id}))


def due_reminders(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT r.*, j.title, j.company FROM reminders r
           LEFT JOIN jobs j ON j.id = r.job_id
           WHERE r.done = 0 AND r.due_at <= datetime('now')
           ORDER BY r.due_at"""
    ).fetchall()


def upcoming_reminders(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute(
        """SELECT r.*, j.title, j.company FROM reminders r
           LEFT JOIN jobs j ON j.id = r.job_id
           WHERE r.done = 0 AND r.due_at > datetime('now')
           ORDER BY r.due_at LIMIT 20"""
    ).fetchall()


def pipeline_board(conn: sqlite3.Connection) -> dict[str, list[dict]]:
    """Jobs grouped by pipeline state, newest activity first."""
    rows = conn.execute(
        """SELECT j.id, j.title, j.company, j.url, a.state, a.applied_at, a.notes,
                  coalesce(s.score, 0) AS score
           FROM applications a
           JOIN jobs j ON j.id = a.job_id
           LEFT JOIN scores s ON s.job_id = j.id AND s.scorer = 'heuristic'
           ORDER BY a.id DESC"""
    ).fetchall()
    board: dict[str, list[dict]] = {state: [] for state in PIPELINE_STATES}
    for row in rows:
        board.setdefault(row["state"], []).append(dict(row))
    return board
