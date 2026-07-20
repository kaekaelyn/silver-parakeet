"""Metrics: applications/week and response rate by source and score band.

"Response" means the pipeline moved past applied — interviewing, offer,
or an explicit rejection. Applications still sitting in applied (or
marked ghosted) count as no response; that is the honest denominator
PLAN §7 asks for ("so he can see what's working").
"""

import sqlite3

RESPONSE_STATES = ("interviewing", "offer", "rejected")
SCORE_BANDS = ((90, 100, "90–100"), (70, 89, "70–89"), (50, 69, "50–69"), (0, 49, "below 50"))
DEFAULT_WEEKS = 8


def applications_per_week(conn: sqlite3.Connection, weeks: int = DEFAULT_WEEKS) -> list[dict]:
    """Applications per calendar week (Monday start), most recent last."""
    rows = conn.execute(
        """SELECT date(a.applied_at, '-6 days', 'weekday 1') AS week_start,
                  count(*) AS applied
           FROM applications a
           WHERE a.applied_at IS NOT NULL
             AND a.applied_at >= datetime('now', ?)
           GROUP BY week_start ORDER BY week_start""",
        (f"-{weeks * 7} days",),
    ).fetchall()
    return [dict(row) for row in rows]


def _with_rate(rows: list[dict]) -> list[dict]:
    for row in rows:
        row["responses"] = row["responses"] or 0
        row["rate"] = round(100 * row["responses"] / row["applied"]) if row["applied"] else 0
    return rows


def response_rate_by_source(conn: sqlite3.Connection) -> list[dict]:
    placeholders = ", ".join("?" for _ in RESPONSE_STATES)
    rows = conn.execute(
        f"""SELECT coalesce(src.name, 'Unknown') AS name,
                   count(*) AS applied,
                   sum(CASE WHEN a.state IN ({placeholders}) THEN 1 ELSE 0 END) AS responses
            FROM applications a
            JOIN jobs j ON j.id = a.job_id
            LEFT JOIN sources src ON src.id = j.source_id
            WHERE a.applied_at IS NOT NULL
            GROUP BY name ORDER BY applied DESC""",
        RESPONSE_STATES,
    ).fetchall()
    return _with_rate([dict(row) for row in rows])


def response_rate_by_band(conn: sqlite3.Connection) -> list[dict]:
    placeholders = ", ".join("?" for _ in RESPONSE_STATES)
    out: list[dict] = []
    for low, high, label in SCORE_BANDS:
        row = conn.execute(
            f"""SELECT count(*) AS applied,
                       sum(CASE WHEN a.state IN ({placeholders}) THEN 1 ELSE 0 END) AS responses
                FROM applications a
                JOIN scores s ON s.job_id = a.job_id AND s.scorer = 'heuristic'
                WHERE a.applied_at IS NOT NULL AND s.score BETWEEN ? AND ?""",
            (*RESPONSE_STATES, low, high),
        ).fetchone()
        out.append({"name": label, "applied": row["applied"], "responses": row["responses"]})
    return _with_rate(out)


def totals(conn: sqlite3.Connection) -> dict:
    placeholders = ", ".join("?" for _ in RESPONSE_STATES)
    row = conn.execute(
        f"""SELECT count(*) AS applied,
                   sum(CASE WHEN a.state IN ({placeholders}) THEN 1 ELSE 0 END) AS responses
            FROM applications a WHERE a.applied_at IS NOT NULL""",
        RESPONSE_STATES,
    ).fetchone()
    result = {"applied": row["applied"], "responses": row["responses"] or 0}
    result["rate"] = (
        round(100 * result["responses"] / result["applied"]) if result["applied"] else 0
    )
    return result
