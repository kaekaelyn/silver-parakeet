from __future__ import annotations

import sqlite3
from pathlib import Path

MIGRATIONS_DIR = Path(__file__).resolve().parents[3] / "migrations"


def connect(db_path: Path) -> sqlite3.Connection:
    db_path.parent.mkdir(parents=True, exist_ok=True)
    connection = sqlite3.connect(db_path)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA journal_mode=WAL")
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def migrate(db_path: Path) -> None:
    with connect(db_path) as connection:
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations "
            "(version TEXT PRIMARY KEY, applied_at TEXT NOT NULL DEFAULT CURRENT_TIMESTAMP)"
        )
        applied = {
            row["version"]
            for row in connection.execute("SELECT version FROM schema_migrations")
        }
        for migration in sorted(MIGRATIONS_DIR.glob("*.sql")):
            version = migration.name
            if version in applied:
                continue
            connection.executescript(migration.read_text())
            connection.execute(
                "INSERT INTO schema_migrations(version) VALUES (?)",
                (version,),
            )
