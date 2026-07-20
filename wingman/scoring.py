"""Heuristic scorer: 0-100 per job with human-readable "why" chips.

Each enabled criteria profile scores a job independently; the best profile
wins and its chips are stored. Scores live in the scores table under
scorer='heuristic' and are recomputed when criteria change.

Weights are the W_* constants below (sum caps at 100). Hard exclusions
(exclude terms, blocklist, remote-only miss, salary below floor, stale
posting) score 0 with a "−reason" chip explaining why. Ghost-posting
signals (stale repost, agency wording) are small penalties with negative
chips — never hard exclusions, so a real job survives a false positive.
"""

import json
import logging
import re
import sqlite3
from dataclasses import dataclass, field
from datetime import UTC, datetime

from pydantic import BaseModel

from wingman import db
from wingman.boolquery import Query, compile_query, term_in_text
from wingman.timeutil import parse_timestamp

logger = logging.getLogger(__name__)

DEFAULT_CRITERIA_NAME = "All jobs"

W_QUERY_MATCH = 40  # boolean query matched
W_NO_QUERY_BASE = 25  # profile has no query: neutral base
W_NICE_TO_HAVE = 30  # cap across all nice-to-have term bonuses
W_RECENCY = ((2, 15), (7, 10), (14, 5))  # (max age days, points)
W_SALARY_FIT = 10  # posted salary meets the floor
W_REMOTE = 5  # confirmed remote when remote-only is set
W_WATCHLIST = 10  # posting came from a watched company's own board
W_STALE_REPOST = -10  # ghost signal: posted long ago but still listed
W_AGENCY = -10  # ghost signal: staffing-agency wording in the description
MAX_QUERY_CHIPS = 4

STALE_REPOST_DAYS = 45
# Curated agency phrasings — kept small on purpose: a false positive costs a
# real job 10 points, so only wording that near-certainly means an agency
# posting for an unnamed client belongs here.
AGENCY_RE = re.compile(
    r"\bour client\b"
    r"|\bon behalf of (?:our|a|the) client\b"
    r"|\brecruiting on behalf\b"
    r"|\bstaffing (?:agency|firm)\b"
    r"|\brecruitment (?:agency|firm)\b"
    r"|\bplacement agency\b",
    re.IGNORECASE,
)


class CriteriaConfig(BaseModel):
    """The criteria config_json shape — single source of truth."""

    query: str = ""
    nice_to_have: list[str] = []
    exclude: list[str] = []
    company_blocklist: list[str] = []
    remote_only: bool = False
    salary_floor: int | None = None
    freshness_days: int | None = None


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
    """Build a Criteria from a criteria table row; raises on bad config."""
    config = CriteriaConfig.model_validate(json.loads(row["config_json"] or "{}"))
    return Criteria(
        id=row["id"],
        name=row["name"],
        query=compile_query(config.query),
        nice_to_have=[t for t in config.nice_to_have if t.strip()],
        exclude=[t for t in config.exclude if t.strip()],
        company_blocklist=[t for t in config.company_blocklist if t.strip()],
        remote_only=config.remote_only,
        salary_floor=config.salary_floor or None,
        freshness_days=config.freshness_days,
    )


def load_enabled_criteria(conn: sqlite3.Connection) -> list[Criteria]:
    """Load enabled profiles; a single bad row is skipped, never fatal."""
    loaded: list[Criteria] = []
    for row in conn.execute("SELECT * FROM criteria WHERE enabled = 1 ORDER BY id"):
        try:
            loaded.append(criteria_from_row(row))
        except Exception as exc:
            logger.warning("criteria %r is invalid, skipping: %s", row["name"], exc)
    return loaded


def _job_age_days(job: sqlite3.Row, now: datetime) -> float | None:
    posted = parse_timestamp(job["posted_at"] or job["first_seen_at"])
    if posted is None:
        return None
    return max(0.0, (now - posted).total_seconds() / 86400)


