import json
from pathlib import Path

import httpx

from wingman.sources import hn, remoteok, remotive, rss, wwr

FIXTURES = Path(__file__).parent / "fixtures"


def test_remotive_parse() -> None:
    payload = json.loads((FIXTURES / "remotive.json").read_text())
    postings = remotive.parse(payload)
    assert len(postings) == 3
    first = postings[0]
    assert first.title == "Senior Backend Engineer"
    assert first.company == "Acme Inc."
    assert first.location == "Worldwide"
    assert first.remote is True
    assert (first.salary_min, first.salary_max) == (120000, 150000)
    assert first.posted_at is not None
    assert "<p>" not in first.description
    assert "PostgreSQL at scale" in first.description


def test_remoteok_parse_skips_legal_notice() -> None:
    payload = json.loads((FIXTURES / "remoteok.json").read_text())
    postings = remoteok.parse(payload)
    assert len(postings) == 2
    first = postings[0]
    assert first.company == "Acme"
    assert first.title == "Senior Backend Engineer"
    assert (first.salary_min, first.salary_max) == (120000, 150000)
    assert first.posted_at is not None


def test_wwr_parse_splits_company_from_title() -> None:
    postings = wwr.parse((FIXTURES / "wwr.rss").read_text())
    assert len(postings) == 2
    first = postings[0]
    assert first.company == "PixelWorks"
    assert first.title == "Senior Frontend Developer"
    assert first.location == "Anywhere in the World"
    assert first.posted_at is not None
    assert "TypeScript" in first.description


def test_hn_parse_top_level_comments() -> None:
    item = json.loads((FIXTURES / "hn_item.json").read_text())
    postings = hn.parse(item)
    # Three children, one deleted (no text) — replies to comments are not parsed.
    assert len(postings) == 2
    first = postings[0]
    assert first.company == "Nimbus Robotics"
    assert first.title == "Senior Python Engineer"
    assert first.location == "Remote (US)"
    assert first.remote is True
    assert (first.salary_min, first.salary_max) == (140000, 170000)
    assert first.url == "https://news.ycombinator.com/item?id=44444100"
    second = postings[1]
    assert second.company == "Foo Labs"
    assert second.location == "Berlin, Germany"
    assert second.remote is None


def test_generic_rss_parse() -> None:
    postings = rss.parse((FIXTURES / "generic.rss").read_text())
    assert len(postings) == 2
    assert postings[0].title == "Django Developer at Riverbend Software"
    assert postings[0].url == "https://djangojobs.example/jobs/riverbend-django-developer"
    assert postings[0].posted_at is not None


def test_hn_fetch_two_step_with_mock_transport() -> None:
    search_payload = (FIXTURES / "hn_search.json").read_text()
    item_payload = (FIXTURES / "hn_item.json").read_text()
    calls: list[str] = []

    def handler(request: httpx.Request) -> httpx.Response:
        calls.append(request.url.path)
        if request.url.path == "/api/v1/search_by_date":
            return httpx.Response(200, text=search_payload)
        return httpx.Response(200, text=item_payload)

    client = httpx.Client(transport=httpx.MockTransport(handler))
    postings = hn.HackerNewsWhoIsHiringSource().fetch({}, client)
    assert len(postings) == 2
    assert calls == ["/api/v1/search_by_date", "/api/v1/items/44444001"]

    # With a pinned story_id the search step is skipped.
    calls.clear()
    postings = hn.HackerNewsWhoIsHiringSource().fetch({"story_id": 44444001}, client)
    assert len(postings) == 2
    assert calls == ["/api/v1/items/44444001"]
