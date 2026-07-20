"""Metrics page: is the search working?"""

from fastapi import APIRouter, Request
from fastapi.responses import HTMLResponse

from wingman import db, metrics
from wingman.web import settings_of, templates

router = APIRouter()


@router.get("/metrics", response_class=HTMLResponse)
def metrics_page(request: Request) -> HTMLResponse:
    with db.session(settings_of(request).db_path) as conn:
        weekly = metrics.applications_per_week(conn)
        by_source = metrics.response_rate_by_source(conn)
        by_band = metrics.response_rate_by_band(conn)
        overall = metrics.totals(conn)
    max_weekly = max((row["applied"] for row in weekly), default=0)
    return templates.TemplateResponse(
        request,
        "metrics.html",
        {
            "weekly": weekly,
            "max_weekly": max_weekly,
            "by_source": by_source,
            "by_band": by_band,
            "overall": overall,
        },
    )
