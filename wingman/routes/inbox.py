"""Ranked inbox, job detail, job state actions, threshold setting."""

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wingman import __version__, db, scoring, tracker
from wingman.web import JOB_SELECT, chips_from_rationale, safe_next, settings_of, templates

router = APIRouter()


@router.get("/", response_class=HTMLResponse)
def inbox(request: Request, show: str = "inbox") -> HTMLResponse:
    with db.session(settings_of(request).db_path) as conn:
        threshold = scoring.get_threshold(conn)
        where = ["j.hidden = 0"]
        params: list[object] = []
        if show == "interested":
            where.append("a.state = 'interested'")
        else:
            # Jobs that progressed into the pipeline (applied and beyond)
            # live on the tracker board, not in the triage feed.
            where.append("(a.state IS NULL OR a.state = 'interested')")
            where.append("coalesce(s.score, 0) >= ?")
            params.append(threshold)
        rows = conn.execute(
            f"""{JOB_SELECT}
                WHERE {" AND ".join(where)}
                ORDER BY score DESC, coalesce(j.posted_at, j.first_seen_at) DESC
                LIMIT 200""",
            params,
        ).fetchall()
        total_jobs = conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"]
        due_reminders = conn.execute(
            """SELECT count(*) AS n FROM reminders
               WHERE done = 0 AND due_at <= datetime('now')"""
        ).fetchone()["n"]
    jobs = [dict(row) | {"chips": chips_from_rationale(row["rationale_json"])} for row in rows]
    return templates.TemplateResponse(
        request,
        "inbox.html",
        {
            "jobs": jobs,
            "threshold": threshold,
            "total_jobs": total_jobs,
            "show": show,
            "due_reminders": due_reminders,
            "pipeline_states": tracker.PIPELINE_STATES,
            "version": __version__,
        },
    )


@router.get("/jobs/{job_id}", response_class=HTMLResponse)
def job_detail(request: Request, job_id: int) -> HTMLResponse:
    from wingman import aiscore, letters
    from wingman.apply import ats, engine

    with db.session(settings_of(request).db_path) as conn:
        row = conn.execute(f"{JOB_SELECT} WHERE j.id = ?", (job_id,)).fetchone()
        if row is None:
            raise HTTPException(status_code=404, detail="no such job")
        reminders = conn.execute(
            "SELECT * FROM reminders WHERE job_id = ? AND done = 0 ORDER BY due_at",
            (job_id,),
        ).fetchall()
        ai_score = aiscore.ai_score_for(conn, job_id)
        cover_letter = letters.saved_letter(conn, job_id)
        ats_kind = ats.ensure_ats_kind(conn, row)
        auto_enabled = engine.get_apply_settings(conn)["auto"].get(ats_kind, False)
    job = dict(row) | {"chips": chips_from_rationale(row["rationale_json"]), "ats_kind": ats_kind}
    return templates.TemplateResponse(
        request,
        "job_detail.html",
        {
            "job": job,
            "reminders": reminders,
            "pipeline_states": tracker.PIPELINE_STATES,
            "ai_score": ai_score,
            "cover_letter": cover_letter,
            "ats_supported": ats_kind in ats.SUPPORTED,
            "auto_enabled": auto_enabled,
            "apply_status": engine.status_for(job_id),
        },
    )


@router.post("/jobs/{job_id}/state")
def set_job_state(
    request: Request, job_id: int, state: str = Form(...), next_url: str = Form("/")
) -> RedirectResponse:
    if not state or state not in (*tracker.PIPELINE_STATES, "hidden", "inbox"):
        return RedirectResponse(safe_next(next_url), status_code=303)
    with db.session(settings_of(request).db_path) as conn:
        tracker.set_state(conn, job_id, state)
    return RedirectResponse(safe_next(next_url), status_code=303)


@router.post("/jobs/{job_id}/notes")
def save_notes(
    request: Request, job_id: int, notes: str = Form(""), next_url: str = Form("/")
) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        tracker.save_notes(conn, job_id, notes)
    return RedirectResponse(safe_next(next_url), status_code=303)


@router.post("/jobs/{job_id}/cover-letter")
def draft_cover_letter(request: Request, job_id: int) -> RedirectResponse:
    from wingman import letters

    with db.session(settings_of(request).db_path) as conn:
        job = conn.execute("SELECT * FROM jobs WHERE id = ?", (job_id,)).fetchone()
        if job is None:
            raise HTTPException(status_code=404, detail="no such job")
        letter, used_ai = letters.generate_cover_letter(conn, job)
        letters.save_letter(conn, job_id, letter)
        db.record_event(conn, "letter.drafted", json.dumps({"job_id": job_id, "ai": used_ai}))
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/settings/threshold")
def set_threshold(request: Request, threshold: int = Form(...)) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        scoring.set_threshold(conn, threshold)
        db.record_event(conn, "settings.threshold", json.dumps({"threshold": threshold}))
    return RedirectResponse("/", status_code=303)
