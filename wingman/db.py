"""SQLite connection helpers and the SQL-file migration runner.

Migrations are numbered .sql files in migrations/, applied in filename
order exactly once each; applied filenames are recorded in
schema_migrations. Old migration files must never be edited.
"""

import logging
import sqlite3
from pathlib import Path

logger = logging.getLogger(__name__)

MIGRATIONS_DIR = Path(__file__).resolve().parent.parent / "migrations"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


def migrate(conn: sqlite3.Connection, migrations_dir: Path = MIGRATIONS_DIR) -> list[str]:
    """Apply pending migrations in order; return the filenames applied."""
    conn.execute(
        """CREATE TABLE IF NOT EXISTS schema_migrations (
               id TEXT PRIMARY KEY,
               applied_at TEXT NOT NULL DEFAULT (datetime('now'))
           )"""
    )
    applied = {row["id"] for row in conn.execute("SELECT id FROM schema_migrations")}
    newly_applied: list[str] = []
    for sql_file in sorted(migrations_dir.glob("*.sql")):
        if sql_file.name in applied:
            continue
        logger.info("applying migration %s", sql_file.name)
        conn.executescript(sql_file.read_text())
        conn.execute("INSERT INTO schema_migrations (id) VALUES (?)", (sql_file.name,))
        conn.commit()
        newly_applied.append(sql_file.name)
    return newly_applied


def record_event(conn: sqlite3.Connection, kind: str, payload_json: str | None = None) -> None:
    conn.execute("INSERT INTO events (kind, payload_json) VALUES (?, ?)", (kind, payload_json))
    conn.commit()
