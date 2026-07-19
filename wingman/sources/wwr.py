"""We Work Remotely RSS feeds (item titles are 'Company: Role')."""

from typing import Any

import feedparser
import httpx

from wingman.sources import RawPosting, SourceAdapter, feed_entry_datetime, html_to_text

DEFAULT_FEED_URL = "https://weworkremotely.com/remote-jobs.rss"


def parse(feed_text: str) -> list[RawPosting]:
    feed = feedparser.parse(feed_text)
    postings: list[RawPosting] = []
    for entry in feed.entries:
        title = entry.get("title") or ""
        company, _, role = title.partition(": ")
        if not role:
            company, role = None, title
        postings.append(
            RawPosting(
                url=entry.get("link") or "",
                title=role.strip(),
                company=company.strip() if company else None,
                location=(entry.get("region") or "").strip() or None,
                remote=True,
                description=html_to_text(entry.get("summary") or ""),
                posted_at=feed_entry_datetime(entry),
                raw={"title": title, "link": entry.get("link"), "id": entry.get("id")},
            )
        )
    return [p for p in postings if p.url and p.title]


class WeWorkRemotelySource(SourceAdapter):
    kind = "wwr"
    default_interval_minutes = 120

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        response = client.get(config.get("feed_url") or DEFAULT_FEED_URL)
        response.raise_for_status()
        return parse(response.text)
