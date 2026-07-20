"""Tier 3 prep pack: manual-application helpers for unsupported ATSes.

Contact fields, canned answers, and the cover letter, ready to copy — so
a manual application takes minutes. When an AI provider is configured,
resume-tailoring suggestions are cached on the application row's
docs_json under "tailoring" so the call happens at most once per job.
"""

import json
import logging
import sqlite3

from wingman import ai, db, letters, vault

logger = logging.getLogger(__name__)

TAILORING_KEY = "tailoring"
MAX_SUGGESTIONS = 5

TAILORING_SCHEMA = {
    "type": "object",
    "properties": {
        "suggestions": {
            "type": "array",
            "items": {"type": "string"},
            "maxItems": MAX_SUGGESTIONS,
        }
    },
    "required": ["suggestions"],
}

SYSTEM_PROMPT = (
    "You suggest how a candidate should tailor their existing resume for one "
    "specific job posting. At most five short bullets, each naming a fact the "
    "candidate already has (from their vault answers, links, or letter) to "
    "emphasize for THIS posting. Never invent experience, skills, or "
    "qualifications the vault doesn't show."
)


def prep_pack(conn: sqlite3.Connection, job: sqlite3.Row) -> dict:
    """Everything to copy into a manual application, from the vault."""
    profile = vault.get_profile(conn)
    contact = [
        (label, value)
        for key, label in vault.CONTACT_FIELDS
        if (value := profile.get(key, "").strip())
    ]
    return {
        "contact": contact,
        "answers": vault.list_answers(conn),
        "cover_letter": letters.saved_letter(conn, job["id"]),
    }


def _vault_facts(conn: sqlite3.Connection) -> str:
    profile = vault.get_profile(conn)
    lines = [
        f"- {label}: {value}"
        for key, label in vault.CONTACT_FIELDS
        if (value := profile.get(key, "").strip())
    ]
    resume = conn.execute(
        "SELECT name FROM documents WHERE kind = 'resume' AND is_default = 1 LIMIT 1"
    ).fetchone()
    if resume:
        lines.append(f"- Resume on file: {resume['name']}")
    lines.extend(
        f"- Answer to '{row['question_pattern']}': {row['answer']}"
        for row in vault.list_answers(conn)
    )
    template = profile.get(vault.COVER_LETTER_KEY, "").strip()
    if template:
        lines.append(f"- Cover letter template:\n{template}")
    return "\n".join(lines) or "(vault is empty)"


def generate_tailoring(conn: sqlite3.Connection, job: sqlite3.Row) -> list[str] | None:
    """Suggestion bullets from the AI provider, or None (letters.py degradation)."""
    provider = ai.provider_for_feature(conn, "tailoring")
    if provider.name == "none":
        return None
    prompt = (
        f"Candidate's vault (the only facts that exist):\n{_vault_facts(conn)}\n\n"
        f"Job: {job['title']} at {job['company'] or 'unknown company'}\n"
        f"Description:\n{(job['description'] or '')[:3000]}"
    )
    raw = provider.complete(SYSTEM_PROMPT, prompt, TAILORING_SCHEMA)
    suggestions = raw.get("suggestions") if isinstance(raw, dict) else None
    if isinstance(suggestions, list):
        cleaned = [s.strip() for s in suggestions if isinstance(s, str) and s.strip()]
        if cleaned:
            db.record_event(
                conn, "ai.ok", json.dumps({"provider": provider.name, "tailoring_job": job["id"]})
            )
            return cleaned[:MAX_SUGGESTIONS]
    db.record_event(
        conn,
        "ai.error",
        json.dumps({"provider": provider.name, "error": "tailoring generation failed"}),
    )
    return None


def save_tailoring(conn: sqlite3.Connection, job_id: int, suggestions: list[str]) -> None:
    """Cache the suggestions in the application row's docs_json."""
    row = conn.execute("SELECT docs_json FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    docs = {}
    if row and row["docs_json"]:
        try:
            docs = json.loads(row["docs_json"])
        except json.JSONDecodeError:
            docs = {}
    docs[TAILORING_KEY] = suggestions
    conn.execute(
        """INSERT INTO applications (job_id, state, docs_json, updated_at)
           VALUES (?, 'interested', ?, datetime('now'))
           ON CONFLICT (job_id) DO UPDATE
           SET docs_json = excluded.docs_json, updated_at = excluded.updated_at""",
        (job_id, json.dumps(docs)),
    )
    conn.commit()


def saved_tailoring(conn: sqlite3.Connection, job_id: int) -> list[str] | None:
    row = conn.execute("SELECT docs_json FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    if not row or not row["docs_json"]:
        return None
    try:
        value = json.loads(row["docs_json"]).get(TAILORING_KEY)
    except json.JSONDecodeError:
        return None
    if isinstance(value, list):
        return [s for s in value if isinstance(s, str)] or None
    return None
