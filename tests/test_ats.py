import sqlite3

from wingman.apply import ats


def test_detect_ats_from_urls() -> None:
    assert ats.detect_ats("https://boards.greenhouse.io/hooli/jobs/123") == "greenhouse"
    assert ats.detect_ats("https://job-boards.greenhouse.io/hooli/jobs/123") == "greenhouse"
    assert ats.detect_ats("https://jobs.lever.co/piedpiper/abc-def") == "lever"
    assert ats.detect_ats("https://jobs.ashbyhq.com/acme/123") == "ashby"
    assert ats.detect_ats("https://apply.workable.com/acme/j/123/") == "workable"
    assert ats.detect_ats("https://example.com/careers/123") is None
    # Similar-looking but different domains must not match.
    assert ats.detect_ats("https://notgreenhouse.io.evil.com/x") is None
    assert ats.detect_ats("https://mygreenhouse.iodine.com/x") is None


def test_detect_ats_in_page() -> None:
    html = '<a href="https://boards.greenhouse.io/hooli/jobs/1">Apply</a>'
    assert ats.detect_ats_in_page(html) == "greenhouse"
    assert ats.detect_ats_in_page("<p>nothing here</p>") is None


def test_apply_url() -> None:
    assert (
        ats.apply_url("lever", "https://jobs.lever.co/piedpiper/abc")
        == "https://jobs.lever.co/piedpiper/abc/apply"
    )
    assert (
        ats.apply_url("lever", "https://jobs.lever.co/piedpiper/abc/apply")
        == "https://jobs.lever.co/piedpiper/abc/apply"
    )
    assert (
        ats.apply_url("greenhouse", "https://boards.greenhouse.io/hooli/jobs/1")
        == "https://boards.greenhouse.io/hooli/jobs/1"
    )


def test_ensure_ats_kind_caches(conn: sqlite3.Connection) -> None:
    conn.execute(
        "INSERT INTO jobs (title, url, dedupe_hash) VALUES ('A', 'https://jobs.lever.co/x/1', 'h')"
    )
    conn.commit()
    job = conn.execute("SELECT * FROM jobs").fetchone()
    assert job["ats_kind"] is None
    assert ats.ensure_ats_kind(conn, job) == "lever"
    assert conn.execute("SELECT ats_kind FROM jobs").fetchone()["ats_kind"] == "lever"


def test_ingest_sets_ats_kind(conn: sqlite3.Connection) -> None:
    from wingman import ingest
    from wingman.sources import RawPosting

    source_id = conn.execute(
        "INSERT INTO sources (kind, name, config_json) VALUES ('rss', 'test', '{}')"
    ).lastrowid
    conn.commit()
    ingest.store_postings(
        conn,
        source_id,
        [RawPosting(url="https://boards.greenhouse.io/hooli/jobs/9", title="Eng")],
    )
    assert conn.execute("SELECT ats_kind FROM jobs").fetchone()["ats_kind"] == "greenhouse"
