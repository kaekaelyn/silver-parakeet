"""Paste-a-URL capture: turn any job page into a tracked job.

Parses schema.org JSON-LD JobPosting markup (common on Greenhouse, Lever,
and most career pages); falls back to <title>/meta heuristics. This is the
supported path for LinkedIn/Indeed/anything — no scraping or automation.
"""

import json
import logging
import sqlite3
from html.parser import HTMLParser
from typing import Any

import httpx

from wingman import db, ingest, scoring
from wingman.sources import RawPosting, html_to_text, parse_datetime

logger = logging.getLogger(__name__)

CAPTURE_SOURCE_NAME = "Captured"
MAX_PAGE_BYTES = 5 * 1024 * 1024  # a job page over 5MB is not a job page


class _PageExtractor(HTMLParser):
    """Collects JSON-LD script bodies, the <title>, and meta tags."""

    def __init__(self) -> None:
        super().__init__()
        self.ld_json_blocks: list[str] = []
        self.title = ""
        self.meta: dict[str, str] = {}
        self._in_ld_json = False
        self._in_title = False

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        attrs_dict = {k: v or "" for k, v in attrs}
        if tag == "script" and attrs_dict.get("type", "").lower() == "application/ld+json":
            self._in_ld_json = True
            self.ld_json_blocks.append("")
        elif tag == "title":
            self._in_title = True
        elif tag == "meta":
            key = attrs_dict.get("property") or attrs_dict.get("name")
            if key and "content" in attrs_dict:
                self.meta.setdefault(key.lower(), attrs_dict["content"])

    def handle_endtag(self, tag: str) -> None:
        if tag == "script":
            self._in_ld_json = False
        elif tag == "title":
            self._in_title = False

    def handle_data(self, data: str) -> None:
        if self._in_ld_json:
            self.ld_json_blocks[-1] += data
        elif self._in_title:
            self.title += data


def _iter_ld_objects(block: str) -> list[dict[str, Any]]:
    try:
        parsed = json.loads(block)
    except json.JSONDecodeError:
        return []
    if isinstance(parsed, dict):
        if "@graph" in parsed and isinstance(parsed["@graph"], list):
            return [obj for obj in parsed["@graph"] if isinstance(obj, dict)]
        return [parsed]
    if isinstance(parsed, list):
        return [obj for obj in parsed if isinstance(obj, dict)]
    return []


def _find_jobposting(extractor: _PageExtractor) -> dict[str, Any] | None:
    for block in extractor.ld_json_blocks:
        for obj in _iter_ld_objects(block):
            type_field = obj.get("@type", "")
            types = type_field if isinstance(type_field, list) else [type_field]
            if any(str(t).lower() == "jobposting" for t in types):
                return obj
    return None


def _location_from(posting: dict[str, Any]) -> str | None:
    locations = posting.get("jobLocation")
    if isinstance(locations, dict):
        locations = [locations]
    if isinstance(locations, list):
        for loc in locations:
            address = loc.get("address", {}) if isinstance(loc, dict) else {}
            if isinstance(address, dict):
                parts = [
                    address.get("addressLocality"),
                    address.get("addressRegion"),
                    address.get("addressCountry"),
                ]
                joined = ", ".join(str(p) for p in parts if p)
                if joined:
                    return joined
    return None


def _salary_from(posting: dict[str, Any]) -> tuple[int | None, int | None]:
    base = posting.get("baseSalary")
    if not isinstance(base, dict):
        return None, None
    value = base.get("value")
    if not isinstance(value, dict):
        return None, None

    def as_int(raw: Any) -> int | None:
        try:
            return int(float(raw))
        except (TypeError, ValueError):
            return None

    minimum = as_int(value.get("minValue"))
    if minimum is None:  # explicit check: a legitimate 0 minimum is not "missing"
        minimum = as_int(value.get("value"))
    return minimum, as_int(value.get("maxValue"))


