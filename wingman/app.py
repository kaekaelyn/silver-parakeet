"""FastAPI application: ranked inbox, job detail, criteria editor, sources admin."""

import json
import logging
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from datetime import UTC, datetime
from pathlib import Path

from fastapi import FastAPI, Form, Request
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.staticfiles import StaticFiles
from fastapi.templating import Jinja2Templates
from pydantic import BaseModel

from wingman import __version__, db, ingest, scheduler, scoring
from wingman.boolquery import QueryError, compile_query
from wingman.config import Settings, load_settings

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")


def _age_str(stamp: str | None) -> str:
    if not stamp:
        return ""
    try:
        then = datetime.fromisoformat(stamp)
    except ValueError:
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=UTC)
    seconds = (datetime.now(UTC) - then).total_seconds()
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def _salary_str(salary_min: int | None, salary_max: int | None) -> str:
    def fmt(amount: int) -> str:
        return f"${amount // 1000}k" if amount >= 10000 else f"${amount}"

    if salary_min and salary_max:
        return f"{fmt(salary_min)}–{fmt(salary_max)}"
    if salary_min:
        return f"{fmt(salary_min)}+"
    if salary_max:
        return f"up to {fmt(salary_max)}"
    return ""


templates.env.filters["age"] = _age_str
templates.env.globals["salary_str"] = _salary_str


class HealthResponse(BaseModel):
    status: str
    version: str
    migrations: int


