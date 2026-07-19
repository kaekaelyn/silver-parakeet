"""FastAPI application: placeholder dashboard and health endpoint."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from wingman import __version__, db
from wingman.config import Settings, load_settings

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")


class HealthResponse(BaseModel):
    status: str
    version: str
    migrations: int


def create_app(settings: Settings | None = None) -> FastAPI:
    app_settings = settings or load_settings()

    @asynccontextmanager
    async def lifespan(_app: FastAPI) -> AsyncIterator[None]:
        with db.session(app_settings.db_path) as conn:
            applied = db.migrate(conn)
            if applied:
                logger.info("applied migrations: %s", ", ".join(applied))
            db.record_event(conn, "app.started")
        yield

    app = FastAPI(title="Wingman", version=__version__, lifespan=lifespan)
    app.state.settings = app_settings
    app.mount("/static", StaticFiles(directory=PACKAGE_DIR / "static"), name="static")

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

    return app
