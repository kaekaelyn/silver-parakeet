"""Adzuna search API (https://developer.adzuna.com) — free key required.

The source only exists in the UI once keys are entered on the Sources
page (or via WINGMAN_ADZUNA_APP_ID / WINGMAN_ADZUNA_APP_KEY).
"""

from typing import Any

import httpx

from wingman.sources import RawPosting, SourceAdapter, html_to_text, parse_datetime

API_URL = "https://api.adzuna.com/v1/api/jobs/{country}/search/1"


def _as_int(raw: Any) -> int | None:
    try:
        return int(float(raw))
    except (TypeError, ValueError):
        return None


def parse(payload: dict[str, Any]) -> list[RawPosting]:
    postings: list[RawPosting] = []
    for job in payload.get("results", []):
        company = (job.get("company") or {}).get("display_name")
        location = (job.get("location") or {}).get("display_name")
        postings.append(
            RawPosting(
                url=job.get("redirect_url") or "",
                title=job.get("title") or "",
                company=company,
                location=location,
                salary_min=_as_int(job.get("salary_min")),
                salary_max=_as_int(job.get("salary_max")),
                description=html_to_text(job.get("description") or ""),
                posted_at=parse_datetime(job.get("created")),
                raw={"adzuna_id": job.get("id"), "category": (job.get("category") or {})},
            )
        )
    return [p for p in postings if p.url and p.title]


class AdzunaSource(SourceAdapter):
    kind = "adzuna"
    default_interval_minutes = 240

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        app_id = (config.get("app_id") or "").strip()
        app_key = (config.get("app_key") or "").strip()
        if not app_id or not app_key:
            raise ValueError("Adzuna keys are not configured (enter them on the Sources page)")
        params: dict[str, str] = {
            "app_id": app_id,
            "app_key": app_key,
            "results_per_page": "50",
            "content-type": "application/json",
        }
        if config.get("what"):
            params["what"] = str(config["what"])
        if config.get("where"):
            params["where"] = str(config["where"])
        country = str(config.get("country") or "us").lower()
        response = client.get(API_URL.format(country=country), params=params)
        response.raise_for_status()
        return parse(response.json())
