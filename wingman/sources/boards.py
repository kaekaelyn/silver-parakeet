"""Company watchlist: poll Greenhouse/Lever/Ashby public JSON boards.

Andy lists companies he'd love to work for; Wingman polls their public
job-board APIs directly — the highest-signal source there is (PLAN §3).
Each watchlist entry is its own source row (kind `<ats>_board`, config
holds the board slug), so one company's broken board never affects
another's.
"""

import html
from datetime import UTC, datetime
from typing import Any

import httpx

from wingman.sources import (
    RawPosting,
    SourceAdapter,
    html_to_text,
    parse_datetime,
    parse_salary_range,
)

WATCHLIST_KINDS = ("greenhouse_board", "lever_board", "ashby_board")
WATCHLIST_ATS = ("greenhouse", "lever", "ashby")

GREENHOUSE_API = "https://boards-api.greenhouse.io/v1/boards/{slug}/jobs?content=true"
LEVER_API = "https://api.lever.co/v0/postings/{slug}?mode=json"
ASHBY_API = "https://api.ashbyhq.com/posting-api/job-board/{slug}"


def _slug_of(config: dict[str, Any]) -> str:
    slug = str(config.get("company") or "").strip()
    if not slug:
        raise ValueError("watchlist source has no company board slug configured")
    return slug


def _company_of(config: dict[str, Any]) -> str:
    return str(config.get("company_name") or "").strip() or _slug_of(config).title()


def parse_greenhouse(payload: dict[str, Any], company: str) -> list[RawPosting]:
    postings: list[RawPosting] = []
    for job in payload.get("jobs", []):
        location = ((job.get("location") or {}).get("name") or "").strip() or None
        # The boards API HTML-escapes the posting body once.
        description = html_to_text(html.unescape(job.get("content") or ""))
        postings.append(
            RawPosting(
                url=job.get("absolute_url") or "",
                title=job.get("title") or "",
                company=company,
                location=location,
                remote=True if "remote" in (location or "").lower() else None,
                description=description,
                posted_at=parse_datetime(job.get("updated_at")),
                raw={"watchlist": True, "greenhouse_id": job.get("id")},
            )
        )
    return [p for p in postings if p.url and p.title]


def parse_lever(payload: list[dict[str, Any]], company: str) -> list[RawPosting]:
    postings: list[RawPosting] = []
    for job in payload:
        categories = job.get("categories") or {}
        salary = job.get("salaryRange") or {}
        workplace = str(job.get("workplaceType") or "").lower()
        posted_at = None
        if job.get("createdAt"):
            try:
                posted_at = datetime.fromtimestamp(int(job["createdAt"]) / 1000, tz=UTC)
            except (ValueError, OSError):
                posted_at = None
        postings.append(
            RawPosting(
                url=job.get("hostedUrl") or "",
                title=job.get("text") or "",
                company=company,
                location=categories.get("location") or None,
                remote=True if workplace == "remote" else None,
                salary_min=salary.get("min") or None,
                salary_max=salary.get("max") or None,
                description=job.get("descriptionPlain")
                or html_to_text(job.get("description") or ""),
                posted_at=posted_at,
                raw={"watchlist": True, "lever_id": job.get("id")},
            )
        )
    return [p for p in postings if p.url and p.title]


def parse_ashby(payload: dict[str, Any], company: str) -> list[RawPosting]:
    postings: list[RawPosting] = []
    for job in payload.get("jobs", []):
        if job.get("isListed") is False:
            continue
        salary_min, salary_max = parse_salary_range(job.get("compensationTierSummary") or "")
        postings.append(
            RawPosting(
                url=job.get("jobUrl") or job.get("applyUrl") or "",
                title=job.get("title") or "",
                company=company,
                location=job.get("location") or None,
                remote=True if job.get("isRemote") else None,
                salary_min=salary_min,
                salary_max=salary_max,
                description=job.get("descriptionPlain")
                or html_to_text(job.get("descriptionHtml") or ""),
                posted_at=parse_datetime(job.get("publishedAt")),
                raw={"watchlist": True, "ashby_id": job.get("id")},
            )
        )
    return [p for p in postings if p.url and p.title]


class GreenhouseBoardSource(SourceAdapter):
    kind = "greenhouse_board"
    default_interval_minutes = 120

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        response = client.get(GREENHOUSE_API.format(slug=_slug_of(config)))
        response.raise_for_status()
        return parse_greenhouse(response.json(), _company_of(config))


class LeverBoardSource(SourceAdapter):
    kind = "lever_board"
    default_interval_minutes = 120

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        response = client.get(LEVER_API.format(slug=_slug_of(config)))
        response.raise_for_status()
        return parse_lever(response.json(), _company_of(config))


class AshbyBoardSource(SourceAdapter):
    kind = "ashby_board"
    default_interval_minutes = 120

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        response = client.get(ASHBY_API.format(slug=_slug_of(config)))
        response.raise_for_status()
        return parse_ashby(response.json(), _company_of(config))
