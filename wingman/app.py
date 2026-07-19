"""FastAPI application: placeholder dashboard and health endpoint."""

import logging
import sqlite3
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from wingman import __version__, db
from wingman.config import Settings, load_settings

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")


def _connect(settings: Settings) -> sqlite3.Connection:
    return db.connect(settings.db_path)


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        conn = _connect(app_settings)
        try:
            applied = db.migrate(conn)
            if applied:
                logger.info("applied migrations: %s", ", ".join(applied))
            db.record_event(conn, "app.started")
        finally:
            conn.close()
        yield

    app = FastAPI(title="Wingman", version=__version__, lifespan=lifespan)
    app.state.settings = app_settings
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        conn = _connect(app_settings)
        try:
            counts = {
                table: conn.execute(f"SELECT count(*) AS n FROM {table}").fetchone()["n"]
                for table in ("jobs", "sources", "applications", "reminders")
            }
        finally:
            conn.close()
        return templates.TemplateResponse(
            request,
            "dashboard.html",
            {"version": __version__, "counts": counts},
        )

    @app.get("/health")
    def health() -> dict[str, object]:
        conn = _connect(app_settings)
        try:
            migrations = conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()["n"]
        finally:
            conn.close()
        return {"status": "ok", "version": __version__, "migrations": migrations}

    return app
