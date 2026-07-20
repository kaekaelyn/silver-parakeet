"""FastAPI application assembly: lifespan, routers, health."""

import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager

from fastapi import FastAPI
from fastapi.responses import FileResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel

from wingman import __version__, db, ingest, scheduler, scoring, vault
from wingman.config import Settings, load_settings
from wingman.routes import ai as ai_routes
from wingman.routes import apply as apply_routes
from wingman.routes import capture as capture_routes
from wingman.routes import criteria as criteria_routes
from wingman.routes import inbox as inbox_routes
from wingman.routes import notify as notify_routes
from wingman.routes import sources as sources_routes
from wingman.routes import tracker as tracker_routes
from wingman.routes import vault as vault_routes
from wingman.web import PACKAGE_DIR

logger = logging.getLogger(__name__)


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
            scoring.ensure_default_criteria(conn)
            vault.ensure_default_answers(conn)
            scoring.score_new_jobs(conn)
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

    app.state.refresh_scheduler = _refresh_scheduler

    @app.get("/sw.js", include_in_schema=False)
    def service_worker() -> FileResponse:
        # Served from the root (not /static/) so its scope covers the whole
        # app — a service-worker scope never exceeds its script's directory.
        return FileResponse(PACKAGE_DIR / "static" / "sw.js", media_type="application/javascript")

    @app.get("/health")
    def health() -> HealthResponse:
        with db.session(app_settings.db_path) as conn:
            row = conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()
        return HealthResponse(status="ok", version=__version__, migrations=row["n"])

    for module in (
        inbox_routes,
        tracker_routes,
        criteria_routes,
        sources_routes,
        vault_routes,
        capture_routes,
        ai_routes,
        apply_routes,
        notify_routes,
    ):
        app.include_router(module.router)

    return app