def _chips(rationale_json: str | None) -> list[str]:
    if not rationale_json:
        return []
    try:
        return json.loads(rationale_json).get("chips", [])
    except json.JSONDecodeError:
        return []


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

    # ── Inbox ────────────────────────────────────────────────────────────

    @app.get("/", response_class=HTMLResponse)
    def inbox(request: Request, show: str = "inbox") -> HTMLResponse:
        with db.session(app_settings.db_path) as conn:
            threshold = scoring.get_threshold(conn)
            state_filter = (
                "a.state = 'interested'"
                if show == "interested"
                else "(a.state IS NULL OR a.state NOT IN ('hidden'))"
            )
            rows = conn.execute(
                f"""SELECT j.*, s.score, s.rationale_json, src.name AS source_name,
                           a.state AS app_state
                    FROM jobs j
                    JOIN scores s ON s.job_id = j.id AND s.scorer = 'heuristic'
                    LEFT JOIN sources src ON src.id = j.source_id
                    LEFT JOIN applications a ON a.job_id = j.id
                    WHERE {state_filter} AND s.score >= ?
                    ORDER BY s.score DESC, coalesce(j.posted_at, j.first_seen_at) DESC
                    LIMIT 200""",
                (threshold if show == "inbox" else 0,),
            ).fetchall()
            total_jobs = conn.execute("SELECT count(*) AS n FROM jobs").fetchone()["n"]
        jobs = [dict(row) | {"chips": _chips(row["rationale_json"])} for row in rows]
        return templates.TemplateResponse(
            request,
            "inbox.html",
            {
                "jobs": jobs,
                "threshold": threshold,
                "total_jobs": total_jobs,
                "show": show,
                "version": __version__,
            },
        )

    @app.get("/jobs/{job_id}", response_class=HTMLResponse)
    def job_detail(request: Request, job_id: int) -> HTMLResponse:
        with db.session(app_settings.db_path) as conn:
            row = conn.execute(
                """SELECT j.*, s.score, s.rationale_json, src.name AS source_name,
                          a.state AS app_state
                   FROM jobs j
                   LEFT JOIN scores s ON s.job_id = j.id AND s.scorer = 'heuristic'
                   LEFT JOIN sources src ON src.id = j.source_id
                   LEFT JOIN applications a ON a.job_id = j.id
                   WHERE j.id = ?""",
                (job_id,),
            ).fetchone()
        if row is None:
            return templates.TemplateResponse(
                request,
                "inbox.html",
                {
                    "jobs": [],
                    "threshold": 0,
                    "total_jobs": 0,
                    "show": "inbox",
                    "version": __version__,
                },
                status_code=404,
            )
        job = dict(row) | {"chips": _chips(row["rationale_json"])}
        return templates.TemplateResponse(request, "job_detail.html", {"job": job})

    @app.post("/jobs/{job_id}/state")
    def set_job_state(
        job_id: int, state: str = Form(...), next_url: str = Form("/")
    ) -> RedirectResponse:
        if state not in ("interested", "hidden", "inbox"):
            return RedirectResponse(next_url, status_code=303)
        with db.session(app_settings.db_path) as conn:
            existing = conn.execute(
                "SELECT id FROM applications WHERE job_id = ?", (job_id,)
            ).fetchone()
            if state == "inbox":
                if existing:
                    conn.execute("DELETE FROM applications WHERE id = ?", (existing["id"],))
            elif existing:
                conn.execute(
                    "UPDATE applications SET state = ? WHERE id = ?", (state, existing["id"])
                )
            else:
                conn.execute(
                    "INSERT INTO applications (job_id, state) VALUES (?, ?)", (job_id, state)
                )
            conn.commit()
            db.record_event(conn, "job.state", json.dumps({"job_id": job_id, "state": state}))
        return RedirectResponse(next_url if next_url.startswith("/") else "/", status_code=303)

    @app.post("/settings/threshold")
    def set_threshold(threshold: int = Form(...)) -> RedirectResponse:
        with db.session(app_settings.db_path) as conn:
            scoring.set_threshold(conn, threshold)
        return RedirectResponse("/", status_code=303)

    # ── Criteria ─────────────────────────────────────────────────────────

    def _criteria_rows(conn) -> list[dict]:
        rows = conn.execute("SELECT * FROM criteria ORDER BY id").fetchall()
        return [dict(row) | {"config": json.loads(row["config_json"] or "{}")} for row in rows]

    @app.get("/criteria", response_class=HTMLResponse)
    def criteria_page(request: Request) -> HTMLResponse:
        with db.session(app_settings.db_path) as conn:
            criteria = _criteria_rows(conn)
            threshold = scoring.get_threshold(conn)
        return templates.TemplateResponse(
            request,
            "criteria.html",
            {"criteria": criteria, "threshold": threshold, "form": None, "error": None},
        )

    @app.post("/criteria/save", response_class=HTMLResponse)
    def save_criteria(
        request: Request,
        criteria_id: int = Form(0),
        name: str = Form(...),
        query: str = Form(""),
        nice_to_have: str = Form(""),
        exclude: str = Form(""),
        company_blocklist: str = Form(""),
        remote_only: bool = Form(False),
        salary_floor: str = Form(""),
        freshness_days: str = Form(""),
    ):
        def split_terms(raw: str) -> list[str]:
            return [t.strip() for t in raw.split(",") if t.strip()]

        form = {
            "id": criteria_id,
            "name": name.strip() or "Unnamed",
            "query": query.strip(),
            "nice_to_have": ", ".join(split_terms(nice_to_have)),
            "exclude": ", ".join(split_terms(exclude)),
            "company_blocklist": ", ".join(split_terms(company_blocklist)),
            "remote_only": remote_only,
            "salary_floor": salary_floor.strip(),
            "freshness_days": freshness_days.strip(),
        }
        try:
            compile_query(query)
            config = {
                "query": query.strip(),
                "nice_to_have": split_terms(nice_to_have),
                "exclude": split_terms(exclude),
                "company_blocklist": split_terms(company_blocklist),
                "remote_only": remote_only,
                "salary_floor": int(salary_floor) if salary_floor.strip() else None,
                "freshness_days": int(freshness_days) if freshness_days.strip() else None,
            }
        except (QueryError, ValueError) as exc:
            with db.session(app_settings.db_path) as conn:
                criteria = _criteria_rows(conn)
                threshold = scoring.get_threshold(conn)
            return templates.TemplateResponse(
                request,
                "criteria.html",
                {"criteria": criteria, "threshold": threshold, "form": form, "error": str(exc)},
                status_code=422,
            )
        with db.session(app_settings.db_path) as conn:
            if criteria_id:
                conn.execute(
                    "UPDATE criteria SET name = ?, config_json = ? WHERE id = ?",
                    (form["name"], json.dumps(config), criteria_id),
                )
            else:
                conn.execute(
                    "INSERT INTO criteria (name, config_json) VALUES (?, ?)",
                    (form["name"], json.dumps(config)),
                )
            conn.commit()
            db.record_event(conn, "criteria.saved", json.dumps({"name": form["name"]}))
            scoring.rescore_all(conn)
        return RedirectResponse("/criteria", status_code=303)

    @app.post("/criteria/{criteria_id}/toggle")
    def toggle_criteria(criteria_id: int) -> RedirectResponse:
        with db.session(app_settings.db_path) as conn:
            conn.execute("UPDATE criteria SET enabled = 1 - enabled WHERE id = ?", (criteria_id,))
            conn.commit()
            scoring.rescore_all(conn)
        return RedirectResponse("/criteria", status_code=303)

    @app.post("/criteria/{criteria_id}/delete")
    def delete_criteria(criteria_id: int) -> RedirectResponse:
        with db.session(app_settings.db_path) as conn:
            conn.execute("DELETE FROM criteria WHERE id = ?", (criteria_id,))
            conn.commit()
            scoring.rescore_all(conn)
        return RedirectResponse("/criteria", status_code=303)

    # ── Health ───────────────────────────────────────────────────────────

    @app.get("/health")
    def health() -> HealthResponse:
        with db.session(app_settings.db_path) as conn:
            row = conn.execute("SELECT count(*) AS n FROM schema_migrations").fetchone()
        return HealthResponse(status="ok", version=__version__, migrations=row["n"])

    # ── Sources admin ────────────────────────────────────────────────────

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
