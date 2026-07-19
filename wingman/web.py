"""Shared web-layer helpers: templates, filters, and query fragments."""

import json
import logging
from datetime import UTC, datetime
from pathlib import Path

from fastapi import Request
from fastapi.templating import Jinja2Templates

from wingman.config import Settings
from wingman.timeutil import parse_timestamp

logger = logging.getLogger(__name__)

PACKAGE_DIR = Path(__file__).resolve().parent
templates = Jinja2Templates(directory=PACKAGE_DIR / "templates")

# One place decides how a job row is joined to its display score (M4 will
# add scorer='ai' and change only this fragment).
JOB_SELECT = """SELECT j.*, coalesce(s.score, 0) AS score, s.rationale_json,
       src.name AS source_name, a.state AS app_state
  FROM jobs j
  LEFT JOIN scores s ON s.job_id = j.id AND s.scorer = 'heuristic'
  LEFT JOIN sources src ON src.id = j.source_id
  LEFT JOIN applications a ON a.job_id = j.id"""


def settings_of(request: Request) -> Settings:
    return request.app.state.settings


def safe_next(next_url: str) -> str:
    """Only same-site paths: '//host' is protocol-relative, so exclude it."""
    if next_url.startswith("/") and not next_url.startswith("//"):
        return next_url
    return "/"


def chips_from_rationale(rationale_json: str | None) -> list[str]:
    if not rationale_json:
        return []
    try:
        return json.loads(rationale_json).get("chips", [])
    except json.JSONDecodeError:
        return []


def age_str(stamp: str | None) -> str:
    then = parse_timestamp(stamp)
    if then is None:
        return ""
    seconds = (datetime.now(UTC) - then).total_seconds()
    if seconds < 3600:
        return f"{max(1, int(seconds // 60))}m"
    if seconds < 86400:
        return f"{int(seconds // 3600)}h"
    return f"{int(seconds // 86400)}d"


def salary_str(salary_min: int | None, salary_max: int | None) -> str:
    def fmt(amount: int) -> str:
        return f"${amount // 1000}k" if amount >= 10000 else f"${amount}"

    if salary_min and salary_max:
        return f"{fmt(salary_min)}–{fmt(salary_max)}"
    if salary_min:
        return f"{fmt(salary_min)}+"
    if salary_max:
        return f"up to {fmt(salary_max)}"
    return ""


templates.env.filters["age"] = age_str
templates.env.globals["salary_str"] = salary_str
