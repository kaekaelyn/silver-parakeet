"""Apply engine: guardrails, recording, and end-to-end flows on fixtures."""

import json
import sqlite3
from pathlib import Path

import pytest

from tests.conftest import FIXTURES
from wingman import db, vault
from wingman.apply import engine
from wingman.config import Settings


@pytest.fixture(autouse=True)
def _clear_sessions():
    engine._SESSIONS.clear()
    yield
    engine._SESSIONS.clear()


def _seed_env(settings: Settings) -> sqlite3.Connection:
    conn = db.connect(settings.db_path)
    db.migrate(conn)
    vault.ensure_default_answers(conn)
    vault.set_profile_values(
        conn,
        {
            "contact.name": "Andy Dwyer",
            "contact.email": "andy@example.com",
            "contact.phone": "555-0100",
            "contact.linkedin": "https://linkedin.com/in/andy",
            "contact.github": "https://github.com/andy",
            "contact.website": "https://andy.example",
        },
    )
    settings.documents_dir.mkdir(parents=True, exist_ok=True)
    resume = settings.documents_dir / "resume.pdf"
    resume.write_bytes(b"%PDF-1.4 fake resume")
    conn.execute(
        "INSERT INTO documents (kind, name, path, is_default) VALUES ('resume', 'CV', ?, 1)",
        (str(resume),),
    )
    for pattern, answer in (
        ("salary expectations", "$140,000"),
        ("visa sponsorship", "No"),
        ("years of python experience", "8"),
        ("authorized to work", "Yes"),
    ):
        conn.execute(
            "INSERT INTO answers (question_pattern, answer, kind) VALUES (?, ?, 'text')",
            (pattern, answer),
        )
    conn.commit()
    return conn


def _add_hamster_answer(conn: sqlite3.Connection) -> None:
    conn.execute(
        """INSERT INTO answers (question_pattern, answer, kind)
           VALUES ('hamster herding', 'Extensive', 'text')"""
    )
    conn.commit()


def _seed_job(
    conn: sqlite3.Connection,
    fixture: str = "greenhouse_form.html",
    company: str = "Hooli",
    kind: str = "greenhouse",
    query: str = "",
) -> int:
    url = (FIXTURES / fixture).resolve().as_uri() + query
    cursor = conn.execute(
        """INSERT INTO jobs (title, url, dedupe_hash, company, ats_kind, description)
           VALUES ('Engineer', ?, ?, ?, ?, 'desc')""",
        (url, f"h-{fixture}-{query}", company, kind),
    )
    conn.commit()
    return cursor.lastrowid


def _enable_auto(conn: sqlite3.Connection, cap: int = 5, cooldown: int = 7) -> None:
    engine.set_apply_settings(conn, {"greenhouse": True, "lever": True}, cap, cooldown)


# --- settings and guardrails (no browser needed) ---


def test_apply_settings_roundtrip(conn: sqlite3.Connection) -> None:
    defaults = engine.get_apply_settings(conn)
    assert defaults == {
        "auto": {"greenhouse": False, "lever": False},
        "daily_cap": engine.DEFAULT_DAILY_CAP,
        "cooldown_days": engine.DEFAULT_COOLDOWN_DAYS,
    }
    engine.set_apply_settings(conn, {"greenhouse": True}, daily_cap=3, cooldown_days=10)
    saved = engine.get_apply_settings(conn)
    assert saved["auto"] == {"greenhouse": True, "lever": False}
    assert saved["daily_cap"] == 3 and saved["cooldown_days"] == 10


def test_auto_check_toggle_off(conn: sqlite3.Connection) -> None:
    job_id = _seed_job(conn)
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    ok, reason = engine.auto_check(conn, job, "greenhouse")
    assert not ok and "switched off" in reason


def test_auto_check_unknown_ats(conn: sqlite3.Connection) -> None:
    job_id = _seed_job(conn, kind="ashby")
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    ok, reason = engine.auto_check(conn, job, "ashby")
    assert not ok and "no filler" in reason


def test_auto_check_daily_cap(conn: sqlite3.Connection) -> None:
    _enable_auto(conn, cap=1)
    other = _seed_job(conn, company="OtherCo", query="?other=1")
    conn.execute(
        """INSERT INTO applications (job_id, state, applied_at, method)
           VALUES (?, 'applied', datetime('now'), 'wingman-auto')""",
        (other,),
    )
    conn.commit()
    job_id = _seed_job(conn)
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    ok, reason = engine.auto_check(conn, job, "greenhouse")
    assert not ok and "cap" in reason


def test_auto_check_company_cooldown(conn: sqlite3.Connection) -> None:
    _enable_auto(conn, cooldown=7)
    earlier = _seed_job(conn, company="Hooli", query="?earlier=1")
    conn.execute(
        """INSERT INTO applications (job_id, state, applied_at, method)
           VALUES (?, 'applied', datetime('now', '-2 days'), 'manual')""",
        (earlier,),
    )
    conn.commit()
    job_id = _seed_job(conn, company="hooli")  # case-insensitive
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    ok, reason = engine.auto_check(conn, job, "greenhouse")
    assert not ok and "cooldown" in reason
    # Outside the window it's allowed again.
    conn.execute("UPDATE applications SET applied_at = datetime('now', '-30 days')")
    conn.commit()
    ok, _reason = engine.auto_check(conn, job, "greenhouse")
    assert ok


