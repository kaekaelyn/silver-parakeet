"""Generic RSS/Atom adapter: escape hatch for any niche job board feed."""

from typing import Any

import feedparser
import httpx

from wingman.sources import RawPosting, SourceAdapter, feed_entry_datetime, html_to_text


def parse(feed_text: str) -> list[RawPosting]:
    feed = feedparser.parse(feed_text)
    if not feed.entries and not feed.get("version"):
        # A user-supplied URL that isn't a feed should surface as a source
        # error, not silently report zero jobs forever. feedparser leaves
        # version empty when it can't recognize a feed format.
        raise ValueError("not a valid RSS/Atom feed")
    postings: list[RawPosting] = []
    for entry in feed.entries:
        postings.append(
            RawPosting(
                url=entry.get("link") or "",
                title=(entry.get("title") or "").strip(),
                description=html_to_text(entry.get("summary") or ""),
                posted_at=feed_entry_datetime(entry),
                raw={"title": entry.get("title"), "link": entry.get("link")},
            )
        )
    return [p for p in postings if p.url and p.title]


class GenericRSSSource(SourceAdapter):
    kind = "rss"
    default_interval_minutes = 60

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        feed_url = config.get("feed_url")
        if not feed_url:
            raise ValueError("rss source requires a 'feed_url' in its config")
        response = client.get(feed_url)
        response.raise_for_status()
        return parse(response.text)
