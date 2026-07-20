"""Paste-a-URL capture page."""

import json
import logging

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from wingman import capture, db
from wingman.web import settings_of, templates

logger = logging.getLogger(__name__)

router = APIRouter()


@router.get("/capture", response_class=HTMLResponse)
def capture_page(request: Request, url: str = "") -> HTMLResponse:
    # `url` prefills the form — this is what the M6 Android share-target
    # (method=GET) will point at.
    return templates.TemplateResponse(request, "capture.html", {"error": None, "url": url})


@router.post("/capture", response_class=HTMLResponse)
def capture_submit(request: Request, url: str = Form(...)) -> Response:
    url = url.strip()
    if not url.startswith(("http://", "https://")):
        return templates.TemplateResponse(
            request,
            "capture.html",
            {"error": "Please paste a full http(s) link.", "url": url},
            status_code=422,
        )
    try:
        with db.session(settings_of(request).db_path) as conn:
            job_id = capture.capture_url(conn, url)
    except Exception as exc:
        logger.exception("capture failed for %s", url)
        with db.session(settings_of(request).db_path) as conn:
            db.record_event(conn, "capture.error", json.dumps({"url": url, "error": str(exc)}))
        return templates.TemplateResponse(
            request,
            "capture.html",
            {"error": f"Couldn't capture that page: {exc}", "url": url},
            status_code=422,
        )
    return RedirectResponse(f"/jobs/{job_id}", status_code=303)