def test_auto_check_already_applied(conn: sqlite3.Connection) -> None:
    _enable_auto(conn)
    job_id = _seed_job(conn)
    conn.execute(
        """INSERT INTO applications (job_id, state, applied_at, method)
           VALUES (?, 'applied', datetime('now'), 'manual')""",
        (job_id,),
    )
    conn.commit()
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    ok, reason = engine.auto_check(conn, job, "greenhouse")
    assert not ok and "already applied" in reason


# --- end-to-end flows (headless browser on fixture forms) ---
#
# The flows run in a worker thread, exactly as production routes invoke
# them (and because the session `browser` fixture owns the main thread's
# sync-playwright loop).


def _run_in_thread(target, *args, **kwargs) -> None:
    import threading

    thread = threading.Thread(target=target, args=args, kwargs=kwargs)
    thread.start()
    thread.join(timeout=120)
    assert not thread.is_alive(), "apply flow did not finish"


def test_auto_apply_submits_records_screenshots(settings: Settings, browser) -> None:
    conn = _seed_env(settings)
    _add_hamster_answer(conn)
    _enable_auto(conn, cooldown=0)
    job_id = _seed_job(conn)

    _run_in_thread(engine._auto_run, settings, job_id, headless=True)

    status = engine.status_for(job_id)
    assert status is not None and status.state == "submitted", status
    app = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    assert app["state"] == "applied"
    assert app["method"] == "wingman-auto"
    assert app["applied_at"] is not None
    docs = json.loads(app["docs_json"])
    assert docs["confirmed"] is True
    assert docs["cover_letter"]
    assert docs["resume_path"].endswith("resume.pdf")
    assert docs["screenshot"] and Path(docs["screenshot"]).is_file()
    reminder = conn.execute("SELECT 1 FROM reminders WHERE job_id = ? AND done = 0", (job_id,))
    assert reminder.fetchone() is not None


def test_auto_apply_never_submits_with_unmatched_required(settings: Settings, browser) -> None:
    conn = _seed_env(settings)  # no hamster answer: required question unanswered
    _enable_auto(conn, cooldown=0)
    job_id = _seed_job(conn)

    _run_in_thread(engine._auto_run, settings, job_id, headless=True)

    status = engine.status_for(job_id)
    assert status is not None and status.state == "needs_review"
    assert "hamster" in status.detail
    assert conn.execute("SELECT count(*) AS n FROM applications").fetchone()["n"] == 1
    # The only row is the letter cache, never an applied record.
    app = conn.execute("SELECT * FROM applications").fetchone()
    assert app["applied_at"] is None
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "apply.auto_fallback" in kinds and "apply.submitted" not in kinds


def test_auto_apply_never_submits_on_captcha(settings: Settings, browser) -> None:
    conn = _seed_env(settings)
    _enable_auto(conn, cooldown=0)
    job_id = _seed_job(conn, fixture="greenhouse_captcha.html")

    _run_in_thread(engine._auto_run, settings, job_id, headless=True)

    status = engine.status_for(job_id)
    assert status is not None and status.state == "needs_review"
    assert "CAPTCHA" in status.detail
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM applications WHERE applied_at IS NOT NULL"
        ).fetchone()["n"]
        == 0
    )


def test_try_begin_claims_job_atomically() -> None:
    """Concurrent Apply clicks: exactly one session may claim a job."""
    import threading

    starts = 0
    lock = threading.Lock()
    barrier = threading.Barrier(8)

    def click() -> None:
        nonlocal starts
        barrier.wait()
        if engine._try_begin(7, "assisted"):
            with lock:
                starts += 1

    threads = [threading.Thread(target=click) for _ in range(8)]
    for thread in threads:
        thread.start()
    for thread in threads:
        thread.join()
    assert starts == 1

    # A finished session frees the job for a new one.
    engine._set_status(7, "assisted", "error", "boom")
    assert engine._try_begin(7, "auto") is True


def test_auto_apply_blocked_before_browser_launch(settings: Settings) -> None:
    """Guardrails run pre-launch: toggle off means no browser, just 'blocked'."""
    conn = _seed_env(settings)
    job_id = _seed_job(conn)  # auto toggles default off

    _run_in_thread(engine._auto_run, settings, job_id, headless=True)

    status = engine.status_for(job_id)
    assert status is not None and status.state == "blocked"
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "apply.auto_blocked" in kinds and "apply.filled" not in kinds


def test_assisted_records_when_human_submits(settings: Settings, browser) -> None:
    conn = _seed_env(settings)
    _add_hamster_answer(conn)
    job_id = _seed_job(conn, query="?auto=1")  # fixture clicks Submit like a human

    _run_in_thread(
        engine._assisted_run, settings, job_id, headless=True, review_timeout_s=20, poll_s=0.2
    )

    status = engine.status_for(job_id)
    assert status is not None and status.state == "submitted", status
    app = conn.execute("SELECT * FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    assert app["method"] == "wingman-assisted"
    assert json.loads(app["docs_json"])["screenshot"] is None


def test_assisted_review_timeout_abandons(settings: Settings, browser) -> None:
    conn = _seed_env(settings)
    job_id = _seed_job(conn)  # nobody clicks submit

    _run_in_thread(
        engine._assisted_run, settings, job_id, headless=True, review_timeout_s=1, poll_s=0.2
    )

    status = engine.status_for(job_id)
    assert status is not None and status.state == "abandoned"
    assert (
        conn.execute(
            "SELECT count(*) AS n FROM applications WHERE applied_at IS NOT NULL"
        ).fetchone()["n"]
        == 0
    )
    kinds = [r["kind"] for r in conn.execute("SELECT kind FROM events")]
    assert "apply.abandoned" in kinds
