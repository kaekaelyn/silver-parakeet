"""Notifications settings page: ntfy topic, digest hour, test push."""

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wingman import db, notify
from wingman.web import settings_of, templates

router = APIRouter()


@router.get("/notify", response_class=HTMLResponse)
def notify_page(request: Request) -> HTMLResponse:
    with db.session(settings_of(request).db_path) as conn:
        settings = notify.get_notify_settings(conn)
        recent = conn.execute(
            """SELECT ts, kind, payload_json FROM events
               WHERE kind LIKE 'notify.%' ORDER BY id DESC LIMIT 10"""
        ).fetchall()
        digest_title, digest_preview = notify.digest_content(conn)
    activity = []
    for row in recent:
        try:
            payload = json.loads(row["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        activity.append({"ts": row["ts"], "kind": row["kind"], "payload": payload})
    return templates.TemplateResponse(
        request,
        "notify.html",
        {
            "notify_settings": settings,
            "activity": activity,
            "digest_title": digest_title,
            "digest_preview": digest_preview,
        },
    )


@router.post("/notify/settings")
def save_notify_settings(
    request: Request,
    topic: str = Form(""),
    server: str = Form(""),
    digest_hour: int = Form(notify.DEFAULT_DIGEST_HOUR),
) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        notify.set_notify_settings(conn, topic, server or notify.DEFAULT_SERVER, digest_hour)
    return RedirectResponse("/notify", status_code=303)


@router.post("/notify/test")
def send_test_push(request: Request) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        notify.send_push(
            conn,
            "Wingman test",
            "Push notifications are working. 🪽",
            tags="white_check_mark",
        )
    return RedirectResponse("/notify", status_code=303)
