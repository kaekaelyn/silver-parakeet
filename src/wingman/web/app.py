from __future__ import annotations

from fastapi import FastAPI, Request
from fastapi.responses import HTMLResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates

from wingman.config import load_settings
from wingman.db.migrations import migrate

from pathlib import Path

ROOT = Path(__file__).resolve().parents[3]
templates = Jinja2Templates(directory=ROOT / "templates")


def create_app() -> FastAPI:
    settings = load_settings()
    migrate(settings.database_path)
    app = FastAPI(title="Wingman")
    app.mount("/static", StaticFiles(directory=ROOT / "static"), name="static")

    @app.get("/health")
    def health() -> dict[str, str]:
        return {"status": "ok"}

    @app.get("/", response_class=HTMLResponse)
    def dashboard(request: Request) -> HTMLResponse:
        return templates.TemplateResponse(
            "dashboard.html", {"request": request, "data_dir": settings.data_dir}
        )

    return app


app = create_app()
