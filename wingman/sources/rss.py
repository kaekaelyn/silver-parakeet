"""Generic RSS/Atom adapter: escape hatch for any niche job board feed."""

from datetime import UTC, datetime
from typing import Any

import feedparser
import httpx

import wingman.sources as sources


def parse(feed_text: str) -> list[sources.RawPosting]:
    feed = feedparser.parse(feed_text)
    postings: list[sources.RawPosting] = []
    for entry in feed.entries:
        parsed_time = entry.get("published_parsed") or entry.get("updated_parsed")
        posted_at = datetime(*parsed_time[:6], tzinfo=UTC) if parsed_time else None
        postings.append(
            sources.RawPosting(
                url=entry.get("link") or "",
                title=(entry.get("title") or "").strip(),
                description=sources.html_to_text(entry.get("summary") or ""),
                posted_at=posted_at,
                raw={"title": entry.get("title"), "link": entry.get("link")},
            )
        )
    return [p for p in postings if p.url and p.title]


class GenericRSSSource(sources.SourceAdapter):
    kind = "rss"
    default_name = "RSS feed"
    default_interval_minutes = 60

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[sources.RawPosting]:
        feed_url = config.get("feed_url")
        if not feed_url:
            raise ValueError("rss source requires a 'feed_url' in its config")
        response = client.get(feed_url)
        response.raise_for_status()
        return parse(response.text)
