"""Sources admin: enable/disable, fetch now, add/delete RSS feeds."""

import json

from fastapi import APIRouter, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse

from wingman import boardkeys, db, ingest
from wingman.sources.boards import WATCHLIST_ATS, WATCHLIST_KINDS
from wingman.web import settings_of, templates

KEYED_BOARD_NAMES = {"adzuna": "Adzuna", "usajobs": "USAJOBS"}
KEYED_SEARCH_FIELD = {"adzuna": "what", "usajobs": "keyword"}

# User-added source kinds may be deleted; built-in boards only toggle off.
DELETABLE_KINDS = ("rss", *WATCHLIST_KINDS)

router = APIRouter()


def _refresh_scheduler(request: Request) -> None:
    refresh = getattr(request.app.state, "refresh_scheduler", None)
    if refresh is not None:
        refresh()


@router.get("/sources", response_class=HTMLResponse)
def sources_page(request: Request) -> HTMLResponse:
    with db.session(settings_of(request).db_path) as conn:
        rows = conn.execute(
            """SELECT s.*, count(j.id) AS job_count
               FROM sources s LEFT JOIN jobs j ON j.source_id = s.id
               GROUP BY s.id ORDER BY s.id"""
        ).fetchall()
        keyed = []
        with_keys = set()
        for kind, label in KEYED_BOARD_NAMES.items():
            present = boardkeys.keys_present(conn, kind)
            if present:
                with_keys.add(kind)
            source_row = next((r for r in rows if r["kind"] == kind), None)
            search = ""
            if source_row:
                search = json.loads(source_row["config_json"] or "{}").get(
                    KEYED_SEARCH_FIELD[kind], ""
                )
            keyed.append(
                {
                    "kind": kind,
                    "label": label,
                    "configured": present,
                    "search": search,
                    "fields": [
                        {"name": field, "label": ui_label}
                        for field, _pk, _env, ui_label in boardkeys.KEY_FIELDS[kind]
                    ],
                    "signup_url": boardkeys.SIGNUP_URLS[kind],
                }
            )
    # Keyed boards without keys stay out of the table entirely.
    visible = [r for r in rows if r["kind"] not in KEYED_BOARD_NAMES or r["kind"] in with_keys]
    return templates.TemplateResponse(
        request,
        "sources.html",
        {
            "sources": visible,
            "deletable_kinds": DELETABLE_KINDS,
            "watchlist_ats": WATCHLIST_ATS,
            "keyed_boards": keyed,
        },
    )


