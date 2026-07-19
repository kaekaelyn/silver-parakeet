"""Source adapters: each turns one job board into a list of RawPosting.

Adapters implement fetch(config, client) -> list[RawPosting]. They are
registered in ADAPTERS by kind; a failing adapter must never affect other
sources (the orchestrator in wingman.ingest guarantees isolation).
"""

import html
import re
from abc import ABC, abstractmethod
from datetime import datetime
from html.parser import HTMLParser
from typing import Any, ClassVar

import httpx
from pydantic import BaseModel, Field


class RawPosting(BaseModel):
    url: str
    title: str
    company: str | None = None
    location: str | None = None
    remote: bool | None = None
    salary_min: int | None = None
    salary_max: int | None = None
    description: str = ""
    posted_at: datetime | None = None
    raw: dict[str, Any] = Field(default_factory=dict)


class SourceAdapter(ABC):
    kind: ClassVar[str]
    default_name: ClassVar[str]
    default_interval_minutes: ClassVar[int] = 60
    default_config: ClassVar[dict[str, Any]] = {}

    @abstractmethod
    def fetch(self, config: dict[str, Any], client: httpx.Client) -> list[RawPosting]:
        """Fetch current postings. May raise; callers isolate failures."""


class _TextExtractor(HTMLParser):
    def __init__(self) -> None:
        super().__init__()
        self.chunks: list[str] = []

    def handle_data(self, data: str) -> None:
        self.chunks.append(data)

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag in ("p", "br", "li", "div", "tr"):
            self.chunks.append("\n")


def html_to_text(markup: str) -> str:
    """Best-effort plain text from an HTML fragment."""
    extractor = _TextExtractor()
    extractor.feed(html.unescape(markup))
    text = "".join(extractor.chunks)
    return re.sub(r"\n{3,}", "\n\n", text).strip()


_SALARY_NUMBER = re.compile(r"\$?\s*(\d{1,3}(?:,\d{3})+|\d+(?:\.\d+)?)\s*([kK])?")


def parse_salary_range(text: str) -> tuple[int | None, int | None]:
    """Pull (min, max) integers out of free text like '$100,000 - $130k'."""
    amounts: list[int] = []
    for number, k_suffix in _SALARY_NUMBER.findall(text):
        value = float(number.replace(",", ""))
        if k_suffix:
            value *= 1000
        # Ignore stray small numbers ("40 hours", "401k" is filtered by comma/k rules poorly,
        # so require a plausible annual amount).
        if value >= 10_000:
            amounts.append(int(value))
    if not amounts:
        return None, None
    if len(amounts) == 1:
        return amounts[0], None
    return min(amounts), max(amounts)


def parse_datetime(value: str | None) -> datetime | None:
    if not value:
        return None
    try:
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


from wingman.sources.hn import HackerNewsWhoIsHiringSource  # noqa: E402
from wingman.sources.remoteok import RemoteOKSource  # noqa: E402
from wingman.sources.remotive import RemotiveSource  # noqa: E402
from wingman.sources.rss import GenericRSSSource  # noqa: E402
from wingman.sources.wwr import WeWorkRemotelySource  # noqa: E402

ADAPTERS: dict[str, SourceAdapter] = {
    adapter.kind: adapter
    for adapter in (
        RemotiveSource(),
        RemoteOKSource(),
        WeWorkRemotelySource(),
        HackerNewsWhoIsHiringSource(),
        GenericRSSSource(),
    )
}

# Sources seeded into the DB on first run: (kind, name, config).
DEFAULT_SOURCES: list[tuple[str, str, dict[str, Any]]] = [
    ("remotive", "Remotive", {}),
    ("remoteok", "RemoteOK", {}),
    ("wwr", "We Work Remotely", {"feed_url": "https://weworkremotely.com/remote-jobs.rss"}),
    ("hn", "HN Who is hiring?", {}),
]
