"""Events page: the audit trail, surfaced (PLAN §7 — "what did you do
on my behalf and when").

Read-only over the existing `events` table; payloads are PII-clean by
convention and nothing new is logged for this page.
"""

import json

from fastapi import APIRouter, Query, Request
from fastapi.responses import HTMLResponse

from wingman import db
from wingman.web import settings_of, templates

router = APIRouter()

PAGE_SIZE = 100

# Kind prefixes offered as filters; anything else falls back to "all".
KIND_FILTERS = ("all", "fetch.", "apply.", "ai.", "notify.", "capture.")


def pretty_payload(payload_json: str | None) -> str:
    if not payload_json:
        return ""
    try:
        return json.dumps(json.loads(payload_json), indent=2, sort_keys=True)
    except json.JSONDecodeError:
        return payload_json


@router.get("/events", response_class=HTMLResponse)
def events_page(
    request: Request,
    kind: str = Query("all"),
    offset: int = Query(0, ge=0),
) -> HTMLResponse:
    if kind not in KIND_FILTERS:
        kind = "all"
    where, params = "", []
    if kind != "all":
        where = "WHERE kind LIKE ?"
        params.append(kind + "%")
    with db.session(settings_of(request).db_path) as conn:
        # One extra row tells us whether an older page exists.
        rows = conn.execute(
            f"""SELECT ts, kind, payload_json FROM events {where}
                ORDER BY id DESC LIMIT ? OFFSET ?""",
            (*params, PAGE_SIZE + 1, offset),
        ).fetchall()
    has_older = len(rows) > PAGE_SIZE
    events = [
        {"ts": row["ts"], "kind": row["kind"], "payload": pretty_payload(row["payload_json"])}
        for row in rows[:PAGE_SIZE]
    ]
    return templates.TemplateResponse(
        request,
        "events.html",
        {
            "events": events,
            "kind": kind,
            "filters": KIND_FILTERS,
            "offset": offset,
            "newer_offset": max(0, offset - PAGE_SIZE),
            "older_offset": offset + PAGE_SIZE,
            "has_older": has_older,
        },
    )
