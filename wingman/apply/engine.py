"""Apply sessions: assisted (headed, human submits) and auto (guarded).

Hard rules (CLAUDE.md): never auto-submit with unmatched required fields,
on a CAPTCHA, over the daily cap, or when the per-ATS toggle is off. The
guardrail check runs before a browser ever launches, and the fill report
is re-checked before the submit click.
"""

import json
import logging
import sqlite3
import threading
import time
from dataclasses import dataclass, field

from wingman import db, tracker
from wingman.apply import ats
from wingman.apply.packet import FillPacket, build_packet
from wingman.config import Settings

logger = logging.getLogger(__name__)

AUTO_TOGGLE_KEY = "apply.auto."  # + ats kind
DAILY_CAP_KEY = "apply.daily_cap"
COOLDOWN_KEY = "apply.cooldown_days"
DEFAULT_DAILY_CAP = 5
DEFAULT_COOLDOWN_DAYS = 7

REVIEW_TIMEOUT_S = 20 * 60
REVIEW_POLL_S = 2.0
CONFIRM_TIMEOUT_S = 30
PAGE_LOAD_TIMEOUT_MS = 30_000


@dataclass
class ApplyStatus:
    job_id: int
    mode: str  # 'assisted' | 'auto'
    state: str  # starting|filling|review|submitted|abandoned|error|blocked|needs_review|unconfirmed
    detail: str = ""
    updated_at: float = field(default_factory=time.time)

    @property
    def active(self) -> bool:
        return self.state in ("starting", "filling", "review")


_SESSIONS: dict[int, ApplyStatus] = {}
_sessions_lock = threading.Lock()
_auto_lock = threading.Lock()


def status_for(job_id: int) -> ApplyStatus | None:
    with _sessions_lock:
        return _SESSIONS.get(job_id)


def _set_status(job_id: int, mode: str, state: str, detail: str = "") -> None:
    with _sessions_lock:
        _SESSIONS[job_id] = ApplyStatus(job_id=job_id, mode=mode, state=state, detail=detail)


# --- settings (all editable in the UI; stored in the profile table) ---


def get_apply_settings(conn: sqlite3.Connection) -> dict:
    rows = dict(
        conn.execute(
            "SELECT key, value FROM profile WHERE key LIKE 'apply.%'",
        ).fetchall()
    )
    return {
        "auto": {kind: rows.get(AUTO_TOGGLE_KEY + kind) == "1" for kind in ats.SUPPORTED},
        "daily_cap": _int_or(rows.get(DAILY_CAP_KEY), DEFAULT_DAILY_CAP),
        "cooldown_days": _int_or(rows.get(COOLDOWN_KEY), DEFAULT_COOLDOWN_DAYS),
    }


