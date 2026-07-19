"""Pipeline board and reminders."""

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wingman import db, tracker
from wingman.web import safe_next, settings_of, templates

router = APIRouter()


@router.get("/tracker", response_class=HTMLResponse)
def tracker_page(request: Request) -> HTMLResponse:
    with db.session(settings_of(request).db_path) as conn:
        board = tracker.pipeline_board(conn)
        due = tracker.due_reminders(conn)
        upcoming = tracker.upcoming_reminders(conn)
    return templates.TemplateResponse(
        request,
        "tracker.html",
        {
            "board": board,
            "due": due,
            "upcoming": upcoming,
            "pipeline_states": tracker.PIPELINE_STATES,
        },
    )


@router.post("/jobs/{job_id}/reminders")
def add_reminder(
    request: Request,
    job_id: int,
    due_date: str = Form(...),
    message: str = Form(""),
    next_url: str = Form("/tracker"),
) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        tracker.add_reminder(conn, job_id, due_date, message)
    return RedirectResponse(safe_next(next_url), status_code=303)


@router.post("/reminders/{reminder_id}/done")
def reminder_done(
    request: Request, reminder_id: int, next_url: str = Form("/tracker")
) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        tracker.complete_reminder(conn, reminder_id)
    return RedirectResponse(safe_next(next_url), status_code=303)
