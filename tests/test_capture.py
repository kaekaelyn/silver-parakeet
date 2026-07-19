import sqlite3
from pathlib import Path

import httpx
import pytest

from wingman import capture

FIXTURES = Path(__file__).parent / "fixtures"


def test_parse_jsonld_jobposting() -> None:
    html = (FIXTURES / "jobpage_jsonld.html").read_text()
    posting = capture.parse_job_page(html, "https://meridian.example/jobs/42?utm_source=x")
    assert posting.title == "Senior Platform Engineer"
    assert posting.company == "Meridian Systems"
    assert posting.location == "Portland, OR, US"
    assert posting.remote is True
    assert (posting.salary_min, posting.salary_max) == (150000, 185000)
    assert posting.posted_at is not None
    assert "logistics software" in posting.description
    assert "<p>" not in posting.description


def test_parse_plain_page_fallback() -> None:
    html = (FIXTURES / "jobpage_plain.html").read_text()
    posting = capture.parse_job_page(html, "https://rivertown.example/careers/data-eng")
    assert posting.title == "Data Engineer — Rivertown Analytics"
    assert posting.company == "Rivertown Analytics"
    assert "Spark and Airflow" in posting.description
    assert posting.raw["jsonld"] is False


def _mock_client(body: str, status: int = 200) -> httpx.Client:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(status, text=body)

    return httpx.Client(transport=httpx.MockTransport(handler))


def test_capture_url_creates_scored_job(conn: sqlite3.Connection) -> None:
    html = (FIXTURES / "jobpage_jsonld.html").read_text()
    job_id = capture.capture_url(
        conn, "https://meridian.example/jobs/42", client=_mock_client(html)
    )
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert job["title"] == "Senior Platform Engineer"
    assert job["source_id"] is not None
    score = conn.execute("SELECT score FROM scores WHERE job_id = ?", (job_id,)).fetchone()
    assert score is not None
    events = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "capture.ok" in events


def test_capture_same_url_twice_returns_existing(conn: sqlite3.Connection) -> None:
    html = (FIXTURES / "jobpage_jsonld.html").read_text()
    first = capture.capture_url(conn, "https://meridian.example/jobs/42", client=_mock_client(html))
    second = capture.capture_url(
        conn, "https://meridian.example/jobs/42?utm_source=share", client=_mock_client(html)
    )
    assert first == second
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 1


def test_capture_http_error_raises(conn: sqlite3.Connection) -> None:
    with pytest.raises(httpx.HTTPStatusError):
        capture.capture_url(
            conn, "https://gone.example/job", client=_mock_client("nope", status=404)
        )


def test_capture_source_is_never_scheduled(conn: sqlite3.Connection) -> None:
    capture.ensure_capture_source(conn)
    row = conn.execute("SELECT enabled FROM sources WHERE kind = 'capture'").fetchone()
    assert row["enabled"] == 0


def test_salary_min_zero_preserved() -> None:
    from wingman.capture import _salary_from

    assert _salary_from({"baseSalary": {"value": {"minValue": 0, "maxValue": 500}}}) == (0, 500)


def test_capture_rejects_oversized_page(conn: sqlite3.Connection) -> None:
    big = "x" * (capture.MAX_PAGE_BYTES + 1)
    with pytest.raises(ValueError, match="too large"):
        capture.capture_url(conn, "https://big.example/j", client=_mock_client(big))
    assert conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"] == 0
