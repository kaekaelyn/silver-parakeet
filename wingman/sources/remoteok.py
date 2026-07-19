"""RemoteOK public JSON API (https://remoteok.com/api)."""

from datetime import UTC, datetime
from typing import Any

import httpx

import wingman.sources as sources

API_URL = "https://remoteok.com/api"


def _posted_at(job: dict[str, Any]) -> datetime | None:
    if job.get("date"):
        parsed = sources.parse_datetime(job["date"])
        if parsed:
            return parsed
    if job.get("epoch"):
        try:
            return datetime.fromtimestamp(int(job["epoch"]), tz=UTC)
        except (ValueError, OSError):
            return None
    return None


def parse(payload: list[dict[str, Any]]) -> list[sources.RawPosting]:
    postings: list[sources.RawPosting] = []
    for job in payload:
        # The first array element is a legal notice, not a job.
        if "position" not in job or "company" not in job:
            continue
        postings.append(
            sources.RawPosting(
                url=job.get("url") or job.get("apply_url") or "",
                title=job["position"],
                company=job["company"],
                location=job.get("location") or None,
                remote=True,
                salary_min=job.get("salary_min") or None,
                salary_max=job.get("salary_max") or None,
                description=sources.html_to_text(job.get("description") or ""),
                posted_at=_posted_at(job),
                raw=job,
            )
        )
    return [p for p in postings if p.url]


class RemoteOKSource(sources.SourceAdapter):
    kind = "remoteok"
    default_name = "RemoteOK"
    default_interval_minutes = 60

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[sources.RawPosting]:
        response = client.get(API_URL)
        response.raise_for_status()
        return parse(response.json())
