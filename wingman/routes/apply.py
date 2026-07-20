"""Apply routes: start sessions from job detail; settings page for tiers."""

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wingman import db
from wingman.apply import ats, engine
from wingman.web import settings_of, templates

router = APIRouter()

ATS_LABELS = {
    "greenhouse": "Greenhouse",
    "lever": "Lever",
    "ashby": "Ashby",
    "workable": "Workable",
}


@router.get("/apply", response_class=HTMLResponse)
def apply_page(request: Request) -> HTMLResponse:
    with db.session(settings_of(request).db_path) as conn:
        apply_settings = engine.get_apply_settings(conn)
        used_today = engine.auto_submits_today(conn)
        verification = engine.live_verification(conn)
        recent = conn.execute(
            """SELECT ts, kind, payload_json FROM events
               WHERE kind LIKE 'apply.%' ORDER BY id DESC LIMIT 20"""
        ).fetchall()
    activity = []
    for row in recent:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        activity.append({"ts": row["ts"], "kind": row["kind"], "payload": payload})
    return templates.TemplateResponse(
        request,
        "apply.html",
        {
            "apply_settings": apply_settings,
            "used_today": used_today,
            "ats_labels": ATS_LABELS,
            "supported_kinds": ats.SUPPORTED,
            "verification": verification,
            "unverified_kinds": [k for k in ats.SUPPORTED if not verification[k]["verified"]],
            "activity": activity,
        },
    )


@router.post("/apply/verified/{kind}")
def dismiss_live_run_reminder(request: Request, kind: str) -> RedirectResponse:
    if kind not in ats.SUPPORTED:
        raise HTTPException(status_code=404, detail="unknown ATS kind")
    with db.session(settings_of(request).db_path) as conn:
        engine.mark_live_verified(conn, kind)
    return RedirectResponse("/apply", status_code=303)


@router.post("/apply/settings")
async def save_apply_settings(
    request: Request,
    daily_cap: int = Form(...),
    cooldown_days: int = Form(...),
) -> RedirectResponse:
    # Toggles key off ats.SUPPORTED so new fillers appear here automatically.
    form = await request.form()
    auto = {kind: form.get(f"auto_{kind}") is not None for kind in ats.SUPPORTED}
    with db.session(settings_of(request).db_path) as conn:
        engine.set_apply_settings(conn, auto, daily_cap, cooldown_days)
    return RedirectResponse("/apply", status_code=303)


@router.post("/jobs/{job_id}/apply")
def start_assisted_apply(request: Request, job_id: int) -> RedirectResponse:
    _require_job(request, job_id)
    engine.start_assisted(settings_of(request), job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


@router.post("/jobs/{job_id}/apply-auto")
def start_auto_apply(request: Request, job_id: int) -> RedirectResponse:
    _require_job(request, job_id)
    engine.start_auto(settings_of(request), job_id)
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)


def _require_job(request: Request, job_id: int) -> None:
    with db.session(settings_of(request).db_path) as conn:
        if conn.execute("SELECT 1 FROM jobs WHERE id = ?", (job_id,)).fetchone() is None:
            raise HTTPException(status_code=404, detail="no such job")
