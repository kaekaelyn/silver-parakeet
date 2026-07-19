"""SQLite connection helpers and the SQL-file migration runner.

Migrations are numbered .sql files in migrations/, applied in filename
order exactly once each; applied filenames are recorded in
schema_migrations. Old migration files must never be edited. Each
migration is applied atomically (the runner wraps the script in a
transaction), so migration files must not contain their own
BEGIN/COMMIT statements.
"""

import logging
import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

logger = logging.getLogger(__name__)

_PACKAGE_DIR = Path(__file__).resolve().parent


def find_migrations_dir() -> Path:
    """Locate migrations/ next to the package (wheel) or at the repo root."""
    candidates = (_PACKAGE_DIR / "migrations", _PACKAGE_DIR.parent / "migrations")
    for candidate in candidates:
        if candidate.is_dir():
            return candidate
    raise FileNotFoundError(
        "migrations directory not found; looked in: " + ", ".join(str(c) for c in candidates)
    )


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    conn = sqlite3.connect(db_path)
    conn.row_factory = sqlite3.Row
    conn.execute("PRAGMA journal_mode=WAL")
    conn.execute("PRAGMA foreign_keys=ON")
    return conn


@contextmanager
def session(db_path: Path) -> Iterator[sqlite3.Connection]:
    conn = connect(db_path)
    try:
        yield conn
    finally:
        conn.close()


def migrate(conn: sqlite3.Connection, migrations_dir: Path | None = None) -> list[str]:
    """Apply pending migrations in order; return the filenames applied.

    Each migration runs atomically: on failure nothing from that file is
    committed and it is not recorded, so a corrected file can be re-applied.
    """
    if migrations_dir is None:
        migrations_dir = find_migrations_dir()
    elif not migrations_dir.is_dir():
        raise FileNotFoundError(f"migrations directory not found: {migrations_dir}")
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
        try:
            conn.executescript("BEGIN;\n" + sql_file.read_text())
            conn.execute("INSERT INTO schema_migrations (id) VALUES (?)", (sql_file.name,))
            conn.commit()
        except Exception:
            conn.rollback()
            raise
        newly_applied.append(sql_file.name)
    return newly_applied


def record_event(conn: sqlite3.Connection, kind: str, payload_json: str | None = None) -> None:
    conn.execute("INSERT INTO events (kind, payload_json) VALUES (?, ?)", (kind, payload_json))
    conn.commit()
