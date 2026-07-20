"""Login form for the PIN gate (only mounted when a PIN is configured).

Inline-styled on purpose: this page must render before the gate lets
anything else through, so it depends on no /static asset and no template.
"""

import hmac
import json
import logging
import time
from html import escape

from fastapi import APIRouter, Form, Query, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wingman import auth, db
from wingman.web import safe_next, settings_of

logger = logging.getLogger(__name__)

router = APIRouter()


def _page(next_url: str, error: str | None = None) -> str:
    error_html = f'<p style="color:#b3261e;margin:0 0 12px">{escape(error)}</p>' if error else ""
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Wingman — enter PIN</title></head>
<body style="font-family:system-ui,sans-serif;background:#f5f4f0;margin:0;
             display:flex;justify-content:center;align-items:center;min-height:100vh">
<form method="post" action="/login"
      style="background:#fff;border:1px solid #ddd;border-radius:10px;
             padding:28px 32px;max-width:320px;width:90%">
  <h1 style="font-size:1.2rem;margin:0 0 6px">Wingman</h1>
  <p style="color:#555;margin:0 0 16px">Enter your PIN to continue.</p>
  {error_html}
  <input type="hidden" name="next" value="{escape(next_url, quote=True)}">
  <input type="password" name="pin" inputmode="numeric" autocomplete="current-password"
         autofocus required aria-label="PIN"
         style="width:100%;box-sizing:border-box;font-size:1.3rem;letter-spacing:.3em;
                padding:10px 12px;border:1px solid #bbb;border-radius:6px">
  <button type="submit"
          style="width:100%;margin-top:14px;padding:10px;font-size:1rem;border:0;
                 border-radius:6px;background:#1a1a2e;color:#fff;cursor:pointer">
    Unlock</button>
</form></body></html>"""


@router.get("/login", response_class=HTMLResponse)
def login_form(next_url: str = Query("/", alias="next")) -> HTMLResponse:
    return HTMLResponse(_page(safe_next(next_url)))


@router.post("/login", response_model=None)
def login_submit(
    request: Request,
    pin: str = Form(""),
    next_url: str = Form("/", alias="next"),
) -> HTMLResponse | RedirectResponse:
    settings = settings_of(request)
    target = safe_next(next_url)
    if settings.pin is not None and hmac.compare_digest(pin, settings.pin):
        secret = auth.load_secret(settings.data_dir)
        response = RedirectResponse(target, status_code=303)
        response.set_cookie(
            auth.COOKIE_NAME,
            auth.cookie_value(secret),
            max_age=auth.COOKIE_MAX_AGE,
            httponly=True,
            samesite="lax",
        )
        return response
    client_ip = request.client.host if request.client else "unknown"
    logger.warning("failed PIN attempt from %s", client_ip)
    with db.session(settings.db_path) as conn:
        db.record_event(conn, "auth.failed", json.dumps({"ip": client_ip}))
    time.sleep(1)  # crude brute-force brake
    return HTMLResponse(_page(target, error="Wrong PIN — try again."))
