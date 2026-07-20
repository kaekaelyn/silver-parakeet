"""Shared timestamp parsing: one place for the naive-means-UTC rule."""

from datetime import UTC, datetime


def parse_timestamp(stamp: str | None) -> datetime | None:
    """Parse an ISO-ish timestamp; naive values are treated as UTC."""
    if not stamp:
        return None
    try:
        parsed = datetime.fromisoformat(stamp)
    except ValueError:
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=UTC)
    return parsed
