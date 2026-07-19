"""We Work Remotely RSS feeds (item titles are 'Company: Role')."""

from datetime import UTC, datetime
from time import struct_time
from typing import Any

import feedparser
import httpx

import wingman.sources as sources

DEFAULT_FEED_URL = "https://weworkremotely.com/remote-jobs.rss"


def _entry_datetime(entry: Any) -> datetime | None:
    parsed: struct_time | None = entry.get("published_parsed")
    if not parsed:
        return None
    return datetime(*parsed[:6], tzinfo=UTC)


def parse(feed_text: str) -> list[sources.RawPosting]:
    feed = feedparser.parse(feed_text)
    postings: list[sources.RawPosting] = []
    for entry in feed.entries:
        title = entry.get("title") or ""
        company, _, role = title.partition(": ")
        if not role:
            company, role = None, title
        postings.append(
            sources.RawPosting(
                url=entry.get("link") or "",
                title=role.strip(),
                company=company.strip() if company else None,
                location=(entry.get("region") or "").strip() or None,
                remote=True,
                description=sources.html_to_text(entry.get("summary") or ""),
                posted_at=_entry_datetime(entry),
                raw={"title": title, "link": entry.get("link"), "id": entry.get("id")},
            )
        )
    return [p for p in postings if p.url and p.title]


class WeWorkRemotelySource(sources.SourceAdapter):
    kind = "wwr"
    default_name = "We Work Remotely"
    default_interval_minutes = 120
    default_config = {"feed_url": DEFAULT_FEED_URL}

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[sources.RawPosting]:
        response = client.get(config.get("feed_url") or DEFAULT_FEED_URL)
        response.raise_for_status()
        return parse(response.text)