def set_apply_settings(
    conn: sqlite3.Connection, auto: dict[str, bool], daily_cap: int, cooldown_days: int
) -> None:
    values = {AUTO_TOGGLE_KEY + kind: "1" if auto.get(kind) else "0" for kind in ats.SUPPORTED}
    values[DAILY_CAP_KEY] = str(max(0, daily_cap))
    values[COOLDOWN_KEY] = str(max(0, cooldown_days))
    for key, value in values.items():
        conn.execute(
            """INSERT INTO profile (key, value) VALUES (?, ?)
               ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
            (key, value),
        )
    conn.commit()
    db.record_event(conn, "apply.settings", json.dumps({"auto": auto, "cap": daily_cap}))


def _int_or(raw: str | None, default: int) -> int:
    try:
        return int(raw) if raw is not None else default
    except ValueError:
        return default


# --- guardrails ---


def auto_submits_today(conn: sqlite3.Connection) -> int:
    return conn.execute(
        """SELECT count(*) AS n FROM applications
           WHERE method = 'wingman-auto' AND applied_at >= date('now')"""
    ).fetchone()["n"]


def company_cooldown_active(conn: sqlite3.Connection, company: str, days: int) -> bool:
    if not company.strip() or days <= 0:
        return False
    row = conn.execute(
        """SELECT 1 FROM applications a JOIN jobs j ON j.id = a.job_id
           WHERE j.company = ? COLLATE NOCASE
             AND a.applied_at >= datetime('now', ?)""",
        (company.strip(), f"-{days} days"),
    ).fetchone()
    return row is not None


def auto_check(conn: sqlite3.Connection, job: sqlite3.Row, kind: str | None) -> tuple[bool, str]:
    """All pre-launch guardrails for unattended submit; (ok, reason-if-not)."""
    from wingman.apply.fillers import FILLERS

    if kind not in FILLERS:
        return False, f"no filler for {kind or 'unknown ATS'}"
    applied = conn.execute(
        "SELECT 1 FROM applications WHERE job_id = ? AND applied_at IS NOT NULL", (job["id"],)
    ).fetchone()
    if applied:
        return False, "already applied to this job"
    settings = get_apply_settings(conn)
    if not settings["auto"].get(kind):
        return False, f"auto-submit is switched off for {kind}"
    if auto_submits_today(conn) >= settings["daily_cap"]:
        return False, f"daily auto-submit cap ({settings['daily_cap']}) reached"
    if company_cooldown_active(conn, job["company"] or "", settings["cooldown_days"]):
        return False, "applied to this company within the cooldown window"
    return True, ""


# --- session entry points (called from routes; work happens in a thread) ---


def start_assisted(settings: Settings, job_id: int) -> bool:
    current = status_for(job_id)
    if current and current.active:
        return False
    _set_status(job_id, "assisted", "starting")
    threading.Thread(target=_assisted_run, args=(settings, job_id), daemon=True).start()
    return True


def start_auto(settings: Settings, job_id: int) -> bool:
    current = status_for(job_id)
    if current and current.active:
        return False
    _set_status(job_id, "auto", "starting")
    threading.Thread(target=_auto_run, args=(settings, job_id), daemon=True).start()
    return True


# --- the flows ---


def _assisted_run(
    settings: Settings,
    job_id: int,
    headless: bool = False,
    review_timeout_s: float = REVIEW_TIMEOUT_S,
    poll_s: float = REVIEW_POLL_S,
) -> None:
    """Tier 1: fill a visible browser, the human reviews and clicks Submit."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    from wingman.apply.fillers import FILLERS, common

    conn = db.connect(settings.db_path)
    try:
        job, kind, filler = _job_and_filler(conn, job_id, FILLERS)
        if job is None:
            _set_status(job_id, "assisted", "error", "no such job")
            return
        if filler is None:
            _set_status(job_id, "assisted", "error", f"no filler for {kind or 'this ATS'}")
            return
        _set_status(job_id, "assisted", "filling")
        packet = build_packet(conn, job)
        with sync_playwright() as pw:
            context = _launch(pw, settings, headless=headless)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(
                    ats.apply_url(kind, job["url"]),
                    wait_until="domcontentloaded",
                    timeout=PAGE_LOAD_TIMEOUT_MS,
                )
                report = filler.fill(page, packet)
                db.record_event(
                    conn,
                    "apply.filled",
                    json.dumps({"job_id": job_id, "mode": "assisted", **report.summary()}),
                )
                todo = len(report.unmatched_required)
                message = (
                    f"Wingman filled {len(report.filled)} fields. "
                    + (
                        f"{todo} required field(s) outlined in red need you. "
                        if todo
                        else "Nothing looks missing. "
                    )
                    + "Review everything, then click Submit yourself."
                )
                common.show_review_banner(page, report, message)
                _set_status(job_id, "assisted", "review", message)

                deadline = time.monotonic() + review_timeout_s
                while time.monotonic() < deadline:
                    if common.submission_confirmed(page, filler.CONFIRMATION_MARKERS):
                        _record_application(conn, job_id, "wingman-assisted", packet, report, None)
                        _set_status(job_id, "assisted", "submitted", "application recorded")
                        return
                    page.wait_for_timeout(poll_s * 1000)
                _set_status(job_id, "assisted", "abandoned", "review window timed out")
                db.record_event(conn, "apply.abandoned", json.dumps({"job_id": job_id}))
            finally:
                _close_quietly(context)
    except PlaywrightError as exc:
        detail = str(exc).splitlines()[0]
        if "closed" in detail.lower():
            # The human closed the window without submitting: that's a decision.
            _set_status(job_id, "assisted", "abandoned", "browser window closed")
            db.record_event(conn, "apply.abandoned", json.dumps({"job_id": job_id}))
        else:
            logger.warning("assisted apply failed for job %d: %s", job_id, detail)
            _set_status(job_id, "assisted", "error", detail)
            db.record_event(
                conn, "apply.error", json.dumps({"job_id": job_id, "error": detail[:300]})
            )
    except Exception as exc:  # never let an apply thread die silently
        logger.exception("assisted apply crashed for job %d", job_id)
        _set_status(job_id, "assisted", "error", str(exc)[:200])
        db.record_event(
            conn, "apply.error", json.dumps({"job_id": job_id, "error": str(exc)[:300]})
        )
    finally:
        conn.close()


def _auto_run(settings: Settings, job_id: int, headless: bool = True) -> None:
    """Tier 2: unattended submit — only when every guardrail passes."""
    from playwright.sync_api import Error as PlaywrightError
    from playwright.sync_api import sync_playwright

    from wingman.apply.fillers import FILLERS

    if not _auto_lock.acquire(blocking=False):
        _set_status(job_id, "auto", "blocked", "another auto-apply is already running")
        return
    conn = db.connect(settings.db_path)
    try:
        job, kind, filler = _job_and_filler(conn, job_id, FILLERS)
        ok, reason = auto_check(conn, job, kind) if job is not None else (False, "no such job")
        if not ok:
            _set_status(job_id, "auto", "blocked", reason)
            db.record_event(
                conn, "apply.auto_blocked", json.dumps({"job_id": job_id, "reason": reason})
            )
            return
        _set_status(job_id, "auto", "filling")
        packet = build_packet(conn, job)
        with sync_playwright() as pw:
            context = _launch(pw, settings, headless=headless)
            try:
                page = context.pages[0] if context.pages else context.new_page()
                page.goto(
                    ats.apply_url(kind, job["url"]),
                    wait_until="domcontentloaded",
                    timeout=PAGE_LOAD_TIMEOUT_MS,
                )
                report = filler.fill(page, packet)
                db.record_event(
                    conn,
                    "apply.filled",
                    json.dumps({"job_id": job_id, "mode": "auto", **report.summary()}),
                )
                if not report.clean:
                    # CAPTCHA or unanswered required field: never submit.
                    reason = (
                        "CAPTCHA on the form"
                        if report.captcha
                        else "required fields Wingman could not answer: "
                        + "; ".join(report.unmatched_required[:5])
                    )
                    _set_status(job_id, "auto", "needs_review", reason)
                    db.record_event(
                        conn,
                        "apply.auto_fallback",
                        json.dumps({"job_id": job_id, "reason": reason[:300]}),
                    )
                    return
                page.locator(filler.SUBMIT_SELECTOR).first.click()
                confirmed = _wait_confirmed(page, filler.CONFIRMATION_MARKERS)
                screenshot = _screenshot(page, settings, job_id)
                _record_application(
                    conn, job_id, "wingman-auto", packet, report, screenshot, confirmed=confirmed
                )
                if confirmed:
                    _set_status(job_id, "auto", "submitted", "submitted and confirmed")
                else:
                    _set_status(
                        job_id,
                        "auto",
                        "unconfirmed",
                        "submit clicked but no confirmation page detected — check the screenshot",
                    )
            finally:
                _close_quietly(context)
    except PlaywrightError as exc:
        detail = str(exc).splitlines()[0]
        logger.warning("auto apply failed for job %d: %s", job_id, detail)
        _set_status(job_id, "auto", "error", detail)
        db.record_event(conn, "apply.error", json.dumps({"job_id": job_id, "error": detail[:300]}))
    except Exception as exc:
        logger.exception("auto apply crashed for job %d", job_id)
        _set_status(job_id, "auto", "error", str(exc)[:200])
        db.record_event(
            conn, "apply.error", json.dumps({"job_id": job_id, "error": str(exc)[:300]})
        )
    finally:
        conn.close()
        _auto_lock.release()


# --- helpers ---


def _job_and_filler(conn: sqlite3.Connection, job_id: int, fillers: dict):
    job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
    if job is None:
        return None, None, None
    kind = ats.ensure_ats_kind(conn, job)
    return job, kind, fillers.get(kind)


def _launch(pw, settings: Settings, headless: bool):
    settings.browser_profile_dir.mkdir(parents=True, exist_ok=True)
    kwargs = {}
    if settings.browser_path:
        kwargs["executable_path"] = str(settings.browser_path)
    return pw.chromium.launch_persistent_context(
        str(settings.browser_profile_dir), headless=headless, **kwargs
    )


def _close_quietly(context) -> None:
    try:
        context.close()
    except Exception:  # already closed by the user
        pass


def _wait_confirmed(page, markers: tuple[str, ...], timeout_s: float = CONFIRM_TIMEOUT_S) -> bool:
    from wingman.apply.fillers import common

    deadline = time.monotonic() + timeout_s
    while time.monotonic() < deadline:
        if common.submission_confirmed(page, markers):
            return True
        page.wait_for_timeout(500)
    return False


def _screenshot(page, settings: Settings, job_id: int) -> str | None:
    """Every auto-submission gets a screenshot (PLAN §5 Tier 2)."""
    try:
        settings.screenshots_dir.mkdir(parents=True, exist_ok=True)
        path = settings.screenshots_dir / f"job{job_id}-{int(time.time())}.png"
        page.screenshot(path=str(path), full_page=True)
        return str(path)
    except Exception as exc:
        logger.warning("screenshot failed for job %d: %s", job_id, str(exc).splitlines()[0])
        return None


def _record_application(
    conn: sqlite3.Connection,
    job_id: int,
    method: str,
    packet: FillPacket,
    report,
    screenshot: str | None,
    confirmed: bool = True,
) -> None:
    """Record the application with exact document snapshots (PLAN §5)."""
    tracker.set_state(conn, job_id, "applied")  # state + applied_at + follow-up reminder
    row = conn.execute("SELECT docs_json FROM applications WHERE job_id = ?", (job_id,)).fetchone()
    docs = {}
    if row and row["docs_json"]:
        try:
            docs = json.loads(row["docs_json"])
        except json.JSONDecodeError:
            docs = {}
    docs.update(
        {
            "cover_letter": packet.cover_letter,
            "resume_path": str(packet.resume_path) if packet.resume_path else None,
            "resume_name": packet.resume_name,
            "fill_report": report.summary(),
            "screenshot": screenshot,
            "confirmed": confirmed,
        }
    )
    conn.execute(
        "UPDATE applications SET method = ?, docs_json = ? WHERE job_id = ?",
        (method, json.dumps(docs), job_id),
    )
    conn.commit()
    db.record_event(
        conn, "apply.submitted", json.dumps({"job_id": job_id, "method": method, "ok": confirmed})
    )
