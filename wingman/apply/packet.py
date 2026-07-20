"""The fill packet: everything a filler may put into a form.

Built from the vault (contact, default resume, canned answers) plus the
job's cover letter. Contact details also become derived canned answers so
custom questions like "LinkedIn profile" fill from one source of truth.
"""

import sqlite3
from dataclasses import dataclass, field
from pathlib import Path

from wingman import letters, vault


@dataclass
class FillPacket:
    contact: dict[str, str]
    resume_path: Path | None
    resume_name: str | None
    cover_letter: str
    answers: list[dict] = field(default_factory=list)


def split_name(full_name: str) -> tuple[str, str]:
    parts = full_name.strip().split()
    if not parts:
        return "", ""
    if len(parts) == 1:
        return parts[0], ""
    return parts[0], " ".join(parts[1:])


# (pattern, contact key): each non-empty contact value becomes a canned
# answer so the generic question walker can fill "GitHub profile" etc.
_DERIVED_PATTERNS = (
    ("linkedin", "linkedin"),
    ("linkedin profile", "linkedin"),
    ("github", "github"),
    ("github profile", "github"),
    ("website", "website"),
    ("portfolio", "website"),
    ("personal site", "website"),
    ("phone", "phone"),
    ("phone number", "phone"),
    ("email", "email"),
    ("email address", "email"),
    ("location", "location"),
    ("city", "location"),
    ("full name", "name"),
    ("your name", "name"),
)


def build_packet(conn: sqlite3.Connection, job: sqlite3.Row) -> FillPacket:
    profile = vault.get_profile(conn)
    contact = {
        key.removeprefix("contact."): profile.get(key, "").strip()
        for key, _label in vault.CONTACT_FIELDS
    }
    resume = conn.execute(
        "SELECT * FROM documents WHERE kind = 'resume' AND is_default = 1 LIMIT 1"
    ).fetchone()
    resume_path = Path(resume["path"]) if resume else None
    if resume_path is not None and not resume_path.is_file():
        resume_path = None
    letter = letters.saved_letter(conn, job["id"])
    if not letter:
        letter, _used_ai = letters.generate_cover_letter(conn, job)
        letters.save_letter(conn, job["id"], letter)

    answers: list[dict] = [
        {"question_pattern": pattern, "answer": contact[key], "kind": "contact"}
        for pattern, key in _DERIVED_PATTERNS
        if contact.get(key)
    ]
    answers.extend(
        {"question_pattern": row["question_pattern"], "answer": row["answer"], "kind": row["kind"]}
        for row in vault.list_answers(conn)
    )
    return FillPacket(
        contact=contact,
        resume_path=resume_path,
        resume_name=resume["name"] if resume else None,
        cover_letter=letter,
        answers=answers,
    )
