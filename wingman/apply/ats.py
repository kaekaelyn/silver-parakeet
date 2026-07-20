"""ATS detection from job URLs (and page HTML for captured jobs)."""

import sqlite3
from urllib.parse import urlparse

# Fillers exist for these (PLAN §11 M5: Greenhouse + Lever first).
SUPPORTED = ("greenhouse", "lever")
# Recognized-but-not-yet-fillable boards still get labeled.
KNOWN = ("greenhouse", "lever", "ashby", "workable")

_HOST_SUFFIXES = (
    ("greenhouse.io", "greenhouse"),
    ("lever.co", "lever"),
    ("ashbyhq.com", "ashby"),
    ("workable.com", "workable"),
)

_PAGE_MARKERS = (
    ("boards.greenhouse.io", "greenhouse"),
    ("job-boards.greenhouse.io", "greenhouse"),
    ("jobs.lever.co", "lever"),
    ("jobs.ashbyhq.com", "ashby"),
    ("apply.workable.com", "workable"),
)


def detect_ats(url: str) -> str | None:
    """ATS kind from a URL's host, or None."""
    host = (urlparse(url).hostname or "").lower()
    for suffix, kind in _HOST_SUFFIXES:
        if host == suffix or host.endswith("." + suffix):
            return kind
    return None


def detect_ats_in_page(html: str) -> str | None:
    """ATS kind from page HTML (company sites embed their board's domain)."""
    lowered = html.lower()
    for marker, kind in _PAGE_MARKERS:
        if marker in lowered:
            return kind
    return None


def ensure_ats_kind(conn: sqlite3.Connection, job: sqlite3.Row) -> str | None:
    """Return the job's ats_kind, detecting and caching it if missing."""
    if job["ats_kind"]:
        return job["ats_kind"]
    kind = detect_ats(job["url"])
    if kind:
        conn.execute("UPDATE jobs SET ats_kind = ? WHERE id = ?", (kind, job["id"]))
        conn.commit()
    return kind


def apply_url(kind: str, url: str) -> str:
    """The URL of the actual application form for a posting URL."""
    if kind == "lever":
        # Lever postings live at /<company>/<id>; the form at .../apply.
        stripped = url.split("?")[0].rstrip("/")
        if not stripped.endswith("/apply"):
            return stripped + "/apply"
        return stripped
    return url
