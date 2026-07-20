"""USAJOBS search API (https://developer.usajobs.gov) — free key required.

USAJOBS authenticates with an Authorization-Key header plus the account
email as User-Agent. The source only exists in the UI once keys are
entered on the Sources page (or via WINGMAN_USAJOBS_API_KEY /
WINGMAN_USAJOBS_EMAIL).
"""

from typing import Any

import httpx

from wingman.sources import RawPosting, SourceAdapter, parse_datetime

API_URL = "https://data.usajobs.gov/api/search"

_ANNUAL_CODES = {"PA", "PER YEAR", "ANNUAL"}


def _salary(descriptor: dict[str, Any]) -> tuple[int | None, int | None]:
    for pay in descriptor.get("PositionRemuneration") or []:
        code = str(pay.get("RateIntervalCode") or "").upper()
        if code not in _ANNUAL_CODES:
            continue  # hourly/daily rates would read as absurd annual salaries
        try:
            return int(float(pay["MinimumRange"])), int(float(pay["MaximumRange"]))
        except (KeyError, TypeError, ValueError):
            continue
    return None, None


def parse(payload: dict[str, Any]) -> list[RawPosting]:
    items = ((payload.get("SearchResult") or {}).get("SearchResultItems")) or []
    postings: list[RawPosting] = []
    for item in items:
        descriptor = item.get("MatchedObjectDescriptor") or {}
        salary_min, salary_max = _salary(descriptor)
        details = (descriptor.get("UserArea") or {}).get("Details") or {}
        postings.append(
            RawPosting(
                url=descriptor.get("PositionURI") or "",
                title=descriptor.get("PositionTitle") or "",
                company=descriptor.get("OrganizationName"),
                location=descriptor.get("PositionLocationDisplay"),
                remote=True if details.get("RemoteIndicator") else None,
                salary_min=salary_min,
                salary_max=salary_max,
                description=str(details.get("JobSummary") or ""),
                posted_at=parse_datetime(descriptor.get("PublicationStartDate")),
                raw={"usajobs_id": item.get("MatchedObjectId")},
            )
        )
    return [p for p in postings if p.url and p.title]


class USAJobsSource(SourceAdapter):
    kind = "usajobs"
    default_interval_minutes = 240

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        api_key = (config.get("api_key") or "").strip()
        email = (config.get("email") or "").strip()
        if not api_key or not email:
            raise ValueError("USAJOBS keys are not configured (enter them on the Sources page)")
        params: dict[str, str] = {"ResultsPerPage": "50"}
        if config.get("keyword"):
            params["Keyword"] = str(config["keyword"])
        response = client.get(
            API_URL,
            params=params,
            headers={"Authorization-Key": api_key, "User-Agent": email},
        )
        response.raise_for_status()
        return parse(response.json())
