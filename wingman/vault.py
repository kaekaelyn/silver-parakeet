"""Profile vault: contact details, documents, canned answers.

Everything Andy-specific is entered through the app; nothing requires
editing files by hand. PII lives only here and in the documents dir.
"""

import json
import logging
import re
import sqlite3
import time
from pathlib import Path

from wingman import db

logger = logging.getLogger(__name__)

CONTACT_FIELDS = (
    ("contact.name", "Full name"),
    ("contact.email", "Email"),
    ("contact.phone", "Phone"),
    ("contact.location", "Location"),
    ("contact.github", "GitHub URL"),
    ("contact.website", "Website"),
    ("contact.linkedin", "LinkedIn URL"),
)
COVER_LETTER_KEY = "cover_letter_template"
DOCUMENT_KINDS = ("resume", "cover_letter")
MAX_DOCUMENT_BYTES = 20 * 1024 * 1024

# Cover-letter template placeholder contract (shown in the vault UI and
# honored by M4's letter generation): {company} = job's company,
# {title} = job's title, {name} = contact.name from this vault.
TEMPLATE_PLACEHOLDERS = ("company", "title", "name")

# Seeded once (only into an empty answers table): PLAN §5 promises EEO
# questions get an explicit decline-to-answer default.
DEFAULT_ANSWERS = (
    ("gender", "Decline to self-identify", "decline"),
    ("race", "Decline to self-identify", "decline"),
    ("ethnicity", "Decline to self-identify", "decline"),
    ("veteran", "Decline to self-identify", "decline"),
    ("disability", "Decline to self-identify", "decline"),
)


def ensure_default_answers(conn: sqlite3.Connection) -> None:
    if conn.execute("SELECT count(*) AS n FROM answers").fetchone()["n"] == 0:
        conn.executemany(
            "INSERT INTO answers (question_pattern, answer, kind) VALUES (?, ?, ?)",
            DEFAULT_ANSWERS,
        )
        conn.commit()


def get_profile(conn: sqlite3.Connection) -> dict[str, str]:
    return {
        row["key"]: row["value"] or "" for row in conn.execute("SELECT key, value FROM profile")
    }


def set_profile_values(conn: sqlite3.Connection, values: dict[str, str]) -> None:
    for key, value in values.items():
        conn.execute(
            """INSERT INTO profile (key, value) VALUES (?, ?)
               ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
            (key, value.strip()),
        )
    conn.commit()
    db.record_event(conn, "vault.updated", json.dumps({"keys": sorted(values)}))


def _safe_filename(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name).strip("-.") or "document"
    return cleaned[:80]


def add_document(
    conn: sqlite3.Connection,
    documents_dir: Path,
    kind: str,
    name: str,
    filename: str,
    content: bytes,
) -> int:
    if kind not in DOCUMENT_KINDS:
        raise ValueError(f"unknown document kind {kind!r}")
    if len(content) > MAX_DOCUMENT_BYTES:
        raise ValueError("document is too large (20MB max)")
    documents_dir.mkdir(parents=True, exist_ok=True)
    base = f"{int(time.time())}-{_safe_filename(filename)}"
    path = documents_dir / base
    suffix = 1
    while path.exists():  # same name in the same second must not overwrite
        path = documents_dir / f"{base}.{suffix}"
        suffix += 1
    path.write_bytes(content)
    is_first = (
        conn.execute("SELECT count(*) AS n FROM documents WHERE kind = ?", (kind,)).fetchone()["n"]
        == 0
    )
    cursor = conn.execute(
        "INSERT INTO documents (kind, name, path, is_default) VALUES (?, ?, ?, ?)",
        (kind, name.strip() or filename, str(path), int(is_first)),
    )
    conn.commit()
    # Kind only: document names can carry PII, which stays in the vault.
    db.record_event(conn, "document.added", json.dumps({"kind": kind}))
    return cursor.lastrowid


def set_default_document(conn: sqlite3.Connection, document_id: int) -> None:
    row = conn.execute("SELECT kind FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        return
    conn.execute("UPDATE documents SET is_default = 0 WHERE kind = ?", (row["kind"],))
    conn.execute("UPDATE documents SET is_default = 1 WHERE id = ?", (document_id,))
    conn.commit()


def delete_document(conn: sqlite3.Connection, document_id: int) -> None:
    row = conn.execute("SELECT * FROM documents WHERE id = ?", (document_id,)).fetchone()
    if row is None:
        return
    # One transaction: delete + default promotion commit together so the
    # DB can never be left with rows of a kind but no default.
    conn.execute("DELETE FROM documents WHERE id = ?", (document_id,))
    if row["is_default"]:
        newest = conn.execute(
            "SELECT id FROM documents WHERE kind = ? ORDER BY id DESC LIMIT 1", (row["kind"],)
        ).fetchone()
        if newest:
            conn.execute("UPDATE documents SET is_default = 1 WHERE id = ?", (newest["id"],))
    conn.commit()
    db.record_event(conn, "document.deleted", json.dumps({"kind": row["kind"]}))
    try:
        Path(row["path"]).unlink(missing_ok=True)
    except OSError:
        logger.warning("could not remove document file %s", row["path"])


def list_documents(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM documents ORDER BY kind, id DESC").fetchall()


def add_answer(conn: sqlite3.Connection, question_pattern: str, answer: str, kind: str) -> None:
    conn.execute(
        "INSERT INTO answers (question_pattern, answer, kind) VALUES (?, ?, ?)",
        (question_pattern.strip(), answer.strip(), kind.strip() or "text"),
    )
    conn.commit()
    db.record_event(conn, "answer.added", json.dumps({"kind": kind.strip() or "text"}))


def delete_answer(conn: sqlite3.Connection, answer_id: int) -> None:
    conn.execute("DELETE FROM answers WHERE id = ?", (answer_id,))
    conn.commit()
    db.record_event(conn, "answer.deleted", json.dumps({"id": answer_id}))


def list_answers(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return conn.execute("SELECT * FROM answers ORDER BY id").fetchall()
