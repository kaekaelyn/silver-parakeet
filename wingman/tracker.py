"""Pipeline state transitions, notes, and follow-up reminders.

Timestamps in the reminders table use SQLite's 'YYYY-MM-DD HH:MM:SS'
format so due-date comparisons against datetime('now') stay consistent.
"""

import json
import logging
import sqlite3
from datetime import date

from wingman import db

logger = logging.getLogger(__name__)

PIPELINE_STATES = ("interested", "applied", "interviewing", "offer", "rejected", "ghosted")
FOLLOW_UP_DAYS = 7
FOLLOW_UP_MESSAGE = "Follow up on this application?"


def set_state(conn: sqlite3.Connection, job_id: int, state: str) -> None:
    """Apply a state action: pipeline state, 'hidden' flag, or 'inbox' reset."""
    if state == "hidden":
        # Hiding is a job attribute, not a pipeline state.
        conn.execute("UPDATE jobs SET hidden = 1 WHERE id = ?", (job_id,))
    elif state == "inbox":
        conn.execute("UPDATE jobs SET hidden = 0 WHERE id = ?", (job_id,))
        row = conn.execute(
            "SELECT applied_at, notes FROM applications WHERE job_id = ?", (job_id,)
        ).fetchone()
        if row and (row["applied_at"] or (row["notes"] or "").strip()):
            # Application history must never be silently destroyed: a job
            # with an applied date or notes drops back to 'interested'
            # instead of being deleted.
            conn.execute(
                """UPDATE applications SET state = 'interested',
                       updated_at = datetime('now') WHERE job_id = ?""",
                (job_id,),
            )
        else:
            conn.execute("DELETE FROM applications WHERE job_id = ?", (job_id,))
    elif state in PIPELINE_STATES:
        conn.execute(
            """INSERT INTO applications (job_id, state, updated_at)
               VALUES (?, ?, datetime('now'))
               ON CONFLICT (job_id) DO UPDATE
               SET state = excluded.state, updated_at = excluded.updated_at""",
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
    # Only an existing *follow-up* reminder counts: an unrelated manual
    # reminder ("prep for phone screen") must not suppress the automatic one.
    exists = conn.execute(
        "SELECT 1 FROM reminders WHERE job_id = ? AND done = 0 AND message = ?",
        (job_id, FOLLOW_UP_MESSAGE),
    ).fetchone()
    if not exists:
        conn.execute(
            "INSERT INTO reminders (job_id, due_at, message) VALUES (?, datetime('now', ?), ?)",
            (job_id, f"+{FOLLOW_UP_DAYS} days", FOLLOW_UP_MESSAGE),
        )


def save_notes(conn: sqlite3.Connection, job_id: int, notes: str) -> None:
    """Notes live on the application row; saving notes creates one if needed."""
    conn.execute(
        """INSERT INTO applications (job_id, state, notes, updated_at)
           VALUES (?, 'interested', ?, datetime('now'))
           ON CONFLICT (job_id) DO UPDATE
           SET notes = excluded.notes, updated_at = excluded.updated_at""",
        (job_id, notes.strip()),
    )
    conn.commit()
    db.record_event(conn, "job.notes", json.dumps({"job_id": job_id}))


def add_reminder(conn: sqlite3.Connection, job_id: int | None, due_date: str, message: str) -> None:
    """Manual reminder; due_date must be YYYY-MM-DD (due at 09:00 that day)."""
    try:
        parsed = date.fromisoformat(due_date.strip())
    except ValueError as exc:
        raise ValueError(f"invalid reminder date {due_date!r}, expected YYYY-MM-DD") from exc
    conn.execute(
        "INSERT INTO reminders (job_id, due_at, message) VALUES (?, ?, ?)",
        (job_id, f"{parsed.isoformat()} 09:00:00", message.strip() or "Follow up"),
    )
    conn.commit()
    db.record_event(
        conn, "reminder.created", json.dumps({"job_id": job_id, "due": parsed.isoformat()})
    )


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
    """Jobs grouped by pipeline state, most recently updated first."""
    rows = conn.execute(
        """SELECT j.id, j.title, j.company, j.url, a.state, a.applied_at, a.notes,
                  coalesce(s.score, 0) AS score
           FROM applications a
           JOIN jobs j ON j.id = a.job_id
           LEFT JOIN scores s ON s.job_id = j.id AND s.scorer = 'heuristic'
           ORDER BY coalesce(a.updated_at, '') DESC, a.id DESC"""
    ).fetchall()
    board: dict[str, list[dict]] = {state: [] for state in PIPELINE_STATES}
    for row in rows:
        board[row["state"]].append(dict(row))
    return board
