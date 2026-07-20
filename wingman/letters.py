"""Cover letter drafting: AI when available, template substitution always.

The letter is cached on the job's application row (docs_json) so M5 can
attach the exact text that was sent.
"""

import json
import logging
import sqlite3

from wingman import ai, db, vault

logger = logging.getLogger(__name__)

DEFAULT_TEMPLATE = (
    "Dear {company} team,\n\n"
    "I'm excited to apply for the {title} role. My background matches what "
    "you're looking for, and I'd love to tell you more.\n\n"
    "Best regards,\n{name}"
)

LETTER_SCHEMA = {
    "type": "object",
    "properties": {"letter": {"type": "string"}},
    "required": ["letter"],
}

SYSTEM_PROMPT = (
    "You draft short, specific cover letters (under 250 words). Plain "
    "language, no clichés, no invented experience — only rephrase and "
    "target what the candidate's template voice provides."
)


def _fill_template(template: str, job: sqlite3.Row, name: str) -> str:
    values = {
        "company": job["company"] or "your company",
        "title": job["title"],
        "name": name or "",
    }
    result = template
    for key in vault.TEMPLATE_PLACEHOLDERS:
        result = result.replace("{" + key + "}", values.get(key, ""))
    return result.strip()


def generate_cover_letter(conn: sqlite3.Connection, job: sqlite3.Row) -> tuple[str, bool]:
    """Return (letter_text, used_ai). Always produces a letter."""
    profile = vault.get_profile(conn)
    template = profile.get(vault.COVER_LETTER_KEY, "").strip() or DEFAULT_TEMPLATE
    name = profile.get("contact.name", "")
    fallback = _fill_template(template, job, name)

    provider = ai.provider_for_feature(conn, "letters")
    if provider.name != "none":
        prompt = (
            f"Candidate name: {name or 'unknown'}\n"
            f"Their template/voice:\n{template}\n\n"
            f"Job: {job['title']} at {job['company'] or 'unknown company'}\n"
            f"Description:\n{(job['description'] or '')[:3000]}"
        )
        raw = provider.complete(SYSTEM_PROMPT, prompt, LETTER_SCHEMA)
        letter = raw.get("letter") if isinstance(raw, dict) else None
        if isinstance(letter, str) and letter.strip():
            db.record_event(
                conn, "ai.ok", json.dumps({"provider": provider.name, "letter_job": job["id"]})
            )
            return letter.strip(), True
        db.record_event(
            conn,
            "ai.error",
            json.dumps({"provider": provider.name, "error": "letter generation fell back"}),
        )
    return fallback, False


def save_letter(conn: sqlite3.Connection, job_id: int, letter: str) -> None:
    """Cache the letter in the application row's docs_json."""
    row = conn.execute("SELECT docs_json FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    docs = {}
    if row and row["docs_json"]:
        try:
            docs = json.loads(row["docs_json"])
        except json.JSONDecodeError:
            docs = {}
    docs["cover_letter"] = letter
    conn.execute(
        """INSERT INTO applications (job_id, state, docs_json, updated_at)
           VALUES (?, 'interested', ?, datetime('now'))
           ON CONFLICT (job_id) DO UPDATE
           SET docs_json = excluded.docs_json, updated_at = excluded.updated_at""",
        (job_id, json.dumps(docs)),
    )
    conn.commit()


def saved_letter(conn: sqlite3.Connection, job_id: int) -> str | None:
    row = conn.execute("SELECT docs_json FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    if not row or not row["docs_json"]:
        return None
    try:
        return json.loads(row["docs_json"]).get("cover_letter")
    except json.JSONDecodeError:
        return None
