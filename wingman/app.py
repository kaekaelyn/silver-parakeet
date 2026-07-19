"""FastAPI application: dashboard, health, and sources admin."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from wingman import __version__, db, ingest, scheduler
from wingman.config import Settings, load_settings

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")


class HealthResponse(BaseModel):
    status: str
    version: str
    migrations: int


def create_app(settings: Settings | None = None, with_scheduler: bool = True) -> FastAPI:
    app_settings = settings or load_settings()
    app_scheduler = scheduler.create_scheduler() if with_scheduler else None

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        with db.session(app_settings.db_path) as conn:
            applied = db.migrate(conn)
            if applied:
                logger.info("applied migrations: %s", ", ".join(applied))
            ingest.ensure_default_sources(conn)
            db.record_event(conn, "app.started")
        if app_scheduler is not None:
            app_scheduler.start()
            scheduler.refresh_jobs(app_scheduler, app_settings)
        yield
        if app_scheduler is not None:
            app_scheduler.shutdown(wait=False)

    app = FastAPI(title="Wingman", version=__version__, lifespan=lifespan)
    app.state.settings = app_settings
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    def _refresh_scheduler() -> None:
        if app_scheduler is not None:
            scheduler.refresh_jobs(app_scheduler, app_settings)

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        with db.session(app_settings.db_path) as conn:
            counts = {
                table: conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                for table in ("jobs", "sources", "applications", "reminders")
            }
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"version": __version__, "counts": counts},
        )

    @app.get("/health")
    def health() -> HealthResponse:
        with db.session(app_settings.db_path) as conn:
            row = conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()
        return HealthResponse(status="ok", version=__version__, migrations=row["n"])

    @app.get("/sources", response_class=HTMLResponse)
    def sources_page(request: Request) -> HTMLResponse:
        with db.session(app_settings.db_path) as conn:
            rows = conn.execute(
                """SELECT s.*, count(j.id) AS job_count
                   FROM sources s LEFT JOIN jobs j ON j.source_id = s.id
                   GROUP BY s.id ORDER BY s.id"""
            ).fetchall()
        return templates.TemplateResponse(request, "sources.html", {"sources": rows})

    @app.post("/sources/{source_id}/toggle")
    def toggle_source(source_id: int) -> RedirectResponse:
        with db.session(app_settings.db_path) as conn:
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
        _refresh_scheduler()
        return RedirectResponse("/sources", status_code=303)

    @app.post("/sources/{source_id}/fetch")
    def fetch_source_now(source_id: int) -> RedirectResponse:
        with db.session(app_settings.db_path) as conn:
            ingest.fetch_source(conn, source_id)
        return RedirectResponse("/sources", status_code=303)

    @app.post("/sources/add-rss")
    def add_rss_source(name: str = Form(...), feed_url: str = Form(...)) -> RedirectResponse:
        with db.session(app_settings.db_path) as conn:
            conn.execute(
                "INSERT INTO sources (kind, name, config_json) VALUES ('rss', ?, ?)",
                (name.strip(), json.dumps({"feed_url": feed_url.strip()})),
            )
            conn.commit()
            db.record_event(conn, "source.added", json.dumps({"source": name.strip()}))
        _refresh_scheduler()
        return RedirectResponse("/sources", status_code=303)

    @app.post("/sources/{source_id}/delete")
    def delete_source(source_id: int) -> RedirectResponse:
        # Only user-added RSS feeds are deletable; built-in boards are
        # toggled off instead. Jobs already ingested are kept (detached).
        with db.session(app_settings.db_path) as conn:
            row = conn.execute(
                "SELECT name, kind FROM sources WHERE id = ?", (source_id,)
            ).fetchone()
            if row and row["kind"] == "rss":
                conn.execute("UPDATE jobs SET source_id = NULL WHERE source_id = ?", (source_id,))
                conn.execute("DELETE FROM sources WHERE id = ?", (source_id,))
                conn.commit()
                db.record_event(conn, "source.deleted", json.dumps({"source": row["name"]}))
        _refresh_scheduler()
        return RedirectResponse("/sources", status_code=303)

    return app
