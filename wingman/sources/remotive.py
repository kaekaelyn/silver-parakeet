"""Remotive public JSON API (https://remotive.com/api/remote-jobs)."""

from typing import Any

import httpx

import wingman.sources as sources

API_URL = "https://remotive.com/api/remote-jobs"


def parse(payload: dict[str, Any]) -> list[sources.RawPosting]:
    postings: list[sources.RawPosting] = []
    for job in payload.get("jobs", []):
        salary_min, salary_max = sources.parse_salary_range(job.get("salary") or "")
        postings.append(
            sources.RawPosting(
                url=job["url"],
                title=job["title"],
                company=job.get("company_name"),
                location=job.get("candidate_required_location"),
                remote=True,
                salary_min=salary_min,
                salary_max=salary_max,
                description=sources.html_to_text(job.get("description") or ""),
                posted_at=sources.parse_datetime(job.get("publication_date")),
                raw=job,
            )
        )
    return postings


class RemotiveSource(sources.SourceAdapter):
    kind = "remotive"
    default_name = "Remotive"
    default_interval_minutes = 60

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[sources.RawPosting]:
        params: dict[str, str] = {}
        if config.get("search"):
            params["search"] = config["search"]
        if config.get("limit"):
            params["limit"] = str(config["limit"])
        response = client.get(API_URL, params=params)
        response.raise_for_status()
        return parse(response.json())
