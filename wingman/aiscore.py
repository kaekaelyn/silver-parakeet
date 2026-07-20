"""AI batch scoring: score+rationale+red-flags for promising jobs.

Runs as a scheduled batch (polite to subscription limits). Results are
schema-validated and cached in scores under scorer='ai'; nothing is
scored twice. A provider failure stops the batch with one event — it
never breaks the app or the heuristic scores.
"""

import json
import logging
import sqlite3

from pydantic import BaseModel, Field, ValidationError

from wingman import ai, db, scoring

logger = logging.getLogger(__name__)

BATCH_LIMIT = 10
DESCRIPTION_CHARS = 4000

SCORE_SCHEMA = {
    "type": "object",
    "properties": {
        "score": {"type": "integer", "minimum": 0, "maximum": 100},
        "rationale": {"type": "array", "items": {"type": "string"}, "maxItems": 3},
        "red_flags": {"type": "array", "items": {"type": "string"}},
    },
    "required": ["score", "rationale", "red_flags"],
}

SYSTEM_PROMPT = (
    "You evaluate job postings for one specific candidate. Be blunt and "
    "practical: fit score 0-100, at most three short rationale bullets, and "
    "red flags (ghost-job signals, contract-vs-perm mismatch, visa issues, "
    "vague pay, reposted-forever listings). No flattery, no hedging."
)


class AIScoreResult(BaseModel):
    score: int = Field(ge=0, le=100)
    rationale: list[str] = Field(max_length=3)
    red_flags: list[str] = []


def _criteria_summary(conn: sqlite3.Connection) -> str:
    parts = []
    for criteria in scoring.load_enabled_criteria(conn):
        bits = [f"profile '{criteria.name}'"]
        if criteria.query is not None:
            bits.append(f"wants: {criteria.query.source}")
        if criteria.nice_to_have:
            bits.append("nice to have: " + ", ".join(criteria.nice_to_have))
        if criteria.salary_floor:
            bits.append(f"salary floor ${criteria.salary_floor}")
        if criteria.remote_only:
            bits.append("remote only")
        parts.append("; ".join(bits))
    return " | ".join(parts) or "no criteria configured"


def _job_prompt(job: sqlite3.Row, criteria_summary: str) -> str:
    salary = ""
    if job["salary_min"] or job["salary_max"]:
        salary = f"Salary posted: {job['salary_min']}-{job['salary_max']}. "
    return (
        f"Candidate's criteria: {criteria_summary}\n\n"
        f"Posting: {job['title']} at {job['company'] or 'unknown company'} "
        f"({job['location'] or 'location unspecified'}). {salary}\n"
        f"Description:\n{(job['description'] or '')[:DESCRIPTION_CHARS]}"
    )


def pending_jobs(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    """Jobs worth AI attention: at/above threshold, visible, not yet AI-scored."""
    threshold = scoring.get_threshold(conn)
    return conn.execute(
        """SELECT j.* FROM jobs j
           JOIN scores h ON h.job_id = j.id AND h.scorer = 'heuristic'
           LEFT JOIN scores a ON a.job_id = j.id AND a.scorer = 'ai'
           WHERE a.job_id IS NULL AND j.hidden = 0 AND h.score >= ?
           ORDER BY h.score DESC
           LIMIT ?""",
        (max(threshold, 1), BATCH_LIMIT),
    ).fetchall()


def score_pending(conn: sqlite3.Connection) -> dict[str, int]:
    """Run one AI scoring batch. Returns counts; never raises."""
    provider = ai.get_provider(conn)
    if provider.name == "none":
        return {"scored": 0, "skipped": 0}
    jobs = pending_jobs(conn)
    scored = 0
    criteria_summary = _criteria_summary(conn)
    for job in jobs:
        raw = provider.complete(SYSTEM_PROMPT, _job_prompt(job, criteria_summary), SCORE_SCHEMA)
        if raw is None:
            _record_failure(conn, provider.name, "provider returned nothing")
            break  # one failure event, stop the batch — don't hammer a broken CLI
        try:
            result = AIScoreResult.model_validate(raw)
        except ValidationError as exc:
            _record_failure(
                conn, provider.name, f"schema validation failed: {exc.error_count()} errors"
            )
            break
        conn.execute(
            """INSERT INTO scores (job_id, scorer, score, rationale_json, scored_at)
               VALUES (?, 'ai', ?, ?, datetime('now'))
               ON CONFLICT (job_id, scorer) DO UPDATE
               SET score = excluded.score, rationale_json = excluded.rationale_json,
                   scored_at = excluded.scored_at""",
            (
                job["id"],
                result.score,
                json.dumps(
                    {
                        "rationale": result.rationale,
                        "red_flags": result.red_flags,
                        "provider": provider.name,
                    }
                ),
            ),
        )
        conn.commit()
        scored += 1
    if scored:
        db.record_event(conn, "ai.ok", json.dumps({"provider": provider.name, "scored": scored}))
    return {"scored": scored, "skipped": len(jobs) - scored}


def _record_failure(conn: sqlite3.Connection, provider: str, reason: str) -> None:
    logger.warning("ai scoring failed (%s): %s", provider, reason)
    db.record_event(conn, "ai.error", json.dumps({"provider": provider, "error": reason}))


def ai_score_for(conn: sqlite3.Connection, job_id: int) -> dict | None:
    row = conn.execute(
        "SELECT score, rationale_json FROM scores WHERE job_id = ? AND scorer = 'ai'",
        (job_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        rationale = json.loads(row["rationale_json"] or "{}")
    except json.JSONDecodeError:
        rationale = {}
    return {
        "score": row["score"],
        "rationale": rationale.get("rationale", []),
        "red_flags": rationale.get("red_flags", []),
        "provider": rationale.get("provider", ""),
    }
