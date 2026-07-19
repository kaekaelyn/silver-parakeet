import sqlite3
from pathlib import Path

import pytest

from wingman import db

EXPECTED_TABLES = {
    "sources",
    "jobs",
    "scores",
    "criteria",
    "profile",
    "documents",
    "answers",
    "applications",
    "reminders",
    "events",
    "schema_migrations",
}


def test_migrate_creates_schema(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "test.db")
    applied = db.migrate(conn)
    assert applied == ["001_initial.sql"]
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert EXPECTED_TABLES <= tables
    conn.close()


def test_migrate_is_idempotent(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "test.db")
    assert db.migrate(conn) == ["001_initial.sql"]
    assert db.migrate(conn) == []
    conn.close()


def test_wal_mode_enabled(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "test.db")
    assert conn.execute("PRAGMA journal_mode").fetchone()[0] == "wal"
    conn.close()


def test_migrations_apply_in_filename_order(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    (migrations_dir / "002_second.sql").write_text("CREATE TABLE b (id INTEGER);")
    (migrations_dir / "001_first.sql").write_text("CREATE TABLE a (id INTEGER);")
    conn = db.connect(tmp_path / "test.db")
    assert db.migrate(conn, migrations_dir) == ["001_first.sql", "002_second.sql"]
    conn.close()


def test_failed_migration_is_rolled_back_and_retryable(tmp_path: Path) -> None:
    migrations_dir = tmp_path / "migrations"
    migrations_dir.mkdir()
    bad = migrations_dir / "001_bad.sql"
    bad.write_text("CREATE TABLE a (id INTEGER);\nCREATE TABLE a (id INTEGER);")
    conn = db.connect(tmp_path / "test.db")
    with pytest.raises(sqlite3.OperationalError):
        db.migrate(conn, migrations_dir)
    tables = {
        row["name"] for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
    }
    assert "a" not in tables, "partial migration must not persist"
    assert conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"] == 0
    bad.write_text("CREATE TABLE a (id INTEGER);")
    assert db.migrate(conn, migrations_dir) == ["001_bad.sql"]
    conn.close()


def test_missing_migrations_dir_raises(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "test.db")
    with pytest.raises(FileNotFoundError):
        db.migrate(conn, tmp_path / "nonexistent")
    conn.close()


def test_session_closes_connection(tmp_path: Path) -> None:
    with db.session(tmp_path / "test.db") as conn:
        conn.execute("SELECT 1")
    with pytest.raises(sqlite3.ProgrammingError):
        conn.execute("SELECT 1")


def test_record_event(tmp_path: Path) -> None:
    conn = db.connect(tmp_path / "test.db")
    db.migrate(conn)
    db.record_event(conn, "test.event", '{"n": 1}')
    row = conn.execute("SELECT kind, payload_json, ts FROM events").fetchone()
    assert row["kind"] == "test.event"
    assert row["payload_json"] == '{"n": 1}'
    assert row["ts"]
    conn.close()