@router.post("/sources/keys")
async def save_board_keys(request: Request, kind: str = Form(...)) -> RedirectResponse:
    """Save a keyed board's API keys (profile table) and search terms."""
    if kind not in KEYED_BOARD_NAMES:
        return RedirectResponse("/sources", status_code=303)
    form = await request.form()
    with db.session(settings_of(request).db_path) as conn:
        for field, profile_key, _env, _label in boardkeys.KEY_FIELDS[kind]:
            value = str(form.get(field, "")).strip()
            if not value:
                continue  # blank means "keep the saved key"; clearing has its own button
            conn.execute(
                """INSERT INTO profile (key, value) VALUES (?, ?)
                   ON CONFLICT (key) DO UPDATE SET value = excluded.value""",
                (profile_key, value),
            )
        conn.commit()
        present = boardkeys.keys_present(conn, kind)
        config = json.dumps({KEYED_SEARCH_FIELD[kind]: str(form.get("search", "")).strip()})
        row = conn.execute("SELECT id FROM sources WHERE kind = ?", (kind,)).fetchone()
        if row:
            conn.execute(
                "UPDATE sources SET config_json = ?, enabled = ? WHERE id = ?",
                (config, int(present), row["id"]),
            )
        elif present:
            conn.execute(
                "INSERT INTO sources (kind, name, config_json) VALUES (?, ?, ?)",
                (kind, KEYED_BOARD_NAMES[kind], config),
            )
        conn.commit()
        # Configured-or-not only; the key values themselves never hit the log.
        db.record_event(conn, "source.keys", json.dumps({"kind": kind, "configured": present}))
    _refresh_scheduler(request)
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/{source_id}/toggle")
def toggle_source(request: Request, source_id: int) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        conn.execute("UPDATE sources SET enabled = 1 - enabled WHERE id = ?", (source_id,))
        conn.commit()
        row = conn.execute(
            "SELECT name, enabled FROM sources WHERE id = ?", (source_id,)
        ).fetchone()
        if row:
            db.record_event(
                conn,
                "source.toggled",
                json.dumps({"source": row["name"], "enabled": bool(row["enabled"])}),
            )
    _refresh_scheduler(request)
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/{source_id}/fetch")
def fetch_source_now(request: Request, source_id: int) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        ingest.fetch_source(conn, source_id)
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/add-rss")
def add_rss_source(
    request: Request, name: str = Form(...), feed_url: str = Form(...)
) -> RedirectResponse:
    with db.session(settings_of(request).db_path) as conn:
        conn.execute(
            "INSERT INTO sources (kind, name, config_json) VALUES ('rss', ?, ?)",
            (name.strip(), json.dumps({"feed_url": feed_url.strip()})),
        )
        conn.commit()
        db.record_event(conn, "source.added", json.dumps({"source": name.strip()}))
    _refresh_scheduler(request)
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/keys/clear")
def clear_board_keys(request: Request, kind: str = Form(...)) -> RedirectResponse:
    """Forget a keyed board's API keys; its source disables and disappears."""
    if kind not in KEYED_BOARD_NAMES:
        return RedirectResponse("/sources", status_code=303)
    with db.session(settings_of(request).db_path) as conn:
        for _field, profile_key, _env, _label in boardkeys.KEY_FIELDS[kind]:
            conn.execute("DELETE FROM profile WHERE key = ?", (profile_key,))
        conn.execute("UPDATE sources SET enabled = 0 WHERE kind = ?", (kind,))
        conn.commit()
        db.record_event(conn, "source.keys", json.dumps({"kind": kind, "configured": False}))
    _refresh_scheduler(request)
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/add-watchlist")
def add_watchlist_source(
    request: Request,
    company_name: str = Form(...),
    ats: str = Form(...),
    slug: str = Form(...),
) -> RedirectResponse:
    """Watch a company's public job board (Greenhouse/Lever/Ashby)."""
    if ats not in WATCHLIST_ATS:
        return RedirectResponse("/sources", status_code=303)
    company_name = company_name.strip()
    slug = slug.strip().strip("/").split("/")[-1]  # accept a pasted board URL tail
    if not company_name or not slug:
        return RedirectResponse("/sources", status_code=303)
    with db.session(settings_of(request).db_path) as conn:
        conn.execute(
            "INSERT INTO sources (kind, name, config_json) VALUES (?, ?, ?)",
            (
                f"{ats}_board",
                f"Watchlist: {company_name}",
                json.dumps({"company": slug, "company_name": company_name}),
            ),
        )
        conn.commit()
        db.record_event(conn, "source.added", json.dumps({"source": company_name, "ats": ats}))
    _refresh_scheduler(request)
    return RedirectResponse("/sources", status_code=303)


@router.post("/sources/{source_id}/delete")
def delete_source(request: Request, source_id: int) -> RedirectResponse:
    # Only user-added sources (RSS feeds, watchlist boards) are deletable;
    # built-in boards are toggled off instead. Ingested jobs are kept
    # (detached).
    with db.session(settings_of(request).db_path) as conn:
        row = conn.execute("SELECT name, kind FROM sources WHERE id = ?", (source_id,)).fetchone()
        if row and row["kind"] in DELETABLE_KINDS:
            conn.execute("UPDATE jobs SET source_id = NULL WHERE source_id = ?", (source_id,))
            conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
            conn.commit()
            db.record_event(conn, "source.deleted", json.dumps({"source": row["name"]}))
    _refresh_scheduler(request)
    return RedirectResponse("/sources", status_code=303)
