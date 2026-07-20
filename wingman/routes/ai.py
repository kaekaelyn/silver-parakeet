"""AI settings and health page: provider choice, checks, manual batch run."""

import json

from fastapi import APIRouter, Form, HTTPException, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wingman import ai, aiscore, db
from wingman.web import settings_of, templates

router = APIRouter()


@router.get("/ai", response_class=HTMLResponse)
def ai_page(request: Request) -> HTMLResponse:
    with db.session(settings_of(request).db_path) as conn:
        current = ai.get_provider_name(conn)
        last = ai.last_call_status(conn)
        pending = aiscore.pending_count(conn)
        ai_scored = conn.execute("SELECT count(*) AS n FROM scores WHERE scorer = 'ai'").fetchone()[
            "n"
        ]
    providers = []
    for provider in ai.PROVIDERS.values():
        available, detail = provider.available()
        providers.append(
            {
                "name": provider.name,
                "label": provider.label,
                "available": available,
                "detail": detail,
            }
        )
    last_info = None
    if last:
        try:
            payload = json.loads(last["payload_json"] or "{}")
        except json.JSONDecodeError:
            payload = {}
        last_info = {"kind": last["kind"], "ts": last["ts"], "payload": payload}
    return templates.TemplateResponse(
        request,
        "ai.html",
        {
            "providers": providers,
            "current": current,
            "last": last_info,
            "pending": pending,
            "ai_scored": ai_scored,
        },
    )


@router.post("/ai/provider")
def set_provider(request: Request, provider: str = Form(...)) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        try:
            ai.set_provider_name(conn, provider)
        except ValueError as exc:
            raise HTTPException(status_code=422, detail=str(exc)) from exc
        db.record_event(conn, "ai.provider", json.dumps({"provider": provider}))
    return RedirectResponse("/ai", status_code=303)


@router.post("/ai/test")
def test_provider(request: Request) -> RedirectResponse:
    """One tiny real call so 'logged in / working?' has a truthful answer."""
    with db.session(settings_of(request).db_path) as conn:
        provider = ai.get_provider(conn)
        if provider.name == "none":
            return RedirectResponse("/ai", status_code=303)
        result = provider.complete(
            "You are a health check.",
            'Reply with a JSON object exactly like {"ok": true}.',
            {"type": "object", "properties": {"ok": {"type": "boolean"}}},
        )
        if isinstance(result, dict) and result.get("ok") is True:
            db.record_event(conn, "ai.ok", json.dumps({"provider": provider.name, "test": True}))
        else:
            db.record_event(
                conn,
                "ai.error",
                json.dumps({"provider": provider.name, "error": "test call failed"}),
            )
    return RedirectResponse("/ai", status_code=303)


@router.post("/ai/score-now")
def score_now(request: Request) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        aiscore.score_pending(conn)
    return RedirectResponse("/ai", status_code=303)
