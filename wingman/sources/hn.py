"""Hacker News 'Ask HN: Who is hiring?' via the Algolia API.

Finds the latest monthly thread, then parses its top-level comments.
Comment convention: first line is 'Company | Role | Location | ...'.
"""

from typing import Any

import httpx

from wingman.sources import (
    RawPosting,
    SourceAdapter,
    html_to_text,
    parse_datetime,
    parse_salary_range,
)

SEARCH_URL = "https://hn.algolia.com/api/v1/search_by_date"
ITEM_URL = "https://hn.algolia.com/api/v1/items/{item_id}"
THREAD_TITLE_PREFIX = "Ask HN: Who is hiring?"


def find_latest_thread_id(client: httpx.Client) -> int:
    response = client.get(
        SEARCH_URL,
        params={
            "query": f'"{THREAD_TITLE_PREFIX}"',
            "tags": "story,author_whoishiring",
            "hitsPerPage": "5",
        },
    )
    response.raise_for_status()
    for hit in response.json().get("hits", []):
        if (hit.get("title") or "").startswith(THREAD_TITLE_PREFIX):
            return int(hit["objectID"])
    raise ValueError("no 'Who is hiring?' thread found")


def parse(item: dict[str, Any]) -> list[RawPosting]:
    postings: list[RawPosting] = []
    for comment in item.get("children", []):
        text_html = comment.get("text")
        if not text_html:  # deleted/dead comments have no text
            continue
        text = html_to_text(text_html)
        first_line = text.split("\n", 1)[0]
        fields = [part.strip() for part in first_line.split("|")]
        company = fields[0] if fields[0] else None
        title = fields[1] if len(fields) > 1 and fields[1] else first_line[:120]
        location = fields[2] if len(fields) > 2 and fields[2] else None
        remote = "remote" in first_line.lower() or None
        salary_min, salary_max = parse_salary_range(first_line)
        postings.append(
            RawPosting(
                url=f"https://news.ycombinator.com/item?id={comment['id']}",
                title=title,
                company=company,
                location=location,
                remote=remote,
                salary_min=salary_min,
                salary_max=salary_max,
                description=text,
                posted_at=parse_datetime(comment.get("created_at")),
                raw={"comment_id": comment.get("id"), "author": comment.get("author")},
            )
        )
    return postings


class HackerNewsWhoIsHiringSource(SourceAdapter):
    kind = "hn"
    default_interval_minutes = 720

    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        thread_id = config.get("story_id") or find_latest_thread_id(client)
        response = client.get(ITEM_URL.format(item_id=thread_id))
        response.raise_for_status()
        return parse(response.json())
