"""ntfy push notifications: morning digest and due-reminder pushes.

One HTTP POST per notification to an ntfy topic (PLAN §9) — the ntfy
Android app turns that into real push. The topic is entered on the
Notify page (env vars as fallback); with no topic configured every
function is a quiet no-op, so notifications degrade exactly like AI.
"""

import json
import logging
import os
import sqlite3
from datetime import datetime

import httpx

from wingman import db, scoring
from wingman.config import DEFAULT_ENV_FILE, parse_env_file

logger = logging.getLogger(__name__)

TOPIC_KEY = "notify.ntfy_topic"
SERVER_KEY = "notify.ntfy_server"
DIGEST_HOUR_KEY = "notify.digest_hour"
LAST_DIGEST_KEY = "notify.last_digest_date"

DEFAULT_SERVER = "https://ntfy.sh"
DEFAULT_DIGEST_HOUR = 8
PUSH_TIMEOUT = 10.0
DIGEST_TOP_MATCHES = 3


def get_notify_settings(conn: sqlite3.Connection) -> dict:
    rows = dict(conn.execute("SELECT key, value FROM profile WHERE key LIKE 'notify.%'").fetchall())
    env = parse_env_file(DEFAULT_ENV_FILE)
    env.update({k: v for k, v in os.environ.items() if k.startswith("WINGMAN_")})
    topic = (rows.get(TOPIC_KEY) or "").strip() or (env.get("WINGMAN_NTFY_TOPIC") or "").strip()
    server = (
        (rows.get(SERVER_KEY) or "").strip()
        or (env.get("WINGMAN_NTFY_SERVER") or "").strip()
        or DEFAULT_SERVER
    )
    try:
        digest_hour = int(rows.get(DIGEST_HOUR_KEY) or DEFAULT_DIGEST_HOUR)
    except ValueError:
        digest_hour = DEFAULT_DIGEST_HOUR
    return {
        "topic": topic,
        "server": server.rstrip("/"),
        "digest_hour": min(23, max(0, digest_hour)),
    }


def set_notify_settings(
    conn: sqlite3.Connection, topic: str, server: str, digest_hour: int
) -> None:
    values = {
        TOPIC_KEY: topic.strip(),
        SERVER_KEY: server.strip().rstrip("/"),
        DIGEST_HOUR_KEY: str(min(23, max(0, digest_hour))),
    }
    for key, value in values.items():
        conn.execute(
            """INSERT INTO profile (key, value) VALUES (?, ?)
               ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )
    conn.commit()
    # Configured-or-not only: the topic is effectively a secret (anyone who
    # knows it can read the pushes), so it stays out of the events log.
    db.record_event(conn, "notify.settings", json.dumps({"configured": bool(topic.strip())}))


def send_push(
    conn: sqlite3.Connection,
    title: str,
    message: str,
    client: httpx.Client | None = None,
    tags: str = "",
) -> bool:
    """POST one notification; False (with one event) on any failure."""
    settings = get_notify_settings(conn)
    if not settings["topic"]:
        return False
    headers = {"Title": title}
    if tags:
        headers["Tags"] = tags
    own_client = client is None
    if own_client:
        client = httpx.Client(timeout=PUSH_TIMEOUT)
    try:
        response = client.post(
            f"{settings['server']}/{settings['topic']}",
            content=message.encode(),
            headers=headers,
        )
        response.raise_for_status()
    except Exception as exc:
        logger.warning("ntfy push failed: %s", str(exc).splitlines()[0])
        db.record_event(conn, "notify.error", json.dumps({"error": str(exc)[:200]}))
        return False
    finally:
        if own_client:
            client.close()
    db.record_event(conn, "notify.sent", json.dumps({"title": title}))
    return True


def digest_content(conn: sqlite3.Connection) -> tuple[str, str]:
    """(title, message) for the morning digest — counts plus top matches."""
    threshold = scoring.get_threshold(conn)
    new_rows = conn.execute(
        """SELECT j.title, j.company, s.score FROM jobs j
           JOIN scores s ON s.job_id = j.id AND s.scorer = 'heuristic'
           WHERE j.hidden = 0 AND s.score >= ?
             AND j.first_seen_at >= datetime('now', '-1 day')
           ORDER BY s.score DESC""",
        (threshold,),
    ).fetchall()
    strong = sum(1 for row in new_rows if row["score"] >= 90)
    due = conn.execute(
        "SELECT count(*) AS n FROM reminders WHERE done = 0 AND due_at <= datetime('now')"
    ).fetchone()["n"]

    bits = [f"{len(new_rows)} new match{'es' if len(new_rows) != 1 else ''}"]
    if strong:
        bits[0] += f" ({strong} ≥ 90)"
    if due:
        bits.append(f"{due} follow-up{'s' if due != 1 else ''} due")
    lines = [", ".join(bits) + "."]
    for row in new_rows[:DIGEST_TOP_MATCHES]:
        company = f" at {row['company']}" if row["company"] else ""
        lines.append(f"• {row['title']}{company} ({row['score']})")
    return "Wingman morning digest", "\n".join(lines)


def send_daily_digest(
    conn: sqlite3.Connection,
    client: httpx.Client | None = None,
    now: datetime | None = None,
) -> bool:
    """Send the digest once per local day, at/after the configured hour."""
    settings = get_notify_settings(conn)
    if not settings["topic"]:
        return False
    now = now or datetime.now()
    if now.hour < settings["digest_hour"]:
        return False
    today = now.date().isoformat()
    row = conn.execute("SELECT value FROM profile WHERE key = ?", (LAST_DIGEST_KEY,)).fetchone()
    if row and row["value"] == today:
        return False
    title, message = digest_content(conn)
    if not send_push(conn, title, message, client, tags="sunrise"):
        return False  # not marked sent: the next tick retries
    conn.execute(
        """INSERT INTO profile (key, value) VALUES (?, ?)
           ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
        (LAST_DIGEST_KEY, today),
    )
    conn.commit()
    return True


def send_due_reminder_pushes(conn: sqlite3.Connection, client: httpx.Client | None = None) -> int:
    """Push each newly-due reminder once; notified_at stops re-pushes."""
    if not get_notify_settings(conn)["topic"]:
        return 0
    rows = conn.execute(
        """SELECT r.*, j.title AS job_title, j.company FROM reminders r
           LEFT JOIN jobs j ON j.id = r.job_id
           WHERE r.done = 0 AND r.notified_at IS NULL AND r.due_at <= datetime('now')
           ORDER BY r.due_at"""
    ).fetchall()
    sent = 0
    for row in rows:
        about = ""
        if row["job_title"]:
            about = f" — {row['job_title']}" + (f" at {row['company']}" if row["company"] else "")
        if not send_push(conn, "Wingman reminder", f"{row['message']}{about}", client, tags="bell"):
            break  # server unreachable: keep notified_at NULL and retry next tick
        conn.execute(
            "UPDATE reminders SET notified_at = datetime('now') WHERE id = ?", (row["id"],)
        )
        conn.commit()
        sent += 1
    return sent


def tick(conn: sqlite3.Connection, client: httpx.Client | None = None) -> None:
    """One scheduler pass: digest (when due) plus reminder pushes."""
    send_daily_digest(conn, client)
    send_due_reminder_pushes(conn, client)