def score_job(
    job: sqlite3.Row,
    criteria: Criteria,
    now: datetime | None = None,
    text: str | None = None,
) -> tuple[int, list[str]]:
    """Score one job against one profile. Returns (score, chips)."""
    now = now or datetime.now(UTC)
    if text is None:
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
    if (
        criteria.freshness_days is not None
        and age_days is not None
        and age_days > criteria.freshness_days
    ):
        return 0, ["−stale"]

    score = 0
    chips: list[str] = []

    if criteria.query is not None:
        matched, hits = criteria.query.matches(text)
        if not matched:
            return 0, ["−no keyword match"]
        score += W_QUERY_MATCH
        chips.extend(f"+{term}" for term in hits[:MAX_QUERY_CHIPS])
    else:
        score += W_NO_QUERY_BASE

    if criteria.nice_to_have:
        per_term = W_NICE_TO_HAVE / max(3, len(criteria.nice_to_have))
        bonus = 0.0
        for term in criteria.nice_to_have:
            if term_in_text(term, text):
                bonus += per_term
                chips.append(f"+{term}")
        score += round(min(W_NICE_TO_HAVE, bonus))

    if age_days is not None:
        for max_age, points in W_RECENCY:
            if age_days <= max_age:
                score += points
                if max_age == W_RECENCY[0][0]:
                    chips.append("+new")
                break

    if criteria.salary_floor and job["salary_min"] and job["salary_min"] >= criteria.salary_floor:
        score += W_SALARY_FIT
        chips.append("+salary")
    if criteria.remote_only and job["remote"] == 1:
        score += W_REMOTE
        chips.append("+remote")

    return min(100, score), chips


def ghost_signals(job: sqlite3.Row, now: datetime) -> tuple[int, list[str]]:
    """Ghost-posting heuristics: (penalty, chips), both empty when clean.

    Stale-repost keys off posted_at only — no first_seen_at fallback, because
    a missing posted_at is not evidence of a repost.
    """
    penalty = 0
    chips: list[str] = []
    posted = parse_timestamp(job["posted_at"])
    if posted is not None and (now - posted).total_seconds() / 86400 > STALE_REPOST_DAYS:
        penalty += W_STALE_REPOST
        chips.append("−stale-repost")
    if AGENCY_RE.search(job["description"] or ""):
        penalty += W_AGENCY
        chips.append("−agency")
    return penalty, chips


def score_job_best(
    job: sqlite3.Row,
    criteria_list: list[Criteria],
    now: datetime | None = None,
    watchlist_source_ids: frozenset[int] = frozenset(),
) -> tuple[int, list[str], str]:
    """Best (score, chips, profile name) across profiles."""
    now = now or datetime.now(UTC)
    text = f"{job['title']}\n{job['description'] or ''}".lower()
    best: tuple[int, list[str], str] | None = None
    for criteria in criteria_list:
        score, chips = score_job(job, criteria, now, text)
        if best is None or score > best[0]:
            best = (score, chips, criteria.name)
    if best is None:
        return 0, ["−no criteria"], ""
    score, chips, name = best
    # Watched-company boost (PLAN §4) — hard exclusions (score 0) stay 0.
    if score > 0 and job["source_id"] in watchlist_source_ids:
        score = min(100, score + W_WATCHLIST)
        chips = [*chips, "+watchlist"]
    # Ghost-posting penalties — hard-excluded jobs keep their single −reason chip.
    if score > 0:
        penalty, ghost_chips = ghost_signals(job, now)
        if penalty:
            score = max(0, score + penalty)
            chips = [*chips, *ghost_chips]
    return score, chips, name


def watchlist_source_ids(conn: sqlite3.Connection) -> frozenset[int]:
    from wingman.sources.boards import WATCHLIST_KINDS

    placeholders = ", ".join("?" for _ in WATCHLIST_KINDS)
    return frozenset(
        row["id"]
        for row in conn.execute(
            f"SELECT id FROM sources WHERE kind IN ({placeholders})", WATCHLIST_KINDS
        )
    )


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
    watchlist = watchlist_source_ids(conn)
    for job in rows:
        score, chips, name = score_job_best(job, criteria_list, now, watchlist)
        upsert_score(conn, job["id"], score, chips, name)
    conn.commit()
    return len(rows)


def rescore_all(conn: sqlite3.Connection) -> int:
    """Recompute every job's heuristic score (after criteria changes)."""
    criteria_list = load_enabled_criteria(conn)
    rows = conn.execute("SELECT * FROM jobs").fetchall()
    now = datetime.now(UTC)
    watchlist = watchlist_source_ids(conn)
    for job in rows:
        score, chips, name = score_job_best(job, criteria_list, now, watchlist)
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
            (DEFAULT_CRITERIA_NAME, CriteriaConfig().model_dump_json()),
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