def parse_job_page(page_html: str, url: str) -> RawPosting:
    """Extract a posting from a job page; JSON-LD first, meta fallback."""
    extractor = _PageExtractor()
    extractor.feed(page_html)

    posting = _find_jobposting(extractor)
    if posting is not None:
        org = posting.get("hiringOrganization")
        company = org.get("name") if isinstance(org, dict) else (org or None)
        salary_min, salary_max = _salary_from(posting)
        remote = True if str(posting.get("jobLocationType", "")).upper() == "TELECOMMUTE" else None
        return RawPosting(
            url=url,
            title=str(posting.get("title") or extractor.title or url).strip(),
            company=str(company).strip() if company else None,
            location=_location_from(posting),
            remote=remote,
            salary_min=salary_min,
            salary_max=salary_max,
            description=html_to_text(str(posting.get("description") or "")),
            posted_at=parse_datetime(posting.get("datePosted")),
            raw={"captured": True, "jsonld": True},
        )

    # Fallback: page title + meta description.
    title = (extractor.meta.get("og:title") or extractor.title or url).strip()
    company = extractor.meta.get("og:site_name")
    description = extractor.meta.get("description") or extractor.meta.get("og:description") or ""
    return RawPosting(
        url=url,
        title=title,
        company=company.strip() if company else None,
        description=html_to_text(description),
        raw={"captured": True, "jsonld": False},
    )


def ensure_capture_source(conn: sqlite3.Connection) -> int:
    row = conn.execute("SELECT id FROM sources WHERE kind = 'capture'").fetchone()
    if row:
        return row["id"]
    cursor = conn.execute(
        # enabled=0: the scheduler must never poll the capture pseudo-source.
        "INSERT INTO sources (kind, name, config_json, enabled) VALUES ('capture', ?, '{}', 0)",
        (CAPTURE_SOURCE_NAME,),
    )
    conn.commit()
    return cursor.lastrowid


def capture_url(conn: sqlite3.Connection, url: str, client: httpx.Client | None = None) -> int:
    """Fetch a job page and store it as a job. Returns the job id."""
    own_client = client is None
    if own_client:
        client = ingest.make_client()
    try:
        # Stream with a size cap: a runaway download must never balloon
        # the daemon's memory (reliability over features).
        with client.stream("GET", url) as response:
            response.raise_for_status()
            chunks: list[bytes] = []
            received = 0
            for chunk in response.iter_bytes():
                received += len(chunk)
                if received > MAX_PAGE_BYTES:
                    raise ValueError("page is too large to be a job posting")
                chunks.append(chunk)
        page_html = b"".join(chunks).decode(response.encoding or "utf-8", errors="replace")
    finally:
        if own_client:
            client.close()
    posting = parse_job_page(page_html, url)
    source_id = ensure_capture_source(conn)

    canonical = ingest.canonical_url(posting.url)
    existing = conn.execute(
        "SELECT id FROM jobs WHERE url = ? OR dedupe_hash = ?",
        (canonical, ingest.dedupe_key(posting, canonical)),
    ).fetchone()
    if existing:
        db.record_event(conn, "capture.duplicate", json.dumps({"url": url}))
        return existing["id"]

    new, _ = ingest.store_postings(conn, source_id, [posting])
    if new != 1:
        raise ValueError("page could not be captured as a job (missing title or url)")
    job_id = conn.execute("SELECT id FROM jobs WHERE url = ?", (canonical,)).fetchone()["id"]
    db.record_event(conn, "capture.ok", json.dumps({"url": url, "job_id": job_id}))
    # The job is safely stored; a scoring hiccup must not fail the capture.
    try:
        scoring.score_new_jobs(conn)
    except Exception as exc:
        conn.rollback()
        db.record_event(conn, "scoring.error", json.dumps({"error": str(exc)}))
        logger.exception("scoring failed after capture of %s", url)
    return job_id
