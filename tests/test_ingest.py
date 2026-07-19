import json
import sqlite3
from pathlib import Path
from typing import Any

import httpx
import pytest

from wingman import db, ingest
from wingman.sources import ADAPTERS, RawPosting, SourceAdapter, remoteok, remotive

FIXTURES = Path(__file__).parent / "fixtures"


@pytest.fixture
def conn(tmp_path: Path) -> sqlite3.Connection:
    connection = db.connect(tmp_path / "test.db")
    db.migrate(connection)
    yield connection
    connection.close()


def _add_source(conn: sqlite3.Connection, kind: str, name: str, config: dict | None = None) -> int:
    cursor = conn.execute(
        "INSERT INTO sources (kind, name, config_json) VALUES (?, ?, ?)",
        (kind, name, json.dumps(config or {})),
    )
    conn.commit()
    return cursor.lastrowid


def test_canonical_url() -> None:
    assert (
        ingest.canonical_url("https://Example.com/Jobs/123/?utm_source=x&utm_medium=y#top")
        == "https://example.com/Jobs/123"
    )
    assert (
        ingest.canonical_url("https://example.com/jobs?id=7&ref=feed")
        == "https://example.com/jobs?id=7"
    )
    assert ingest.canonical_url("https://example.com/") == "https://example.com/"


def test_fuzzy_hash_normalizes_variants() -> None:
    assert ingest.fuzzy_hash("Acme Inc.", "Senior Backend Engineer", "Worldwide") == (
        ingest.fuzzy_hash("acme", "Senior  Backend engineer!", "worldwide")
    )
    assert ingest.fuzzy_hash("Acme", "Backend Engineer", "Worldwide") != (
        ingest.fuzzy_hash("Acme", "Frontend Engineer", "Worldwide")
    )


def test_same_job_across_sources_is_deduped(conn: sqlite3.Connection) -> None:
    remotive_jobs = remotive.parse(json.loads((FIXTURES / "remotive.json").read_text()))
    remoteok_jobs = remoteok.parse(json.loads((FIXTURES / "remoteok.json").read_text()))
    source_a = _add_source(conn, "remotive", "Remotive")
    source_b = _add_source(conn, "remoteok", "RemoteOK")

    new_a, dup_a = ingest.store_postings(conn, source_a, remotive_jobs)
    new_b, dup_b = ingest.store_postings(conn, source_b, remoteok_jobs)

    assert (new_a, dup_a) == (3, 0)
    # Acme's Senior Backend Engineer appears on both boards with different URLs.
    assert (new_b, dup_b) == (1, 1)
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 4


def test_same_url_is_deduped(conn: sqlite3.Connection) -> None:
    source_id = _add_source(conn, "rss", "Feed")
    posting = RawPosting(url="https://example.com/job/1?utm_source=a", title="Engineer")
    again = RawPosting(url="https://example.com/job/1?utm_source=b", title="Engineer (Repost)")
    assert ingest.store_postings(conn, source_id, [posting]) == (1, 0)
    assert ingest.store_postings(conn, source_id, [again]) == (0, 1)


class _FakeSource(SourceAdapter):
    kind = "fake"
    default_name = "Fake"

    def __init__(self, postings: list[RawPosting]) -> None:
        self.postings = postings

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        return self.postings


class _BoomSource(SourceAdapter):
    kind = "boom"
    default_name = "Boom"

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        raise RuntimeError("upstream exploded")


def test_fetch_source_success_records_state(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    postings = [RawPosting(url="https://example.com/j/1", title="Engineer", company="X")]
    monkeypatch.setitem(ADAPTERS, "fake", _FakeSource(postings))
    source_id = _add_source(conn, "fake", "Fake board")

    result = ingest.fetch_source(conn, source_id)

    assert result == {"ok": True, "found": 1, "new": 1, "duplicates": 0}
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    assert row["last_fetch_at"] is not None
    assert row["last_error"] is None
    events = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "fetch.ok" in events


def test_failing_source_does_not_affect_others(
    conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch
) -> None:
    postings = [RawPosting(url="https://example.com/j/2", title="Engineer", company="Y")]
    monkeypatch.setitem(ADAPTERS, "boom", _BoomSource())
    monkeypatch.setitem(ADAPTERS, "fake", _FakeSource(postings))
    boom_id = _add_source(conn, "boom", "Broken board")
    fake_id = _add_source(conn, "fake", "Working board")

    results = ingest.fetch_all_enabled(conn)

    assert [r["ok"] for r in results] == [False, True]
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 1
    boom_row = conn.execute("SELECT * FROM sources WHERE id = ?", (boom_id,)).fetchone()
    assert "upstream exploded" in boom_row["last_error"]
    fake_row = conn.execute("SELECT * FROM sources WHERE id = ?", (fake_id,)).fetchone()
    assert fake_row["last_error"] is None
    events = [r["kind"] for r in conn.execute("SELECT kind FROM events ORDER BY id")]
    assert "fetch.error" in events and "fetch.ok" in events


def test_ensure_default_sources_is_idempotent(conn: sqlite3.Connection) -> None:
    ingest.ensure_default_sources(conn)
    first = conn.execute("SELECT count(*) AS n FROM sources").fetchone()["n"]
    ingest.ensure_default_sources(conn)
    assert conn.execute("SELECT count(*) AS n FROM sources").fetchone()["n"] == first
    assert first == 4
