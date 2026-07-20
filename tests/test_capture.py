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


def test_capture_detects_embedded_ats(conn: sqlite3.Connection) -> None:
    """A company page embedding its ATS board gets ats_kind from the HTML."""
    html = (
        (FIXTURES / "jobpage_jsonld.html")
        .read_text()
        .replace(
            "</body>",
            '<script src="https://boards.greenhouse.io/embed/job_board/js?for=meridian"></script></body>',
        )
    )
    job_id = capture.capture_url(
        conn, "https://meridian.example/jobs/43", client=_mock_client(html)
    )
    row = conn.execute("SELECT ats_kind FROM jobs WHERE id = ?", (job_id,)).fetchone()
    assert row["ats_kind"] == "greenhouse"


# --- M6: PWA share-target lands on the capture page ---


def test_share_target_url_extraction() -> None:
    from wingman.routes.capture import shared_url

    assert shared_url("https://a.example/j/1", "", "") == "https://a.example/j/1"
    # Most Android apps put the link inside the shared text.
    assert (
        shared_url("", "Check out this job! https://boards.example/j/2.", "")
        == "https://boards.example/j/2"
    )
    assert shared_url("", "", "https://t.example/3") == "https://t.example/3"
    assert shared_url("Engineer role", "no link here", "") == ""


def test_capture_get_prefills_from_share(client) -> None:
    page = client.get("/capture", params={"text": "look: https://jobs.example/role/9"})
    assert page.status_code == 200
    assert 'value="https://jobs.example/role/9"' in page.text


def test_pwa_manifest_and_service_worker_served(client) -> None:
    manifest = client.get("/static/manifest.webmanifest")
    assert manifest.status_code == 200
    import json as _json

    data = _json.loads(manifest.text)
    assert data["share_target"]["action"] == "/capture"
    assert data["share_target"]["method"] == "GET"
    assert {icon["sizes"] for icon in data["icons"]} == {"192x192", "512x512"}
    for icon in data["icons"]:
        assert client.get(icon["src"]).status_code == 200

    sw = client.get("/sw.js")
    assert sw.status_code == 200
    assert "javascript" in sw.headers["content-type"]

    home = client.get("/").text
    assert "/static/manifest.webmanifest" in home
    assert "serviceWorker" in home
