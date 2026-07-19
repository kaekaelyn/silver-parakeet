"""Heuristic scorer: 0-100 per job with human-readable "why" chips.

Each enabled criteria profile scores a job independently; the best profile
wins and its chips are stored. Scores live in the scores table under
scorer='heuristic' and are recomputed when criteria change.

Weights (sum caps at 100):
    query match          40  (or 25 base when the profile has no query)
    nice-to-have terms   up to 30
    recency              up to 15
    salary at/above floor 10
    remote confirmed      5
Hard exclusions (exclude terms, blocklist, remote-only miss, salary below
floor, stale posting) score 0 with a "−reason" chip explaining why.
"""

import json
import logging
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime
from typing import Any

from wingman import db
from wingman.boolquery import Query, QueryError, compile_query, term_in_text

logger = logging.getLogger(__name__)

DEFAULT_CRITERIA_NAME = "All jobs"


@dataclass
class Criteria:
    id: int
    name: str
    query: Query | None = None
    nice_to_have: list[str] = field(default_factory=list)
    exclude: list[str] = field(default_factory=list)
    company_blocklist: list[str] = field(default_factory=list)
    remote_only: bool = False
    salary_floor: int | None = None
    freshness_days: int | None = None


def criteria_from_row(row: sqlite3.Row) -> Criteria:
    """Build a Criteria from a criteria table row; raises QueryError on a bad query."""
    config: dict[str, Any] = json.loads(row["config_json"] or "{}")
    return Criteria(
        id=row["id"],
        name=row["name"],
        query=compile_query(config.get("query", "")),
        nice_to_have=[t for t in config.get("nice_to_have", []) if t.strip()],
        exclude=[t for t in config.get("exclude", []) if t.strip()],
        company_blocklist=[t for t in config.get("company_blocklist", []) if t.strip()],
        remote_only=bool(config.get("remote_only", False)),
        salary_floor=config.get("salary_floor") or None,
        freshness_days=config.get("freshness_days") or None,
    )


def load_enabled_criteria(conn: sqlite3.Connection) -> list[Criteria]:
    loaded: list[Criteria] = []
    for row in conn.execute("SELECT * FROM criteria WHERE enabled = 1 ORDER BY id"):
        try:
            loaded.append(criteria_from_row(row))
        except QueryError as exc:
            logger.warning("criteria %r has an invalid query, skipping: %s", row["name"], exc)
    return loaded


def _job_age_days(job: sqlite3.Row, now: datetime) -> float | None:
    stamp = job["posted_at"] or job["first_seen_at"]
    if not stamp:
        return None
    try:
        posted = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if posted.tzinfo is None:
        posted = posted.replace(tzinfo=UTC)
    return max(0.0, (now - posted).total_seconds() / 86400)


def score_job(
    job: sqlite3.Row, criteria: Criteria, now: datetime | None = None
) -> tuple[int, list[str]]:
    """Score one job against one profile. Returns (score, chips)."""
    now = now or datetime.now(UTC)
    text = f"{job['title']}\n{job['description'] or ''}".lower()
    company = (job["company"] or "").lower()

    # Hard exclusions first.
    for term in criteria.exclude:
        if term_in_text(term, text):
            return 0, [f"−{term}"]
    for blocked in criteria.company_blocklist:
        if blocked.lower() in company:
            return 0, [f"−{blocked}"]
    if criteria.remote_only and job["remote"] == 0:
        return 0, ["−not remote"]
    if criteria.salary_floor and job["salary_max"] and job["salary_max"] < criteria.salary_floor:
        return 0, ["−salary below floor"]
    age_days = _job_age_days(job, now)
    if criteria.freshness_days and age_days is not None and age_days > criteria.freshness_days:
        return 0, ["−stale"]

    score = 0
    chips: list[str] = []

    if criteria.query is not None:
        matched, hits = criteria.query.matches(text)
        if not matched:
            return 0, ["−no keyword match"]
        score += 40
        chips.extend(f"+{term}" for term in hits[:4])
    else:
        score += 25

    if criteria.nice_to_have:
        per_term = 30 / max(3, len(criteria.nice_to_have))
        bonus = 0.0
        for term in criteria.nice_to_have:
            if term_in_text(term, text):
                bonus += per_term
                chips.append(f"+{term}")
        score += round(min(30, bonus))

    if age_days is not None:
        if age_days <= 2:
            score += 15
            chips.append("+new")
        elif age_days <= 7:
            score += 10
        elif age_days <= 14:
            score += 5

    if criteria.salary_floor and job["salary_min"] and job["salary_min"] >= criteria.salary_floor:
        score += 10
        chips.append("+salary")
    if criteria.remote_only and job["remote"] == 1:
        score += 5
        chips.append("+remote")

    return min(100, score), chips


