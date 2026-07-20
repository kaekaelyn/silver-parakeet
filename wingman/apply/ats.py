"""ATS detection from job URLs (and page HTML for captured jobs)."""

import sqlite3
from urllib.parse import urlparse

# Fillers exist for these (PLAN §11 M5 + M7b: all four hosted boards).
SUPPORTED = ("greenhouse", "lever", "ashby", "workable")
# Recognized boards get labeled even if a filler ever lags behind.
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
        return _with_suffix(url, "/apply")
    host = (urlparse(url).hostname or "").lower()
    # Only rewrite on the boards' own hosts — company-site embeds keep
    # their URL (the form is on the page itself).
    if kind == "ashby" and (host == "ashbyhq.com" or host.endswith(".ashbyhq.com")):
        # jobs.ashbyhq.com/<company>/<id>; the form tab at .../application.
        return _with_suffix(url, "/application")
    if kind == "workable" and (host == "workable.com" or host.endswith(".workable.com")):
        # apply.workable.com/<company>/j/<id>; the form at .../apply.
        return _with_suffix(url, "/apply")
    return url


def _with_suffix(url: str, suffix: str) -> str:
    stripped = url.split("?")[0].rstrip("/")
    if not stripped.endswith(suffix):
        return stripped + suffix
    return stripped
