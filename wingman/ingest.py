"""Normalization, dedupe, and fetch orchestration.

Jobs are deduplicated two ways: by canonical URL (tracking params and
trailing slashes stripped) and by a fuzzy hash of normalized
(company, title, location) — aggregators repost each other's listings
under different URLs.

fetch_source() isolates failures: an adapter that raises records
last_error on its source row and logs an event, and never propagates.
"""

import hashlib
import json
import logging
import re
import sqlite3
from typing import Any
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from wingman import db, scoring
from wingman.sources import ADAPTERS, DEFAULT_SOURCES, RawPosting

logger = logging.getLogger(__name__)

USER_AGENT = "wingman/0.1 (self-hosted job search; +https://github.com/local)"
HTTP_TIMEOUT = 30.0

_TRACKING_PARAMS = re.compile(r"^(utm_|ref$|ref_|source$|gh_src$|lever-)")
_NON_WORD = re.compile(r"[^a-z0-9]+")
_COMPANY_SUFFIXES = re.compile(r"\b(inc|llc|ltd|gmbh|corp|co)\b")


def canonical_url(url: str) -> str:
    scheme, netloc, path, query, _fragment = urlsplit(url.strip())
    netloc = netloc.lower()
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")
    kept = [(k, v) for k, v in parse_qsl(query) if not _TRACKING_PARAMS.match(k.lower())]
    return urlunsplit((scheme.lower(), netloc, path, urlencode(kept), ""))


def _normalize(text: str | None) -> str:
    text = _NON_WORD.sub(" ", (text or "").lower())
    text = _COMPANY_SUFFIXES.sub(" ", text)
    return " ".join(text.split())


def fuzzy_hash(company: str | None, title: str | None, location: str | None) -> str:
    key = "|".join((_normalize(company), _normalize(title), _normalize(location)))
    return hashlib.sha256(key.encode()).hexdigest()


def dedupe_key(posting: RawPosting, url: str) -> str:
    """Fuzzy hash when a company is known; otherwise hash the canonical URL.

    Without a company, distinct jobs sharing a generic title ("Senior
    Software Engineer") would wrongly collapse into one.
    """
    if posting.company:
        return fuzzy_hash(posting.company, posting.title, posting.location)
    return hashlib.sha256(url.encode()).hexdigest()


def make_client() -> httpx.Client:
    return httpx.Client(
        timeout=HTTP_TIMEOUT,
        follow_redirects=True,
        headers={"User-Agent": USER_AGENT},
    )


def ensure_default_sources(conn: sqlite3.Connection) -> None:
    for kind, name, config in DEFAULT_SOURCES:
        exists = conn.execute(
            "SELECT 1 FROM sources WHERE kind = ? AND name = ?", (kind, name)
        ).fetchone()
        if not exists:
            conn.execute(
                "INSERT INTO sources (kind, name, config_json) VALUES (?, ?, ?)",
                (kind, name, json.dumps(config)),
            )
    conn.commit()


def store_postings(
    conn: sqlite3.Connection, source_id: int, postings: list[RawPosting]
) -> tuple[int, int]:
    """Insert new postings; return (new, duplicates)."""
    new = duplicates = 0
    for posting in postings:
        if not posting.url.strip() or not posting.title.strip():
            continue  # never let a malformed entry become a garbage row
        url = canonical_url(posting.url)
        dedupe = dedupe_key(posting, url)
        exists = conn.execute(
            "SELECT 1 FROM jobs WHERE url = ? OR dedupe_hash = ?", (url, dedupe)
        ).fetchone()
        if exists:
            duplicates += 1
            continue
        conn.execute(
            """INSERT INTO jobs (source_id, dedupe_hash, url, title, company, location,
                                 remote, salary_min, salary_max, description, posted_at,
                                 raw_json)
               VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                source_id,
                dedupe,
                url,
                posting.title,
                posting.company,
                posting.location,
                None if posting.remote is None else int(posting.remote),
                posting.salary_min,
                posting.salary_max,
                posting.description,
                posting.posted_at.isoformat() if posting.posted_at else None,
                # The description already lives in its own column; don't
                # store the raw HTML copy of it a second time.
                json.dumps(
                    {
                        "original_url": posting.url,
                        **{k: v for k, v in posting.raw.items() if k != "description"},
                    },
                    default=str,
                ),
            ),
        )
        new += 1
    conn.commit()
    return new, duplicates


def fetch_source(
    conn: sqlite3.Connection, source_id: int, client: httpx.Client | None = None
) -> dict[str, Any]:
    """Fetch one source. Never raises: failures are recorded, not propagated."""
    row = conn.execute("SELECT * FROM sources WHERE id = ?", (source_id,)).fetchone()
    if row is None:
        return {"ok": False, "error": f"no source with id {source_id}"}
    config = json.loads(row["config_json"] or "{}")
    own_client = client is None
    if own_client:
        client = make_client()
    try:
        adapter = ADAPTERS[row["kind"]]
        postings = adapter.fetch(config, client)
        new, duplicates = store_postings(conn, source_id, postings)
        scoring.score_new_jobs(conn)
        conn.execute(
            "UPDATE sources SET last_fetch_at = datetime('now'), last_error = NULL WHERE id = ?",
            (source_id,),
        )
        result = {"ok": True, "found": len(postings), "new": new, "duplicates": duplicates}
        db.record_event(conn, "fetch.ok", json.dumps({"source": row["name"], **result}))
        logger.info("fetched %s: %d found, %d new", row["name"], len(postings), new)
        return result
    except Exception as exc:
        error = f"{type(exc).__name__}: {exc}"
        conn.execute(
            "UPDATE sources SET last_fetch_at = datetime('now'), last_error = ? WHERE id = ?",
            (error, source_id),
        )
        db.record_event(conn, "fetch.error", json.dumps({"source": row["name"], "error": error}))
        logger.exception("fetch failed for source %s", row["name"])
        return {"ok": False, "error": error}
    finally:
        if own_client:
            client.close()


def fetch_all_enabled(conn: sqlite3.Connection) -> list[dict[str, Any]]:
    source_ids = [
        row["id"] for row in conn.execute("SELECT id FROM sources WHERE enabled = 1 ORDER BY id")
    ]
    results = []
    with make_client() as client:
        for source_id in source_ids:
            results.append(fetch_source(conn, source_id, client))
    return results
