"""Paste-a-URL capture page (and the PWA share-target endpoint)."""

import json
import logging
import re

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse, Response

from wingman import capture, db
from wingman.web import settings_of, templates

logger = logging.getLogger(__name__)

router = APIRouter()

_URL_IN_TEXT = re.compile(r"https?://[^\s<>\"']+")


def shared_url(url: str, text: str, title: str) -> str:
    """Best URL from an Android share payload.

    Apps are inconsistent: some put the link in `url`, most put it inside
    `text` (sometimes with a message around it), a few in `title`.
    """
    if url.strip().startswith(("http://", "https://")):
        return url.strip()
    for field in (text, title):
        match = _URL_IN_TEXT.search(field or "")
        if match:
            return match.group(0).rstrip(".,;)")
    return ""


@router.get("/capture", response_class=HTMLResponse)
def capture_page(request: Request, url: str = "", text: str = "", title: str = "") -> HTMLResponse:
    # The Android share-target (PWA manifest, method=GET) lands here with
    # title/text/url query params; a bare visit just shows the empty form.
    return templates.TemplateResponse(
        request, "capture.html", {"error": None, "url": shared_url(url, text, title)}
    )


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