def score_job_best(
    job: sqlite3.Row, criteria_list: list[Criteria], now: datetime | None = None
) -> tuple[int, list[str], str]:
    """Best (score, chips, profile name) across profiles."""
    best: tuple[int, list[str], str] = (0, ["−no criteria"], "")
    for criteria in criteria_list:
        score, chips = score_job(job, criteria, now)
        if score > best[0] or not best[2]:
            best = (score, chips, criteria.name)
    return best


def upsert_score(
    conn: sqlite3.Connection, job_id: int, score: int, chips: list[str], criteria_name: str
) -> None:
    conn.execute(
        """INSERT INTO scores (job_id, scorer, score, rationale_json, scored_at)
           VALUES (?, 'heuristic', ?, ?, datetime('now'))
           ON CONFLICT (job_id, scorer) DO UPDATE
           SET score = excluded.score, rationale_json = excluded.rationale_json,
               scored_at = excluded.scored_at""",
        (job_id, score, json.dumps({"chips": chips, "criteria": criteria_name})),
    )


def score_new_jobs(conn: sqlite3.Connection) -> int:
    """Score jobs that have no heuristic score yet. Returns count scored."""
    criteria_list = load_enabled_criteria(conn)
    rows = conn.execute(
        """SELECT j.* FROM jobs j
           LEFT JOIN scores s ON s.job_id = j.id AND s.scorer = 'heuristic'
           WHERE s.job_id IS NULL"""
    ).fetchall()
    now = datetime.now(UTC)
    for job in rows:
        score, chips, name = score_job_best(job, criteria_list, now)
        upsert_score(conn, job["id"], score, chips, name)
    conn.commit()
    return len(rows)


def rescore_all(conn: sqlite3.Connection) -> int:
    """Recompute every job's heuristic score (after criteria changes)."""
    criteria_list = load_enabled_criteria(conn)
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    now = datetime.now(UTC)
    for job in rows:
        score, chips, name = score_job_best(job, criteria_list, now)
        upsert_score(conn, job["id"], score, chips, name)
    conn.commit()
    db.record_event(conn, "scoring.rescored", json.dumps({"jobs": len(rows)}))
    return len(rows)


def ensure_default_criteria(conn: sqlite3.Connection) -> None:
    """Seed one match-everything profile so a fresh install ranks by recency."""
    row = conn.execute("SELECT count(*) AS n FROM criteria").fetchone()
    if row["n"] == 0:
        conn.execute(
            "INSERT INTO criteria (name, config_json) VALUES (?, ?)",
            (DEFAULT_CRITERIA_NAME, json.dumps({"query": ""})),
        )
        conn.commit()


def get_threshold(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT value FROM profile WHERE key = 'inbox.threshold'").fetchone()
    try:
        return int(row["value"]) if row else 0
    except (TypeError, ValueError):
        return 0


def set_threshold(conn: sqlite3.Connection, threshold: int) -> None:
    conn.execute(
        """INSERT INTO profile (key, value) VALUES ('inbox.threshold', ?)
           ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
        (str(max(0, min(100, threshold))),),
    )
    conn.commit()
