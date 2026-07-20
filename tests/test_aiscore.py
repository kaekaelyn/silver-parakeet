import json
import sqlite3
from typing import Any

import pytest

from wingman import ai, aiscore, scoring


class _FakeProvider(ai.AIProvider):
    name = "fake"
    label = "Fake"
    binary = None

    def __init__(self, responses: list[dict[str, Any] | None]) -> None:
        self.responses = responses
        self.calls = 0

    def complete(self, system, prompt, json_schema=None):
        self.calls += 1
        return self.responses.pop(0) if self.responses else None


def _use_fake(conn: sqlite3.Connection, monkeypatch: pytest.MonkeyPatch, provider) -> None:
    monkeypatch.setitem(ai.PROVIDERS, "fake", provider)
    ai.set_provider_name(conn, "fake")


def _seed_job(conn: sqlite3.Connection, title: str, heuristic: int) -> int:
    cursor = conn.execute(
        "INSERT INTO jobs (title, url, dedupe_hash, description) VALUES (?, ?, ?, 'desc')",
        (title, f"https://x.example/{title}", f"h-{title}"),
    )
    job_id = cursor.lastrowid
    scoring.upsert_score(conn, job_id, heuristic, [], "Test")
    conn.commit()
    return job_id


GOOD = {"score": 91, "rationale": ["strong match"], "red_flags": ["reposted often"]}


def test_batch_scores_and_caches(conn: sqlite3.Connection, monkeypatch) -> None:
    job_id = _seed_job(conn, "A", 70)
    fake = _FakeProvider([dict(GOOD)])
    _use_fake(conn, monkeypatch, fake)

    assert aiscore.score_pending(conn) == {"scored": 1, "skipped": 0}
    stored = aiscore.ai_score_for(conn, job_id)
    assert stored["score"] == 91
    assert stored["red_flags"] == ["reposted often"]
    events = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "ai.ok" in events
    # Cached: a second batch makes no further calls.
    aiscore.score_pending(conn)
    assert fake.calls == 1


def test_provider_failure_stops_batch_with_one_event(conn: sqlite3.Connection, monkeypatch) -> None:
    _seed_job(conn, "A", 70)
    _seed_job(conn, "B", 60)
    _use_fake(conn, monkeypatch, _FakeProvider([None, dict(GOOD)]))

    result = aiscore.score_pending(conn)
    assert result["scored"] == 0
    errors = conn.execute("SELECT count(*) AS n FROM events WHERE kind = 'ai.error'").fetchone()
    assert errors["n"] == 1
    assert conn.execute("SELECT count(*) AS n FROM scores WHERE scorer='ai'").fetchone()["n"] == 0


def test_schema_violation_rejected(conn: sqlite3.Connection, monkeypatch) -> None:
    _seed_job(conn, "A", 70)
    _use_fake(conn, monkeypatch, _FakeProvider([{"score": 150, "rationale": [], "red_flags": []}]))
    assert aiscore.score_pending(conn)["scored"] == 0
    events = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "ai.error" in events


def test_none_provider_is_noop(conn: sqlite3.Connection) -> None:
    _seed_job(conn, "A", 70)
    assert aiscore.score_pending(conn) == {"scored": 0, "skipped": 0}


def test_pending_respects_threshold_and_hidden(conn: sqlite3.Connection) -> None:
    low = _seed_job(conn, "Low", 10)
    hidden = _seed_job(conn, "Hidden", 90)
    conn.execute("UPDATE jobs SET hidden = 1 WHERE id = ?", (hidden,))
    good = _seed_job(conn, "Good", 80)
    scoring.set_threshold(conn, 50)
    pending_ids = [row["id"] for row in aiscore.pending_jobs(conn)]
    assert good in pending_ids
    assert low not in pending_ids and hidden not in pending_ids


def test_pending_count_not_capped_by_batch_limit(conn: sqlite3.Connection) -> None:
    for i in range(aiscore.BATCH_LIMIT + 5):
        _seed_job(conn, f"J{i}", 70)
    assert len(aiscore.pending_jobs(conn)) == aiscore.BATCH_LIMIT
    assert aiscore.pending_count(conn) == aiscore.BATCH_LIMIT + 5


def test_overlong_rationale_trimmed_not_fatal(conn: sqlite3.Connection, monkeypatch) -> None:
    job_id = _seed_job(conn, "A", 70)
    five = {"score": 80, "rationale": [f"r{i}" for i in range(5)], "red_flags": []}
    _use_fake(conn, monkeypatch, _FakeProvider([five]))
    assert aiscore.score_pending(conn)["scored"] == 1
    assert aiscore.ai_score_for(conn, job_id)["rationale"] == ["r0", "r1", "r2"]


def test_concurrent_batch_skipped(conn: sqlite3.Connection, monkeypatch) -> None:
    _seed_job(conn, "A", 70)
    fake = _FakeProvider([dict(GOOD)])
    _use_fake(conn, monkeypatch, fake)
    with aiscore._batch_lock:
        assert aiscore.score_pending(conn) == {"scored": 0, "skipped": 0}
    assert fake.calls == 0
    assert aiscore.score_pending(conn)["scored"] == 1  # lock released: works again


def test_rationale_json_shape(conn: sqlite3.Connection, monkeypatch) -> None:
    job_id = _seed_job(conn, "A", 70)
    _use_fake(conn, monkeypatch, _FakeProvider([dict(GOOD)]))
    aiscore.score_pending(conn)
    raw = conn.execute(
        "SELECT rationale_json FROM scores WHERE job_id = ? AND scorer='ai'", (job_id,)
    ).fetchone()["rationale_json"]
    payload = json.loads(raw)
    assert payload["provider"] == "fake"
    assert payload["rationale"] == ["strong match"]
